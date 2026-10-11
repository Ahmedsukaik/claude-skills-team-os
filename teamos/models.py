"""Who writes the assistant's turns: Claude (live), or a fixed set of rules (guided).

Both return the same thing: one assistant message in the Claude API's shape (text and tool_use
blocks). The rest of the system cannot tell them apart, so the guided rules also stand in for
Claude in the tests, and take over when the live model is not configured, out of budget or down.

Claude picks skills itself, from their descriptions. The guided rules pick them with simple
keyword rules (guided.py), and the page says so on every guided reply.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_MODEL = "claude-haiku-5-5"
# This build runs with thinking switched off, which Haiku 5.5 accepts at effort low to high.
# Other current models refuse thinking "disabled", and keeping thinking on would mean storing
# and replaying thinking blocks, so other models are refused at start.
SUPPORTED_MODELS = ("claude-haiku-5-5",)
# USD per million tokens, from Anthropic's pricing (October 2026), for the cost shown in the demo.
# Haiku 5.5 is priced higher above 100K input tokens; a demo chat never gets there (agent.py caps
# the size of what is sent).
PRICES = {"claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_write": 0.125, "cache_write_1h": 0.20,
                                 "cache_read": 0.01}}
EFFORTS = ("low", "medium", "high")


@dataclass
class Turn:
    content: list[dict[str, Any]]
    stop_reason: str
    model: str
    mode: str                      # "live" or "guided"
    usage: dict[str, int] = field(default_factory=dict)
    ms: int = 0


class ModelUnavailable(Exception):
    """The live model cannot answer now. kind: budget, rate_limited, auth, error (the service),
    invalid (this one request was refused)."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind, self.detail = kind, detail


class Model(Protocol):
    mode: str
    name: str

    def respond(self, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]) -> Turn: ...


def cost_usd(model: str, usage: dict[str, int]) -> float:
    price = PRICES.get(model)
    if not price:
        return 0.0
    written = usage.get("cache_creation_input_tokens", 0)
    five_min = min(usage.get("cache_write_5m_tokens", 0), written)  # the rest is priced as 1-hour writes (the dearer)
    return (usage.get("input_tokens", 0) * price["input"] + usage.get("output_tokens", 0) * price["output"]
            + five_min * price["cache_write"] + (written - five_min) * price["cache_write_1h"]
            + usage.get("cache_read_input_tokens", 0) * price["cache_read"]) / 1_000_000


class ClaudeModel:
    """One Claude API call per assistant step. Thinking off and low effort: picking a skill,
    reading the CRM and writing a read back need care, not long reasoning, and this keeps each
    step fast and cheap."""

    mode = "live"

    def __init__(self, client: Any | None = None, model: str | None = None, max_tokens: int = 1500,
                 effort: str | None = None, strict_tools: bool | None = None):
        self.name = model or os.environ.get("TEAMOS_CLAUDE_MODEL") or DEFAULT_MODEL
        if self.name not in SUPPORTED_MODELS:
            raise ValueError(f"TEAMOS_CLAUDE_MODEL must be one of {', '.join(SUPPORTED_MODELS)} (this build runs with "
                             "thinking off)")
        self.effort = (effort or os.environ.get("TEAMOS_CLAUDE_EFFORT") or "low").lower()
        if self.effort not in EFFORTS:
            raise ValueError(f"TEAMOS_CLAUDE_EFFORT must be one of {', '.join(EFFORTS)}")
        strict_env = os.environ.get("TEAMOS_STRICT_TOOLS", "on").lower() not in ("off", "0", "false", "no")
        self.strict_tools = strict_env if strict_tools is None else strict_tools
        self.max_tokens = max_tokens
        if client is None:
            import anthropic  # only needed in live mode
            # No retries: a rate limit can ask to wait longer than a serverless request may run. The page
            # drives the loop one step at a time, and a failed step falls back to the guided rules.
            client = anthropic.Anthropic(timeout=anthropic.Timeout(20.0, connect=3.0), max_retries=0)  # reads ANTHROPIC_API_KEY
        self._client = client

    def request(self, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]) -> dict[str, Any]:
        tool_defs = [dict(t) if self.strict_tools else {k: v for k, v in t.items() if k != "strict"} for t in tools]
        return {
            "model": self.name, "max_tokens": self.max_tokens,
            # The instructions, the skill list and the tools are the same for every chat: cached for an hour
            # and shared by every visitor, read at a tenth of the price.
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
            "tools": tool_defs, "messages": messages,
            "thinking": {"type": "disabled"}, "output_config": {"effort": self.effort},
            "cache_control": {"type": "ephemeral"},  # automatic caching of the growing conversation
        }

    def respond(self, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]) -> Turn:
        import anthropic
        started = time.monotonic()
        try:
            response = self._client.messages.create(**self.request(system, tools, messages))
        except anthropic.RateLimitError as e:
            raise ModelUnavailable("budget" if "enforced_spend_limit_reached" in str(_body(e)) else "rate_limited") from e
        except anthropic.BadRequestError as e:
            if "usage limits" in str(_body(e)).lower():
                raise ModelUnavailable("budget") from e
            raise ModelUnavailable("invalid", "bad request") from e
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            raise ModelUnavailable("auth") from e
        except anthropic.APIError as e:  # connection errors, timeouts, overloaded, 5xx
            raise ModelUnavailable("error", type(e).__name__) from e
        content = [_clean_block(b) for b in _get(response, "content") or []]
        usage_obj = _get(response, "usage")
        usage = {k: int(_get(usage_obj, k) or 0) for k in
                 ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")}
        usage["cache_write_5m_tokens"] = int(_get(_get(usage_obj, "cache_creation"), "ephemeral_5m_input_tokens") or 0)
        return Turn([b for b in content if b], str(_get(response, "stop_reason") or "end_turn"),
                    str(_get(response, "model") or self.name), "live", usage, int((time.monotonic() - started) * 1000))


def _get(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _body(error: Any) -> Any:
    return getattr(error, "body", None) or getattr(error, "message", "") or ""


def _clean_block(block: Any) -> dict[str, Any] | None:
    """Keep only what the session stores and replays: text and tool_use. Empty or blank text is
    dropped: the API refuses it when it is sent back."""
    kind = _get(block, "type")
    if kind == "text":
        text = str(_get(block, "text") or "")
        return {"type": "text", "text": text} if text.strip() else None
    if kind == "tool_use":
        raw = _get(block, "input")
        return {"type": "tool_use", "id": str(_get(block, "id")), "name": str(_get(block, "name")),
                "input": raw if isinstance(raw, dict) else {}}
    return None  # thinking is switched off; anything else is not needed to continue the chat
