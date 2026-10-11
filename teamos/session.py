"""A demo chat is a list of events, kept by the browser. Every request replays them.

    broker     {"type": "broker", "text": "...", "at": "2026-10-11T14:02:11Z"}
    assistant  {"type": "assistant", "content": [text / tool_use blocks], "stop_reason", "model", "mode",
                "usage", "ms", "at"}
    confirm    {"type": "confirm", "write_id": "W-1", "at": ...}    the broker pressed Confirm
    discard    {"type": "discard", "write_id": "W-1", "at": ...}    the broker pressed Discard
    test       {"type": "test", "test": "commit_without_confirm", "at": ...}

The server signs the event list (an HMAC with a secret only the server knows) and refuses a chat
whose signature does not match, so the browser cannot add or edit events. Even so, tool results
are never stored: on replay every tool call runs again, through the same rules, against a fresh
copy of the CRM.

Every event carries the server's time when it happened ("at"). On replay the CRM's clock is set
to that time, so `recorded_at` is the system time of the moment the broker confirmed, not of the
replay. Nothing is kept on the server between requests.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from crm import CRM, ButtonConfirm, CRMError, iso
from crm import data as crm_data
from crm.timestamps import nice

from .models import cost_usd
from .prompts import SESSION_TAG, UPDATE_TAG
from .skills import SkillLibrary, default_library
from .tools import HOUSE_RULES, TOOL_NAMES, ToolContext, run_tool

log = logging.getLogger("teamos.session")
MAX_EVENTS = 220
MAX_BROKER_MESSAGES = 25
MAX_TEXT = 1500            # a voice note can be long
MAX_STEPS = 10             # model calls per broker message
MAX_TOOL_CALLS = 8         # tool calls in one model step
MAX_BLOCKS = 40
MAX_REPLY_TEXT = 8000
MAX_TOOL_INPUT = 8000
TOOL_ID = re.compile(r"toolu_[A-Za-z0-9_]{1,60}")
SYSTEM_TAG = re.compile(r"</?\s*(?:" + SESSION_TAG + "|" + UPDATE_TAG + r")\b[^>]*>?", re.I)
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏⁠-⁤﻿\ud800-\udfff]")
SIG = re.compile(r"[0-9a-f]{64}")
AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
WRITE_ID = re.compile(r"W-\d{1,4}")
CUT_OFF = ("refusal", "max_tokens", "model_context_window_exceeded")
TOO_MANY_STEPS = "I took too many steps on this one and stopped. Nothing was saved. Try asking again in one short message."
CUT_OFF_REPLY = "I couldn't finish that reply. Nothing was saved. Try asking again in other words."
TEST_ACTOR = "Test (acting as the assistant)"


class SessionError(Exception):
    """The session cannot be continued (edited, too long, or broken). The page starts a new chat."""


# ---------------------------------------------------------------------------- signing
def _secret() -> bytes:
    configured = os.environ.get("TEAMOS_SESSION_SECRET", "")
    if len(configured) >= 32:
        return configured.encode()
    if os.environ.get("VERCEL"):  # several instances: a random secret per instance would end chats at random
        raise RuntimeError("Set TEAMOS_SESSION_SECRET (32 characters or more) for this deployment.")
    log.warning("TEAMOS_SESSION_SECRET is not set (or shorter than 32 characters): using a random secret for this "
                "process, so chats end when it restarts. Set it when running more than one instance.")
    return secrets.token_bytes(32)


_SECRET = _secret()
CONFIRM_SECRET = hmac.new(_SECRET, b"confirm-button", hashlib.sha256).digest()  # separate from the signing key


def signature(session: dict[str, Any]) -> str:
    body = json.dumps({k: session.get(k) for k in ("v", "started", "broker", "events")},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hmac.new(_SECRET, body.encode(), hashlib.sha256).hexdigest()


def signed(session: dict[str, Any]) -> dict[str, Any]:
    out = {"v": session["v"], "started": session["started"], "broker": session["broker"], "events": session["events"]}
    out["sig"] = signature(out)
    return out


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def new_session(broker_id: str = "B-1", today: date | None = None) -> dict[str, Any]:
    if broker_id not in {b["id"] for b in crm_data.BROKERS}:
        broker_id = "B-1"
    return signed({"v": 1, "started": (today or date.today()).isoformat(), "broker": broker_id, "events": []})


# ---------------------------------------------------------------------------- replay
@dataclass
class Replay:
    crm: CRM
    confirm: ButtonConfirm
    broker: dict[str, str]
    ctx: ToolContext
    now: datetime
    clock: dict[str, datetime] = field(default_factory=dict)       # the CRM's clock reads from here
    messages: list[dict[str, Any]] = field(default_factory=list)   # finished user/assistant messages
    pending: list[dict[str, Any]] = field(default_factory=list)    # content of the next user message
    transcript: list[dict[str, Any]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)      # tool calls since the last reply
    turn_skills: list[str] = field(default_factory=list)            # skills loaded since the broker's message
    turn_writes: list[str] = field(default_factory=list)            # writes proposed since the broker's message
    turn_cost: float = 0.0
    tool_ids: set[str] = field(default_factory=set)
    steps_since_broker: int = 0
    broker_messages: int = 0
    awaiting: bool = False   # the last assistant step called tools: the model must be called again
    stats: dict[str, Any] = field(default_factory=lambda: {
        "live_calls": 0, "guided_calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0, "cost_usd": 0.0, "ms": [], "tool_calls": 0, "replies": 0, "refused_saves": 0})

    @classmethod
    def new(cls, started: date, broker_id: str, skills: SkillLibrary | None = None) -> Replay:
        broker = crm_data.broker(broker_id)
        holder: dict[str, datetime] = {"now": datetime.combine(started, time(12, 0), tzinfo=timezone.utc)}
        confirm = ButtonConfirm(CONFIRM_SECRET)
        crm = CRM.new(started, confirm, user=broker["name"], clock=lambda: holder["now"])
        ctx = ToolContext(crm, skills or default_library(), actor=f"Claude for {broker['name']}")
        return cls(crm, confirm, broker, ctx, holder["now"], holder)

    def set_now(self, moment: datetime) -> None:
        self.now = moment
        self.clock["now"] = moment

    def next_messages(self) -> list[dict[str, Any]]:
        if not self.pending:
            raise SessionError("nothing to answer")
        return self.messages + [{"role": "user", "content": list(self.pending)}]

    def skills_used(self) -> list[str]:
        out: list[str] = []
        for item in self.transcript:
            for s in item.get("skills", []):
                if s not in out:
                    out.append(s)
        return out


def start(session: Any, skills: SkillLibrary | None = None, today: date | None = None, verify: bool = True) -> Replay:
    """Check the session's envelope and signature, and replay its events. `verify=False` is for
    tests of the replay rules themselves."""
    if not isinstance(session, dict) or session.get("v") != 1 or not isinstance(session.get("events"), list):
        raise SessionError("not a demo session")
    if verify:
        sig = session.get("sig")
        try:
            valid = isinstance(sig, str) and SIG.fullmatch(sig) is not None and \
                hmac.compare_digest(sig.encode(), signature(session).encode())
        except ValueError:  # NaN or another value JSON cannot carry
            valid = False
        if not valid:
            raise SessionError("the chat was changed outside this server")
    try:
        started = date.fromisoformat(str(session.get("started")))
    except ValueError as e:
        raise SessionError("bad start date") from e
    today = today or date.today()
    if not today - timedelta(days=30) <= started <= today + timedelta(days=1):
        raise SessionError("this chat is too old")
    if session.get("broker") not in {b["id"] for b in crm_data.BROKERS}:
        raise SessionError("unknown broker")
    if len(session["events"]) > MAX_EVENTS:
        raise SessionError("this chat is too long")
    replay = Replay.new(started, session["broker"], skills)
    for event in session["events"]:
        apply(replay, event)
    return replay


def _event_time(r: Replay, event: dict[str, Any]) -> datetime:
    at = event.get("at")
    if not isinstance(at, str) or not AT.fullmatch(at):
        raise SessionError("bad event time")
    moment = datetime.fromisoformat(at.replace("Z", "+00:00"))
    started = r.crm.today
    if moment < r.now - timedelta(seconds=1) and r.transcript:
        raise SessionError("events out of order")
    if not started - timedelta(days=1) <= moment.date() <= started + timedelta(days=32):
        raise SessionError("event time outside the chat")
    return moment


def apply(r: Replay, event: Any, strict: bool = False) -> None:
    """Apply one event. `strict` (a new broker action) raises CRMError instead of skipping it."""
    if not isinstance(event, dict):
        raise SessionError("bad event")
    r.set_now(_event_time(r, event))
    kind = event.get("type")
    if kind == "broker":
        _broker(r, event)
    elif kind == "assistant":
        _assistant(r, event)
    elif kind in ("confirm", "discard"):
        _decide(r, kind, event, strict)
    elif kind == "test":
        _test(r, event, strict)
    else:
        raise SessionError("unknown event")


def strip_tags(text: str) -> str:
    """Remove control and invisible characters, then the tags only the system may use, until
    none is left: "<crm_<crm_update>update>" must not turn into a tag after one pass."""
    text = CONTROL.sub("", text)
    previous = None
    while previous != text:
        previous, text = text, SYSTEM_TAG.sub("", text)
    return text.strip()


def clean_broker_text(text: Any) -> str:
    if not isinstance(text, str):
        raise SessionError("bad message")
    text = strip_tags(text).replace("<", "‹").replace(">", "›")  # nothing tag-like reaches the model
    if not text or len(text) > MAX_TEXT:
        raise SessionError("message is empty or too long")
    return text


def _broker(r: Replay, event: dict[str, Any]) -> None:
    text = clean_broker_text(event.get("text"))
    r.broker_messages += 1
    if r.broker_messages > MAX_BROKER_MESSAGES:
        raise SessionError("this chat has reached its message limit")
    if not r.messages and not any(b.get("type") == "text" and SESSION_TAG in b["text"] for b in r.pending):
        r.pending.insert(0, {"type": "text", "text": f"<{SESSION_TAG}>Signed in: {r.broker['name']} (broker at "
                                                    f"{crm_data.FIRM_LINE}).</{SESSION_TAG}>"})
    r.pending.append({"type": "text", "text": text})
    r.ctx.broker_words.append(text)
    r.transcript.append({"kind": "broker", "text": text, "at": iso(r.now)})
    r.steps_since_broker, r.awaiting = 0, False
    r.turn_skills, r.turn_writes = [], []


def _validate_blocks(r: Replay, content: Any, allow_empty: bool) -> list[dict[str, Any]]:
    if not isinstance(content, list) or len(content) > MAX_BLOCKS:
        raise SessionError("bad assistant turn")
    out: list[dict[str, Any]] = []
    ids: set[str] = set()
    text_size = 0
    for b in content:
        if not isinstance(b, dict):
            raise SessionError("bad block")
        if b.get("type") == "text":
            text = b.get("text")
            if not isinstance(text, str):
                raise SessionError("bad text block")
            if not text.strip():
                continue  # the API refuses blank text when it is sent back
            text_size += len(text)
            out.append({"type": "text", "text": text})
        elif b.get("type") == "tool_use":
            tid, name, data = b.get("id"), b.get("name"), b.get("input")
            if not isinstance(tid, str) or not TOOL_ID.fullmatch(tid) or tid in r.tool_ids or tid in ids:
                raise SessionError("bad tool id")
            if name not in TOOL_NAMES or not isinstance(data, dict) or len(json.dumps(data)) > MAX_TOOL_INPUT:
                raise SessionError("bad tool call")
            ids.add(tid)
            out.append({"type": "tool_use", "id": tid, "name": name, "input": data})
        else:
            raise SessionError("bad block type")
    if text_size > MAX_REPLY_TEXT or len(ids) > MAX_TOOL_CALLS or (not out and not allow_empty):
        raise SessionError("bad assistant turn")
    r.tool_ids |= ids
    return out


def _assistant(r: Replay, event: dict[str, Any]) -> None:
    if not r.pending:
        raise SessionError("assistant turn without anything to answer")
    if r.steps_since_broker >= MAX_STEPS:
        raise SessionError("too many steps")
    stop = str(event.get("stop_reason") or "end_turn")
    cut_off = stop in CUT_OFF
    blocks = _validate_blocks(r, event.get("content"), allow_empty=cut_off)
    if cut_off:  # a refusal or a cut off reply: nothing in it is used, tool calls included
        blocks = [b for b in blocks if b["type"] == "text"]
    r.steps_since_broker += 1
    r.messages.append({"role": "user", "content": r.pending})
    r.pending = []
    r.messages.append({"role": "assistant", "content": blocks or [{"type": "text", "text": CUT_OFF_REPLY}]})
    mode = "live" if event.get("mode") == "live" else "guided"
    model = str(event.get("model") or mode)[:60]
    raw_usage = event.get("usage")
    usage = {str(k): int(v) for k, v in raw_usage.items()
             if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 10_000_000} if isinstance(raw_usage, dict) else {}
    _count(r, mode, model, usage, event.get("ms"))
    if isinstance(event.get("note"), str):
        r.transcript.append({"kind": "system", "text": event["note"][:300]})
    calls = [b for b in blocks if b["type"] == "tool_use"]
    if calls:
        for call in calls:
            result = run_tool(r.ctx, call["name"], call["input"])
            r.pending.append({"type": "tool_result", "tool_use_id": call["id"], "content": result.content,
                              **({"is_error": True} if result.is_error else {})})
            if result.skill and result.skill not in r.turn_skills:
                r.turn_skills.append(result.skill)
            if result.write_id:
                r.turn_writes.append(result.write_id)
            r.steps.append({"tool": call["name"], "label": result.label, "ok": not result.is_error,
                            "outcome": result.outcome})
            r.stats["tool_calls"] += 1
        r.awaiting = True
        if r.steps_since_broker >= MAX_STEPS:
            r.messages += [{"role": "user", "content": r.pending},
                           {"role": "assistant", "content": [{"type": "text", "text": TOO_MANY_STEPS}]}]
            r.pending, r.awaiting = [], False
            _reply(r, TOO_MANY_STEPS, mode, model, problem="needed more than ten steps for one message")
        return
    text = "".join(b["text"] for b in blocks if b["type"] == "text").strip()
    if cut_off or not text:
        _reply(r, CUT_OFF_REPLY, mode, model, problem="the model declined" if stop == "refusal" else "the reply was cut off")
    else:
        _reply(r, text, mode, model)
    r.awaiting = False


def _count(r: Replay, mode: str, model: str, usage: dict[str, int], ms: Any) -> None:
    s = r.stats
    s["live_calls" if mode == "live" else "guided_calls"] += 1
    for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        s[k] += usage.get(k, 0)
    cost = cost_usd(model, usage) if mode == "live" else 0.0
    s["cost_usd"] += cost
    r.turn_cost += cost
    if isinstance(ms, int) and 0 <= ms < 600_000 and mode == "live":
        s["ms"].append(ms)


def _reply(r: Replay, text: str, mode: str, model: str, problem: str | None = None) -> None:
    # A reply that used the CRM without loading a skill this turn works under skills loaded earlier in the chat.
    earlier = [] if r.turn_skills or not r.steps else sorted(r.ctx.loaded, key=lambda s: (s == HOUSE_RULES, s))
    r.transcript.append({"kind": "assistant", "text": text, "steps": r.steps, "mode": mode, "model": model,
                         "skills": list(r.turn_skills), "skills_earlier": earlier, "writes": list(r.turn_writes),
                         "problem": problem, "cost_usd": round(r.turn_cost, 6), "at": iso(r.now)})
    r.steps, r.turn_cost = [], 0.0
    r.turn_writes = []
    r.stats["replies"] += 1


def _decide(r: Replay, kind: str, event: dict[str, Any], strict: bool) -> None:
    write_id = event.get("write_id")
    if not isinstance(write_id, str) or not WRITE_ID.fullmatch(write_id):
        raise SessionError("bad write id")
    who = r.broker["name"]
    try:
        if kind == "confirm":
            write = r.crm.writes.get(write_id)
            token = r.confirm.mint(write_id, write["hash"]) if write else None  # minted here, only for the button
            result = r.crm.commit_write(who, write_id, write["hash"] if write else None, token)
            counts = _count_saved(result["saved"])
            r.transcript.append({"kind": "notice", "notice": "saved", "write_id": write_id, "at": iso(r.now),
                                 "text": f"Saved to the CRM by {who}: {counts}."})
            ids = ", ".join(f"{s['id']} ({s['kind']})" for s in result["saved"])
            update = f"The broker pressed Confirm. {write_id} was saved: {ids}, recorded at {result['recorded_at']}."
        else:
            r.crm.discard_write(who, write_id)
            r.transcript.append({"kind": "notice", "notice": "discarded", "write_id": write_id, "at": iso(r.now),
                                 "text": "Discarded. Nothing was saved."})
            update = f"The broker pressed Discard. {write_id} was not saved."
    except CRMError:
        if strict:
            raise
        return  # refused at the time too; the CRM's log has it
    r.pending.append({"type": "text", "text": f"<{UPDATE_TAG}>{update}</{UPDATE_TAG}>"})


def _count_saved(saved: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for s in saved:
        counts[s["kind"]] = counts.get(s["kind"], 0) + 1
    return ", ".join(f"{n} {k}{'' if n == 1 else 's'}" for k, n in counts.items())


def latest_pending(r: Replay) -> dict[str, Any] | None:
    return next((w for w in reversed(r.crm.writes.values()) if w["status"] == "pending" and not r.crm.is_expired(w)), None)


def _test(r: Replay, event: dict[str, Any], strict: bool) -> None:
    """The story's test: the assistant tries to save the newest pending write without the broker's
    Confirm, through exactly the tool path the model uses. The CRM refuses it."""
    if event.get("test") != "commit_without_confirm":
        raise SessionError("unknown test")
    write = latest_pending(r)
    if write is None:
        if strict:
            raise CRMError("nothing_pending", "There is no write waiting for a confirm to test with.")
        return
    tester = ToolContext(r.crm, r.ctx.skills, actor=TEST_ACTOR, loaded=set(r.ctx.loaded))
    result = run_tool(tester, "commit_write", {"write_id": write["id"], "payload_hash": write["hash"]})
    message = json.loads(result.content).get("message", "").split(" Tell the broker")[0]  # the rest is for the model
    r.stats["refused_saves"] += int(result.is_error)
    r.transcript.append({"kind": "test", "write_id": write["id"], "refused": result.is_error, "at": iso(r.now),
                         "text": "Test: the assistant tried to save the note without your Confirm.",
                         "result": message if result.is_error else "It was saved."})


# ---------------------------------------------------------------------------- what the page shows
def write_card(r: Replay, write: dict[str, Any]) -> dict[str, Any]:
    status = "expired" if r.crm.is_expired(write) else write["status"]
    return {"id": write["id"], "status": status, "summary": write["summary"], "items": r.crm.readback(write),
            "changes": write["changes"],
            "flags": write["flags"], "proposed_at": write["proposed_at"], "expires_at": write["expires_at"],
            "committed_at": write.get("committed_at"), "hash": write["hash"],
            "saved": (write.get("result") or {}).get("saved", [])}


def _saved_records(r: Replay) -> list[dict[str, Any]]:
    out = []
    for write in r.crm.writes.values():
        if write["status"] != "committed":
            continue
        for s in write["result"]["saved"]:
            rec = r.crm.record(s["id"]) or {}
            item: dict[str, Any] = {"id": s["id"], "kind": s["kind"], "title": s["label"], "write_id": write["id"],
                                    "recorded_at": write["committed_at"], "logged_by": rec.get("logged_by", r.broker["name"])}
            if s["kind"] == "note":
                item.update(contact=r.crm.label(rec.get("contact_id")), discussed=rec.get("discussed", []),
                            time={"label": "When it happened", "text": rec.get("stated_time_text"),
                                  "nice": nice(rec.get("stated_time")), "note": rec.get("stated_time_note")})
            elif s["kind"] == "task":
                item.update(contact=r.crm.label(rec.get("contact_id")),
                            time={"label": "Due", "text": rec.get("due_text"), "nice": nice(rec.get("due")),
                                  "note": rec.get("due_note")})
            out.append(item)
    return out


def view(r: Replay) -> dict[str, Any]:
    transcript = []
    for item in r.transcript:
        if item["kind"] == "assistant" and item["writes"]:
            item = {**item, "cards": [write_card(r, r.crm.writes[w]) for w in item["writes"] if w in r.crm.writes]}
        transcript.append(item)
    if r.awaiting:
        transcript.append({"kind": "working", "steps": r.steps, "skills": list(r.turn_skills)})
    s = r.stats
    ms = s["ms"]
    writes = list(r.crm.writes.values())
    deals = [{"id": d["id"], "name": d["name"], "stage": d["stage"], "owner": d["owner"],
              "contact": r.crm.contacts[d["contact_id"]]["name"], "last_activity": d["last_activity"]}
             for d in r.crm.deals.values()]
    return {
        "transcript": transcript, "awaiting": r.awaiting, "broker": r.broker, "now": iso(r.now),
        "pending": [write_card(r, w) for w in writes if w["status"] == "pending" and not r.crm.is_expired(w)],
        "saved": _saved_records(r),
        "drafts": [dict(d) for d in r.crm.drafts.values()],
        "log": r.crm.log[-120:], "deals": deals, "skills_used": r.skills_used(),
        "metrics": {"broker_messages": r.broker_messages, "replies": s["replies"], "tool_calls": s["tool_calls"],
                    "live_calls": s["live_calls"], "guided_calls": s["guided_calls"],
                    "input_tokens": s["input_tokens"] + s["cache_read_input_tokens"] + s["cache_creation_input_tokens"],
                    "cached_tokens": s["cache_read_input_tokens"], "output_tokens": s["output_tokens"],
                    "cost_usd": round(s["cost_usd"], 5), "avg_ms": int(sum(ms) / len(ms)) if ms else None,
                    "writes_proposed": len(writes), "writes_saved": sum(w["status"] == "committed" for w in writes),
                    "saves_refused": sum(1 for e in r.crm.log if e["action"] == "save" and e["outcome"] != "ok")},
    }
