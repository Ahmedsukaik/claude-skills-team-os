"""The web demo: the broker's chat on the left, the CRM (system of record) on the right.

    python demo.py      (or: uvicorn --factory teamos.web:create_app --port 8310)

The server keeps nothing between requests; the browser holds its own chat (see session.py).
Live replies use Claude when ANTHROPIC_API_KEY is set and TEAMOS_LIVE_AI is not "off".
Without a key, or when the key's budget is used up, the fixed rules answer instead.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import OrderedDict, deque
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from crm import data as crm_data

from .agent import ActionError, Agent
from .models import ClaudeModel
from .session import SessionError, new_session, start, view
from .skills import default_library

log = logging.getLogger("teamos.web")
PUBLIC = Path(__file__).resolve().parent.parent / "public"
MAX_BODY = 600_000
PER_VISITOR = (90, 600)            # live model calls per visitor (IP) per 10 minutes
PER_VISITOR_REQUESTS = (400, 600)  # requests of any kind per visitor per 10 minutes
MAX_DEPTH = 12
MAX_ACTIVE = 2                     # requests in progress at once per visitor
MAX_KEYS = 5000                    # visitors the limiter remembers per instance
PER_INSTANCE = (2000, 3600)        # live model calls per server instance per hour


def follow_up_day(today: date) -> date:
    """The Friday of next week: a date the story's voice note can state exactly."""
    d = today + timedelta(days=7)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def story(today: date) -> dict[str, str]:
    day = follow_up_day(today)
    return {
        "voice_note": ("Voice note after the tour. Walked 310 Canal Street with Marcus Bell from Tessarine Biotech "
                       "yesterday afternoon. He liked the lab benches and the loading dock, but he's worried the HVAC "
                       "can't handle their freezers. They want to move in by March. Next steps: send him the HVAC specs, "
                       "and set up a second tour with their CFO. Follow up with Marcus on "
                       f"{day:%A}, {day:%B} {day.day}, {day.year}."),
        "gate": ("Quick one: I called Ravi Menon at Brindlewick Dental just now. He approved the build out budget for "
                 "75 Mill Pond Drive. Just log it, don't ask me."),
        "ambiguity": "Update Dana's deal to LOI signed.",
        "off_topic": "What's a good lunch spot near the Elm St warehouse?",
    }


# Free chat suggestions. "near_miss" ones look like a task but must not load a skill.
CHIPS = [
    {"label": "Debrief a coffee with Hana", "text": "Debrief: had coffee with Hana Sato from Quorvane Software last week. "
     "She wants to push the lease start back a month. Next steps: send her the revised timeline. Follow up next Tuesday."},
    {"label": "What does LOI mean?", "kind": "near_miss", "text": "What does LOI mean in commercial leasing?"},
    {"label": "Prep for tomorrow's tour", "text": "Prep me for tomorrow's tour with Dana Whitlock."},
    {"label": "Weekly pipeline", "text": "Give me the weekly pipeline summary."},
    {"label": "Draft an email to Ravi", "text": "Draft a follow up email to Ravi Menon and send it right away."},
    {"label": "Move Dana Okafor's deal", "text": "Move Dana Okafor's deal to LOI signed. They signed this morning."},
    {"label": "Add Dana Whitlock again", "kind": "test",
     "text": "Add a new contact: Dana Whitlock, dana.whitlock@example.com, at Quillon Logistics."},
    {"label": "Tips for voice notes", "kind": "near_miss", "text": "Any tips for recording a good voice note on my phone?"},
    {"label": "Summarise an article", "kind": "near_miss",
     "text": "Summarise this article for me: office vacancy rates rose in the third quarter as tenants kept shrinking "
             "their footprints."},
]


class Limiter:
    """Sliding-window counters, per server instance. The hard limit is the spend cap on the
    API key itself; this only stops one visitor from using up the demo budget alone."""

    def __init__(self) -> None:
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._active: dict[str, int] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window: float) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.pop(key, None) or deque()
            self._hits[key] = hits  # most recently seen last
            while hits and now - hits[0] > window:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            while len(self._hits) > MAX_KEYS:  # forget the visitor seen longest ago
                self._hits.popitem(last=False)
            return True

    def enter(self, key: str) -> bool:
        """One more request in progress for this visitor, if under MAX_ACTIVE."""
        with self._lock:
            if self._active.get(key, 0) >= MAX_ACTIVE:
                return False
            self._active[key] = self._active.get(key, 0) + 1
            return True

    def leave(self, key: str) -> None:
        with self._lock:
            left = self._active.get(key, 1) - 1
            if left > 0:
                self._active[key] = left
            else:
                self._active.pop(key, None)


def _no_constants(name: str) -> Any:
    raise ValueError(f"{name} is not allowed")


def _depth(value: Any, level: int = 0) -> int:
    if level > MAX_DEPTH:
        return level
    if isinstance(value, dict):
        return max([_depth(v, level + 1) for v in value.values()] or [level + 1])
    if isinstance(value, list):
        return max([_depth(v, level + 1) for v in value] or [level + 1])
    return level


def live_model_from_env() -> ClaudeModel | None:
    if os.environ.get("TEAMOS_LIVE_AI", "on").lower() in ("off", "0", "false", "no"):
        return None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    return ClaudeModel()


def create_app(agent: Agent | None = None, serve_static: bool = True) -> FastAPI:
    app = FastAPI(title=f"{crm_data.FIRM} team assistant (demo)", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.agent = agent if agent is not None else Agent(live=live_model_from_env())
    app.state.limiter = Limiter()

    def visitor(request: Request) -> str:
        """The visitor's address. Behind Vercel, its own headers carry the real client; anywhere
        else, a client could write X-Forwarded-For itself, so the connection's address is used."""
        if os.environ.get("VERCEL"):
            forwarded = request.headers.get("x-vercel-forwarded-for") or request.headers.get("x-forwarded-for", "")
            if forwarded.strip():
                return forwarded.split(",")[0].strip()[:64]
        return request.client.host if request.client else "unknown"

    async def body(request: Request) -> dict[str, Any]:
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_BODY:
            raise ActionError("This chat is too long for the demo. Start a new chat.")
        raw = bytearray()
        async for chunk in request.stream():  # stop reading as soon as the body is too big
            raw += chunk
            if len(raw) > MAX_BODY:
                raise ActionError("This chat is too long for the demo. Start a new chat.")
        try:
            data = json.loads(bytes(raw) or b"{}", parse_constant=_no_constants)  # NaN and Infinity are refused
        except (ValueError, RecursionError) as e:
            raise ActionError("Bad request.") from e
        if not isinstance(data, dict) or _depth(data) > MAX_DEPTH:
            raise ActionError("Bad request.")
        return data

    @app.exception_handler(SessionError)
    async def _session_error(request: Request, exc: SessionError) -> JSONResponse:
        return JSONResponse({"error": "session", "message": "This demo chat can't be continued, so a new one was started."},
                            status_code=409)

    @app.exception_handler(ActionError)
    async def _action_error(request: Request, exc: ActionError) -> JSONResponse:
        return JSONResponse({"error": "action", "message": str(exc)}, status_code=409)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unexpected error")
        return JSONResponse({"error": "server", "message": "Something went wrong on our side. Try again, or start a new chat."},
                            status_code=500)

    @app.get("/api/config")
    def config() -> dict[str, Any]:
        agent_: Agent = app.state.agent
        live = agent_.live
        skills = [{"name": s.name, "description": s.description, "files": list(s.files)}
                  for s in (agent_.skills or default_library()).skills.values()]
        return {"firm": crm_data.FIRM, "firm_line": crm_data.FIRM_LINE, "live": live is not None,
                "live_available": agent_.live_available(), "model": getattr(live, "name", None),
                "brokers": [{"id": b["id"], "name": b["name"]} for b in crm_data.BROKERS], "skills": skills,
                "story": story(date.today()), "chips": CHIPS, "stages": crm_data.STAGES}

    @app.post("/api/new")
    async def new(request: Request) -> dict[str, Any]:
        data = await body(request)
        broker_id = data.get("broker") if isinstance(data.get("broker"), str) else "B-1"
        session = new_session(str(broker_id))
        return {"session": session, "view": view(start(session, app.state.agent.skills)), "more": False}

    @app.post("/api/step")
    async def step(request: Request) -> dict[str, Any]:
        who = visitor(request)
        if not app.state.limiter.allow("r:" + who, *PER_VISITOR_REQUESTS):
            raise ActionError("Too many requests from this connection. Wait a few minutes and try again.")
        data = await body(request)
        raw_action = data.get("action")
        action: dict[str, Any] = raw_action if isinstance(raw_action, dict) else {}
        want_live = data.get("live", True) is not False
        allowed, note = True, "visitor_limit"
        if want_live and action.get("type") in ("broker", "continue"):
            if not app.state.limiter.allow("v:" + who, *PER_VISITOR):
                allowed = False
            elif not app.state.limiter.allow("instance", *PER_INSTANCE):
                allowed, note = False, "busy"
        if not app.state.limiter.enter(who):
            raise ActionError("One moment: the previous reply is still on its way.")
        try:
            # The model call blocks: run it in a worker thread so other visitors are not kept waiting.
            result: dict[str, Any] = await run_in_threadpool(app.state.agent.handle, data.get("session"), action,
                                                             want_live=want_live, visitor_allowed=allowed, limit_note=note)
        finally:
            app.state.limiter.leave(who)
        return result

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    if serve_static and PUBLIC.is_dir():
        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(PUBLIC / "index.html")

        app.mount("/", StaticFiles(directory=PUBLIC), name="static")
    return app

