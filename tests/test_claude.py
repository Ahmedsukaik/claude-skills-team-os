"""The Claude model: the request it sends, how it reads replies, and how API errors map to the
fixed rules fallback. No live API call is made: the last tests run the real `anthropic` SDK
against a local fake server that answers in the documented shape."""
from __future__ import annotations

from typing import Any

import anthropic
import httpx2 as httpx
import pytest
from conftest import free_port, serve
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from teamos.models import DEFAULT_MODEL, ClaudeModel, ModelUnavailable, cost_usd
from teamos.prompts import SYSTEM_PROMPT
from teamos.tools import TOOLS

MESSAGES = [{"role": "user", "content": [{"type": "text", "text": "Give me the weekly pipeline summary."}]}]


class FakeClient:
    def __init__(self, reply: Any):
        self.reply = reply
        self.requests: list[dict[str, Any]] = []
        self.messages = self

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def model(reply: Any = None, **kw: Any) -> ClaudeModel:
    return ClaudeModel(client=FakeClient(reply), **kw)


def test_the_request_caches_the_skill_list_and_switches_thinking_off(monkeypatch):
    for name in ("TEAMOS_CLAUDE_MODEL", "TEAMOS_CLAUDE_EFFORT", "TEAMOS_STRICT_TOOLS"):
        monkeypatch.delenv(name, raising=False)
    req = model().request(SYSTEM_PROMPT, TOOLS, MESSAGES)
    assert req["model"] == DEFAULT_MODEL == "claude-haiku-5-5" and req["max_tokens"] == 1500
    assert req["system"] == [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
    assert "<available_skills>" in req["system"][0]["text"]
    assert req["thinking"] == {"type": "disabled"} and req["output_config"] == {"effort": "low"}
    assert req["cache_control"] == {"type": "ephemeral"}
    assert all("strict" not in t for t in req["tools"]) and req["messages"] is MESSAGES  # strict is off by default
    monkeypatch.setenv("TEAMOS_STRICT_TOOLS", "on")
    assert all(t["strict"] is True for t in model().request(SYSTEM_PROMPT, TOOLS, MESSAGES)["tools"])


def test_strict_tool_schemas_close_every_object():
    def closed(schema: dict[str, Any]) -> bool:
        if schema.get("type") == "object":
            if schema.get("additionalProperties") is not False or not set(schema.get("required", [])) <= set(schema["properties"]):
                return False
            return all(closed(v) for v in schema["properties"].values())
        if schema.get("type") == "array":
            return closed(schema["items"])
        return True
    assert all(closed(t["input_schema"]) for t in TOOLS)


def test_settings_come_from_the_projects_own_variables(monkeypatch):
    monkeypatch.setenv("TEAMOS_CLAUDE_EFFORT", "medium")
    monkeypatch.setenv("TEAMOS_STRICT_TOOLS", "off")
    monkeypatch.setenv("CLAUDE_EFFORT", "xhigh")  # set by other tools; never read here
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-5-5")
    req = model().request(SYSTEM_PROMPT, TOOLS, MESSAGES)
    assert req["model"] == "claude-haiku-5-5" and req["output_config"] == {"effort": "medium"}
    assert all("strict" not in t for t in req["tools"])


def test_models_and_efforts_that_cannot_run_with_thinking_off_are_refused_at_start(monkeypatch):
    monkeypatch.setenv("TEAMOS_CLAUDE_MODEL", "claude-sonnet-5-5")
    with pytest.raises(ValueError, match="thinking off"):
        model()
    monkeypatch.delenv("TEAMOS_CLAUDE_MODEL")
    monkeypatch.setenv("TEAMOS_CLAUDE_EFFORT", "xhigh")
    with pytest.raises(ValueError):
        model()


def test_the_client_does_not_retry_and_has_a_short_timeout(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-local-test-not-a-real-key")
    client = ClaudeModel()._client
    assert client.max_retries == 0 and client.timeout.read == 20.0 and client.timeout.connect == 3.0


def test_replies_keep_text_and_tool_calls_and_drop_the_rest():
    reply = {"model": "claude-haiku-5-5", "stop_reason": "tool_use",
             "usage": {"input_tokens": 50, "output_tokens": 20, "cache_read_input_tokens": 3000, "cache_creation_input_tokens": 0},
             "content": [{"type": "thinking", "thinking": "hmm", "signature": "s"}, {"type": "text", "text": "\n\n"},
                         {"type": "text", "text": "Loading the skill."},
                         {"type": "tool_use", "id": "toolu_01", "name": "load_skill", "input": {"name": "weekly-pipeline"}}]}
    turn = model(reply).respond(SYSTEM_PROMPT, TOOLS, MESSAGES)
    assert turn.content == [{"type": "text", "text": "Loading the skill."},
                            {"type": "tool_use", "id": "toolu_01", "name": "load_skill", "input": {"name": "weekly-pipeline"}}]
    assert turn.stop_reason == "tool_use" and turn.mode == "live" and turn.usage["cache_read_input_tokens"] == 3000


def test_cost_counts_cache_reads_and_writes():
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000,
             "cache_creation_input_tokens": 2_000_000, "cache_write_5m_tokens": 1_000_000}
    assert cost_usd("claude-haiku-5-5", usage) == pytest.approx(0.10 + 0.50 + 0.01 + 0.125 + 0.20)
    assert cost_usd("guided", usage) == 0.0


def _response(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))


@pytest.mark.parametrize("error, kind", [
    (anthropic.RateLimitError("limit", response=_response(429),
                              body={"error": {"type": "rate_limit_error", "details": {"error_code": "enforced_spend_limit_reached"}}}),
     "budget"),
    (anthropic.RateLimitError("slow down", response=_response(429), body={"error": {"type": "rate_limit_error"}}), "rate_limited"),
    (anthropic.BadRequestError("bad", response=_response(400), body={"error": {
        "type": "invalid_request_error", "message": "You have reached your specified workspace API usage limits."}}), "budget"),
    (anthropic.BadRequestError("bad", response=_response(400), body={"error": {"message": "messages: bad"}}), "invalid"),
    (anthropic.AuthenticationError("no", response=_response(401), body=None), "auth"),
    (anthropic.InternalServerError("oops", response=_response(500), body=None), "error"),
    (anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com")), "error"),
])
def test_api_errors_become_a_reason_to_fall_back(error, kind):
    with pytest.raises(ModelUnavailable) as caught:
        model(error).respond(SYSTEM_PROMPT, TOOLS, MESSAGES)
    assert caught.value.kind == kind


# ---------------------------------------------------------------------------- the real SDK, a fake server
def fake_api(answer: Any) -> tuple[FastAPI, dict[str, Any]]:
    seen: dict[str, Any] = {}
    app = FastAPI()

    @app.post("/v1/messages")
    async def messages(request: Request) -> Any:
        seen["headers"], seen["body"] = dict(request.headers), await request.json()
        return answer if isinstance(answer, JSONResponse) else answer(seen["body"])

    return app, seen


def test_the_real_sdk_sends_the_expected_request_and_reads_the_reply():
    app, seen = fake_api(lambda body: {
        "id": "msg_local", "type": "message", "role": "assistant", "model": body["model"],
        "content": [{"type": "tool_use", "id": "toolu_local_1", "name": "load_skill", "input": {"name": "weekly-pipeline"}}],
        "stop_reason": "tool_use", "stop_sequence": None,
        "usage": {"input_tokens": 40, "output_tokens": 18, "cache_creation_input_tokens": 3900, "cache_read_input_tokens": 0}})
    port = free_port()
    server = serve(app, port)
    try:
        client = anthropic.Anthropic(api_key="sk-local-test-not-a-real-key", base_url=f"http://127.0.0.1:{port}", max_retries=0)
        turn = ClaudeModel(client=client, model="claude-haiku-5-5", effort="low").respond(SYSTEM_PROMPT, TOOLS, MESSAGES)
    finally:
        server.should_exit = True
    body = seen["body"]
    assert seen["headers"]["x-api-key"] == "sk-local-test-not-a-real-key" and "anthropic-version" in seen["headers"]
    assert body["thinking"] == {"type": "disabled"} and body["output_config"] == {"effort": "low"}
    assert body["cache_control"] == {"type": "ephemeral"} and body["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert [t["name"] for t in body["tools"]] == [t["name"] for t in TOOLS] and "strict" not in body["tools"][0]  # off by default
    assert body["tools"][0]["input_schema"]["properties"]["name"]["enum"][0] == "crm-update"
    assert turn.content == [{"type": "tool_use", "id": "toolu_local_1", "name": "load_skill", "input": {"name": "weekly-pipeline"}}]
    assert turn.usage["cache_creation_input_tokens"] == 3900 and turn.model == "claude-haiku-5-5"


@pytest.mark.parametrize("status, error, kind", [
    (400, {"type": "invalid_request_error", "message": "You have reached your specified workspace API usage limits. Retry in May."},
     "budget"),
    (429, {"type": "rate_limit_error", "message": "Spend limit reached", "details": {"error_code": "enforced_spend_limit_reached"}},
     "budget"),
    (429, {"type": "rate_limit_error", "message": "Number of requests has exceeded your rate limit"}, "rate_limited"),
    (529, {"type": "overloaded_error", "message": "Overloaded"}, "error"),
])
def test_the_real_sdk_turns_api_errors_into_a_fallback(status, error, kind):
    app, _ = fake_api(JSONResponse({"type": "error", "error": error}, status_code=status))
    port = free_port()
    server = serve(app, port)
    try:
        client = anthropic.Anthropic(api_key="sk-local-test-not-a-real-key", base_url=f"http://127.0.0.1:{port}", max_retries=0)
        with pytest.raises(ModelUnavailable) as caught:
            ClaudeModel(client=client).respond(SYSTEM_PROMPT, TOOLS, MESSAGES)
    finally:
        server.should_exit = True
    assert caught.value.kind == kind
