from __future__ import annotations

import socket
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crm import CRM, ButtonConfirm, StatedConfirm  # noqa: E402

TODAY = date(2026, 10, 12)  # a Monday; the CRM's dates are counted back from it
START = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)


def story_texts() -> dict[str, str]:
    from teamos.web import story
    return story(TODAY)


class Clock:
    """A server clock for tests: starts at START and moves on a few seconds on every read."""

    def __init__(self, start: datetime = START, step: float = 5):
        self.now, self.step = start, timedelta(seconds=step)

    def __call__(self) -> datetime:
        self.now += self.step
        return self.now

    def jump(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def crm(clock: Clock) -> CRM:
    return CRM.new(TODAY, ButtonConfirm(b"k" * 32), clock=lambda: clock.now)


@pytest.fixture
def mcp_crm(clock: Clock) -> CRM:
    return CRM.new(TODAY, StatedConfirm(), clock=lambda: clock.now)


class Chat:
    """Drives an Agent the way the page does: send, then 'continue' while more is true."""

    def __init__(self, agent: Any = None, live: bool = True, broker: str = "B-1", clock: Clock | None = None):
        from teamos.agent import Agent
        from teamos.session import new_session
        self.clock = clock or Clock()
        self.agent = agent or Agent()
        self.agent.clock = self.clock
        self.live = live
        self.session: dict[str, Any] = new_session(broker, TODAY)
        self.last: dict[str, Any] = {}

    def do(self, action: dict[str, Any], allowed: bool = True) -> dict[str, Any]:
        self.last = self.agent.handle(self.session, action, want_live=self.live, visitor_allowed=allowed, today=TODAY)
        self.session = self.last["session"]
        return self.last

    def say(self, text: str, allowed: bool = True) -> dict[str, Any]:
        out = self.do({"type": "broker", "text": text}, allowed)
        guard = 0
        while out["more"] and guard < 12:
            out = self.do({"type": "continue"}, allowed)
            guard += 1
        return out

    def card(self, write_id: str | None = None) -> dict[str, Any]:
        """A read back card as the page shows it (the newest pending one by default)."""
        if write_id is None:
            return dict(self.view["pending"][-1])
        cards = [c for t in self.view["transcript"] for c in t.get("cards", [])]
        return next(c for c in cards if c["id"] == write_id)

    def confirm(self, write_id: str | None = None) -> dict[str, Any]:
        """Press Confirm on a card: the page sends the write id and the hash of the card it shows."""
        card = self.card(write_id)
        return self.do({"type": "confirm", "write_id": card["id"], "hash": card["hash"]})

    def discard(self, write_id: str | None = None) -> dict[str, Any]:
        card = self.card(write_id)
        return self.do({"type": "discard", "write_id": card["id"], "hash": card["hash"]})

    @property
    def view(self) -> dict[str, Any]:
        return self.last["view"]

    def replies(self) -> list[dict[str, Any]]:
        return [t for t in self.view["transcript"] if t["kind"] == "assistant"]

    def reply(self) -> dict[str, Any]:
        return self.replies()[-1]

    def tools(self) -> list[str]:
        return [s["tool"] for s in self.reply()["steps"]]


@pytest.fixture
def chat() -> Chat:
    return Chat()


class ScriptedModel:
    """Stands in for Claude: returns prepared turns in order. Each item is a list of blocks, a
    Turn, an exception, or a function of the messages that returns one of those."""

    mode = "live"
    name = "claude-haiku-5-5"

    def __init__(self, *turns: Any):
        self.turns = list(turns)
        self.calls: list[list[dict[str, Any]]] = []
        self.systems: list[str] = []
        self.tools: list[list[dict[str, Any]]] = []

    def respond(self, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]) -> Any:
        from teamos.models import Turn
        self.calls.append(messages)
        self.systems.append(system)
        self.tools.append(tools)
        item = self.turns.pop(0) if self.turns else [{"type": "text", "text": "Anything else?"}]
        if callable(item) and not isinstance(item, Turn):
            item = item(messages)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, Turn):
            return item
        stop = "tool_use" if any(b["type"] == "tool_use" for b in item) else "end_turn"
        return Turn(item, stop, self.name, "live", {"input_tokens": 1500, "output_tokens": 80,
                                                     "cache_read_input_tokens": 4000}, 900)


def tool(n: int, tool_name: str, /, **data: Any) -> dict[str, Any]:
    return {"type": "tool_use", "id": f"toolu_test_{n:03d}", "name": tool_name, "input": data}


def text(t: str) -> dict[str, Any]:
    return {"type": "text", "text": t}


def last_tool_results(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [b for b in messages[-1]["content"] if b.get("type") == "tool_result"]


NOTE = {"op": "create_note", "contact_id": "C-5", "deal_id": "D-3", "property_id": "P-5",
        "summary": "Tour of 310 Canal Street with Marcus Bell", "discussed": ["Liked the loading dock"],
        "stated_time_text": "yesterday afternoon"}
TASK = {"op": "create_task", "title": "Follow up with Marcus", "contact_id": "C-5", "deal_id": "D-3",
        "due_text": "Friday, October 23, 2026"}


# ------------------------------------------------------------------ a real server in a thread
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def serve(app: Any, port: int) -> Any:
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    return server


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
