"""One request from the page: replay the chat, apply one action, call the model once if needed.

The browser drives the tool loop: when a step ends with tool calls, the response says
`more: true` and the page asks for the next step. Each request is short (one model call at
most), the page can show each tool call as it happens, and no request holds a server open.
"""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from crm import CRMError, iso

from .guided import GuidedModel
from .models import Model, ModelUnavailable, Turn
from .prompts import SYSTEM_PROMPT
from .session import (
    MAX_BROKER_MESSAGES,
    MAX_EVENTS,
    MAX_STEPS,
    Replay,
    SessionError,
    apply,
    clean_broker_text,
    now_utc,
    signed,
    start,
    view,
)
from .skills import SkillLibrary
from .tools import TOOLS

# How long the live model rests after a failure, for every visitor of this server instance.
# A request the API refused as invalid ("invalid") is a problem of that one chat: no rest.
COOLDOWN = {"budget": 15 * 60, "auth": 15 * 60, "rate_limited": 30, "error": 30}
MAX_PROMPT_CHARS = 160_000  # about 40K tokens: far below Haiku 5.5's higher price above 100K
FIXED = "Fixed rules (no AI) answered instead; the CRM's rules work the same way."
NOTES = {
    "budget": "The live AI is resting for now. " + FIXED,
    "auth": "The live AI is unavailable right now. " + FIXED,
    "rate_limited": "The live AI is busy. " + FIXED,
    "error": "The live AI didn't answer in time. " + FIXED,
    "invalid": "The live AI couldn't take this step. " + FIXED,
    "empty": "The live AI sent an empty reply. " + FIXED,
    "visitor_limit": "You've sent a lot of messages, so fixed rules answer for now. The CRM's rules work the same way.",
    "too_long": "This chat is long for the live demo, so fixed rules answer from here. Start a new chat for the live AI.",
    "busy": "The live demo is very busy, so fixed rules are answering. The CRM's rules work the same way.",
}
CONFIRM_ERRORS = {
    "expired": "This read back expired: they last 30 minutes. Ask again for a fresh one.",
    "already_used": "This one is already saved.",
    "discarded": "This one was discarded, so it can't be saved. Ask again if you still want it.",
    "stale": "The CRM changed since this read back, so it was not saved. Ask again for a fresh one.",
    "not_pending": "This one is not waiting for a confirm.",
    "unknown_write": "There is nothing to confirm with that id.",
    "nothing_pending": "Nothing is waiting for a confirm to test with.",
}


class ActionError(Exception):
    """The action is not possible now (for example confirming twice). Shown to the visitor."""


@dataclass
class Agent:
    live: Model | None = None
    guided: Model = field(default_factory=GuidedModel)
    skills: SkillLibrary | None = None
    clock: Callable[[], datetime] = now_utc
    _down_until: float = 0.0
    _down_kind: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def live_available(self) -> bool:
        return self.live is not None and time.monotonic() >= self._down_until

    def handle(self, session: Any, action: Any, want_live: bool = True, visitor_allowed: bool = True,
               today: date | None = None, limit_note: str = "visitor_limit") -> dict[str, Any]:
        replay = start(session, self.skills, today)
        events = list(session["events"])
        kind = action.get("type") if isinstance(action, dict) else None
        at = iso(max(self.clock(), replay.now))  # the server's clock; never before the last event
        call_model = False
        if kind in ("broker", "confirm", "discard", "test") and len(events) > MAX_EVENTS - MAX_STEPS - 3:
            raise ActionError("This demo chat is as long as it can get. Start a new chat to keep trying.")
        if kind == "broker":
            if replay.broker_messages >= MAX_BROKER_MESSAGES:
                raise ActionError(f"This demo chat has reached its limit of {MAX_BROKER_MESSAGES} messages. "
                                  "Start a new chat to keep trying.")
            if replay.awaiting:
                raise ActionError("One moment: the assistant is still working on your last message.")
            try:
                event = {"type": "broker", "text": clean_broker_text(action.get("text")), "at": at}  # stored clean
                apply(replay, event)
            except SessionError as e:  # a bad new message is refused; the chat itself stays
                raise ActionError("That message can't be sent. Write it again in plain words, in under 1,500 "
                                  "characters.") from e
            events.append(event)
            call_model = True
        elif kind == "continue":
            if not replay.awaiting:
                raise ActionError("There is no reply in progress.")
            call_model = True
        elif kind == "view":  # the page reloaded: just show the chat again
            pass
        elif kind in ("confirm", "discard", "test"):
            if replay.awaiting:
                raise ActionError("One moment: the assistant is still working.")
            event = {"type": kind, "at": at}
            if kind == "test":
                event["test"] = "commit_without_confirm"
            else:
                event["write_id"] = str(action.get("write_id") or "")[:12]
            try:
                apply(replay, event, strict=True)
            except CRMError as e:
                raise ActionError(CONFIRM_ERRORS.get(e.code, e.message)) from e
            except SessionError as e:
                raise ActionError("There is nothing to confirm with that id.") from e
            events.append(event)
        else:
            raise ActionError("Unknown action.")
        if call_model:
            events.append(self._step(replay, want_live, visitor_allowed, limit_note, at))
        out = signed({"v": 1, "started": session["started"], "broker": session["broker"], "events": events})
        return {"session": out, "view": view(replay), "more": replay.awaiting}

    def _step(self, replay: Replay, want_live: bool, visitor_allowed: bool, limit_note: str, at: str) -> dict[str, Any]:
        messages = replay.next_messages()
        note = None
        turn: Turn | None = None
        if want_live and self.live is not None:
            if not visitor_allowed:
                note = NOTES.get(limit_note, NOTES["visitor_limit"])
            elif len(json.dumps(messages)) > MAX_PROMPT_CHARS:
                note = NOTES["too_long"]
            elif not self.live_available():
                note = NOTES.get(self._down_kind, NOTES["error"])
            else:
                try:
                    turn = self.live.respond(SYSTEM_PROMPT, TOOLS, messages)
                except ModelUnavailable as e:
                    if e.kind in COOLDOWN:
                        with self._lock:
                            self._down_until = time.monotonic() + COOLDOWN[e.kind]
                            self._down_kind = e.kind
                    note = NOTES.get(e.kind, NOTES["error"])
                if turn is not None and not turn.content and turn.stop_reason not in ("refusal", "max_tokens",
                                                                                       "model_context_window_exceeded"):
                    turn, note = None, NOTES["empty"]
        if turn is None:
            turn = self.guided.respond(SYSTEM_PROMPT, TOOLS, messages)
        event: dict[str, Any] = {"type": "assistant", "content": turn.content, "stop_reason": turn.stop_reason,
                                 "model": turn.model, "mode": turn.mode, "usage": turn.usage, "ms": turn.ms, "at": at}
        if note and not _already_noted(replay, note):
            event["note"] = note
        try:
            apply(replay, event)
        except SessionError:
            # The model produced something the session refuses (too many tool calls, an odd block). Answer
            # this step with the guided rules instead, and say so.
            event = {"type": "assistant", "content": self.guided.respond(SYSTEM_PROMPT, TOOLS, messages).content,
                     "stop_reason": "end_turn", "model": "guided", "mode": "guided", "usage": {}, "ms": 0, "at": at}
            if not _already_noted(replay, NOTES["invalid"]):
                event["note"] = NOTES["invalid"]
            apply(replay, event)
        return event


def _already_noted(replay: Replay, note: str) -> bool:
    return any(item.get("kind") == "system" and item.get("text") == note for item in replay.transcript[-6:])
