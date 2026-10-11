"""The web demo's HTTP API, as the page uses it: the story over HTTP, limits, and bad requests."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from conftest import ScriptedModel, text
from fastapi.testclient import TestClient

from teamos.agent import Agent
from teamos.web import MAX_BODY, PER_VISITOR, Limiter, create_app, follow_up_day, live_model_from_env, story


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Agent()))


def send(client: TestClient, session: dict[str, Any], action: dict[str, Any], **extra: Any) -> dict[str, Any]:
    res = client.post("/api/step", json={"session": session, "action": action, **extra})
    assert res.status_code == 200, res.text
    return res.json()


def say(client: TestClient, session: dict[str, Any], message: str, **extra: Any) -> dict[str, Any]:
    out = send(client, session, {"type": "broker", "text": message}, **extra)
    while out["more"]:
        out = send(client, out["session"], {"type": "continue"}, **extra)
    return out


def test_config_lists_the_skills_the_story_and_whether_live_ai_is_on(client):
    cfg = client.get("/api/config").json()
    assert cfg["live"] is False and cfg["model"] is None and cfg["firm"] == "Marrowby Commercial"
    assert [s["name"] for s in cfg["skills"]] == ["crm-update", "follow-up-email", "house-rules", "meeting-prep",
                                                  "voice-note-debrief", "weekly-pipeline"]
    assert set(cfg["story"]) == {"voice_note", "gate", "ambiguity", "off_topic"}
    assert {c.get("kind") for c in cfg["chips"]} >= {"near_miss", "test"} and len(cfg["brokers"]) == 4


def test_the_story_date_is_always_an_exact_friday_ahead():
    from datetime import date
    for d in (date(2026, 10, 12), date(2026, 12, 31), date(2027, 2, 26)):
        day = follow_up_day(d)
        assert day.weekday() == 4 and 7 <= (day - d).days <= 13
        assert f"{day:%A}, {day:%B} {day.day}, {day.year}" in story(d)["voice_note"]


def test_the_whole_story_over_http(client):
    s = story(__import__("datetime").date.today())
    out = say(client, client.post("/api/new").json()["session"], s["voice_note"])
    write = out["view"]["pending"][0]
    out = send(client, out["session"], {"type": "confirm", "write_id": write["id"]})
    assert out["view"]["metrics"]["writes_saved"] == 1 and out["view"]["transcript"][-1]["notice"] == "saved"
    out = say(client, out["session"], s["gate"])
    out = send(client, out["session"], {"type": "test", "test": "commit_without_confirm"})
    assert out["view"]["transcript"][-1]["refused"] is True and out["view"]["metrics"]["writes_saved"] == 1
    out = say(client, out["session"], s["ambiguity"])
    assert "Which one did you mean?" in out["view"]["transcript"][-1]["text"]
    out = say(client, out["session"], s["off_topic"])
    assert out["view"]["transcript"][-1]["skills"] == []


def test_a_new_chat_can_be_signed_in_as_another_broker(client):
    out = client.post("/api/new", json={"broker": "B-3"}).json()
    assert out["session"]["broker"] == "B-3" and out["view"]["broker"]["name"] == "Jordan Avery"
    assert client.post("/api/new", json={"broker": "B-99"}).json()["session"]["broker"] == "B-1"


def test_the_page_can_reload_and_show_the_same_chat(client):
    out = say(client, client.post("/api/new").json()["session"], "Give me the weekly pipeline summary.")
    again = send(client, out["session"], {"type": "view"})
    assert again["view"]["transcript"] == out["view"]["transcript"] and again["session"] == out["session"]


def test_a_broken_session_asks_the_page_to_start_again(client):
    res = client.post("/api/step", json={"session": {"v": 1, "started": "2026-10-12", "broker": "B-1",
                                                     "events": [{"type": "robot"}]}, "action": {"type": "view"}})
    assert res.status_code == 409 and res.json()["error"] == "session"


@pytest.mark.parametrize("action, message", [
    ({"type": "confirm", "write_id": "W-1"}, "nothing to confirm"),
    ({"type": "discard", "write_id": "W-1"}, "not waiting"),
    ({"type": "test", "test": "commit_without_confirm"}, "Nothing is waiting"),
    ({"type": "continue"}, "no reply in progress"),
    ({"type": "broker", "text": "x" * 1501}, "can't be sent"),
])
def test_impossible_actions_are_explained(client, action, message):
    session = client.post("/api/new").json()["session"]
    res = client.post("/api/step", json={"session": session, "action": action})
    assert res.status_code == 409 and res.json()["error"] == "action" and message in res.json()["message"]


@pytest.mark.parametrize("raw", [b"not json", b"[1, 2]", b'{"a": NaN}', b"x" * (MAX_BODY + 1)],
                         ids=["not json", "a list", "NaN", "too big"])
def test_bad_bodies_are_refused(client, raw):
    res = client.post("/api/step", content=raw, headers={"Content-Type": "application/json"})
    assert res.status_code == 409 and res.json()["error"] == "action"


def test_deeply_nested_json_is_refused_cleanly(client):
    deep = b"[" * 5000 + b"]" * 5000
    res = client.post("/api/step", content=b'{"session": ' + deep + b"}", headers={"Content-Type": "application/json"})
    assert res.status_code == 409
    nested: dict = {}
    cursor = nested
    for _ in range(30):
        cursor["a"] = {}
        cursor = cursor["a"]
    assert client.post("/api/step", json={"session": nested, "action": {"type": "view"}}).status_code == 409


def test_a_visitor_over_the_live_limit_is_moved_to_the_fixed_rules(monkeypatch):
    monkeypatch.setattr("teamos.web.PER_VISITOR", (1, 600))
    live = ScriptedModel([text("Hi from Claude.")], [text("Hi again from Claude.")])
    client = TestClient(create_app(Agent(live=live)))
    first = say(client, client.post("/api/new").json()["session"], "Hello", live=True)
    assert first["view"]["transcript"][-1]["mode"] == "live"
    second = say(client, first["session"], "Give me the weekly pipeline summary.", live=True)
    assert second["view"]["transcript"][-1]["mode"] == "guided" and len(live.calls) == 1


def test_the_page_can_ask_for_the_fixed_rules(client):
    live = ScriptedModel([text("Hi from Claude.")])
    client = TestClient(create_app(Agent(live=live)))
    out = say(client, client.post("/api/new").json()["session"], "Hello", live=False)
    assert out["view"]["transcript"][-1]["mode"] == "guided" and not live.calls


def test_every_kind_of_request_is_counted_per_visitor(monkeypatch):
    monkeypatch.setattr("teamos.web.PER_VISITOR_REQUESTS", (3, 600))
    client = TestClient(create_app(Agent()))
    session = client.post("/api/new").json()["session"]
    codes = [client.post("/api/step", json={"session": session, "action": {"type": "view"}}).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 409]


def test_visitors_are_counted_separately_and_concurrency_is_capped():
    limiter = Limiter()
    assert all(limiter.allow("a", 2, 60) for _ in range(2)) and not limiter.allow("a", 2, 60)
    assert limiter.allow("b", 2, 60)
    assert limiter.enter("a") and limiter.enter("a") and not limiter.enter("a")
    limiter.leave("a")
    assert limiter.enter("a")
    assert PER_VISITOR[0] >= 40  # a story run is about 20 model calls


def test_behind_vercel_the_visitor_is_the_forwarded_client(monkeypatch):
    monkeypatch.setattr("teamos.web.PER_VISITOR_REQUESTS", (1, 600))
    client = TestClient(create_app(Agent()))
    session = client.post("/api/new").json()["session"]
    body = {"session": session, "action": {"type": "view"}}
    # Off Vercel a client cannot pick its own address with a header.
    assert client.post("/api/step", json=body, headers={"x-forwarded-for": "1.1.1.1"}).status_code == 200
    assert client.post("/api/step", json=body, headers={"x-forwarded-for": "2.2.2.2"}).status_code == 409
    monkeypatch.setenv("VERCEL", "1")
    assert client.post("/api/step", json=body, headers={"x-vercel-forwarded-for": "3.3.3.3"}).status_code == 200
    assert client.post("/api/step", json=body, headers={"x-vercel-forwarded-for": "4.4.4.4, 10.0.0.1"}).status_code == 200
    assert client.post("/api/step", json=body, headers={"x-vercel-forwarded-for": "3.3.3.3"}).status_code == 409


def test_on_vercel_a_session_secret_is_required(monkeypatch):
    import teamos.session as session_module
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("TEAMOS_SESSION_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="TEAMOS_SESSION_SECRET"):
        session_module._secret()
    monkeypatch.setenv("TEAMOS_SESSION_SECRET", "s" * 40)
    assert session_module._secret() == b"s" * 40


def test_live_ai_needs_a_key_and_can_be_switched_off(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert live_model_from_env() is None
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-local-test-not-a-real-key")
    monkeypatch.setenv("TEAMOS_LIVE_AI", "off")
    assert live_model_from_env() is None
    monkeypatch.setenv("TEAMOS_LIVE_AI", "on")
    assert live_model_from_env() is not None


def test_the_page_and_its_files_are_served_locally(client):
    page = client.get("/")
    assert page.status_code == 200 and "Claude Skills Team OS" in page.text
    for name in ("/app.js", "/style.css", "/tokens.css"):
        assert client.get(name).status_code == 200
    assert client.get("/healthz").json() == {"status": "ok"}


def test_the_vercel_entry_point_serves_the_api_only():
    import importlib.util
    spec = importlib.util.spec_from_file_location("vercel_entry", Path(__file__).resolve().parent.parent / "api" / "index.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vercel = TestClient(module.app)
    assert vercel.get("/api/config").status_code == 200 and vercel.get("/").status_code == 404


def test_the_page_has_no_contact_details_and_one_link():
    public = Path(__file__).resolve().parent.parent / "public"
    for name in ("index.html", "app.js"):
        page = (public / name).read_text(encoding="utf-8")
        emails = re.findall(r"[\w.+-]+@[a-z][\w-]*\.[a-z]{2,}", page)
        assert all(e.endswith("example.com") for e in emails), name
        assert "mailto:" not in page and "tel:" not in page and "wa.me" not in page
    links = re.findall(r'href="(https?://[^"]+)"', (public / "index.html").read_text(encoding="utf-8"))
    assert [link for link in links if "fonts.g" not in link] == ["https://github.com/Ahmedsukaik/claude-skills-team-os"]


def test_a_slow_model_call_does_not_block_other_visitors():
    import threading
    import time

    import httpx
    from conftest import free_port, serve

    class Slow:
        mode, name = "live", "claude-haiku-5-5"

        def respond(self, system, tools, messages):
            time.sleep(2.5)
            from teamos.models import Turn
            return Turn([text("Hi.")], "end_turn", self.name, "live")

    port = free_port()
    server = serve(create_app(Agent(live=Slow())), port)
    try:
        base = f"http://127.0.0.1:{port}"
        session = httpx.post(base + "/api/new").json()["session"]
        worker = threading.Thread(target=lambda: httpx.post(base + "/api/step", timeout=10, json={
            "session": session, "action": {"type": "broker", "text": "Hello"}, "live": True}))
        worker.start()
        time.sleep(0.3)
        started = time.monotonic()
        assert httpx.get(base + "/healthz").status_code == 200
        assert time.monotonic() - started < 1.2
        worker.join()
    finally:
        server.should_exit = True


def test_an_unexpected_error_is_a_clean_500():
    class Broken(Agent):
        def handle(self, *args, **kwargs):
            raise RuntimeError("boom")

    client = TestClient(create_app(Broken()), raise_server_exceptions=False)
    res = client.post("/api/step", json={"session": {}, "action": {"type": "view"}})
    assert res.status_code == 500 and res.json()["error"] == "server" and "boom" not in res.text
