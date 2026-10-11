"""The fake CRM's tools as an MCP server, so the skills in skills/ work with a real Claude client.

    python -m mcp_server            (stdio; Claude Code or Claude Desktop starts it)

The tools have the same names the skills use: search_crm, get_record, list_deals, get_calendar,
propose_write, commit_write, discard_write, create_email_draft, and get_activity_log.

What the server can and cannot enforce. Over MCP the server sees tool calls, not the person, so
it cannot prove that a human said yes. It enforces what it can see:
- nothing is saved without propose_write first (two steps);
- commit_write needs the payload_hash from the preview, and the payload must be unchanged;
- a write id expires after 30 minutes and works once;
- commit_write needs the person's own words of confirmation, refuses words that are not a
  plain yes ("just log it, don't ask me"), and logs them with the save;
- timestamps, duplicates and the activity log, as in crm/.
The read back itself, and waiting for a real yes, is the house-rules skill's job. The web demo
goes further: there, only the broker's Confirm button can save (see teamos/session.py).

The CRM lives in memory: it starts fresh from the fictional data each time the server starts.
"""
from __future__ import annotations

import functools
import os
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from crm import CRM, CRMError, StatedConfirm
from crm import data as crm_data

INSTRUCTIONS = (
    f"Tools for the CRM of {crm_data.FIRM_LINE}. Reads are logged. Writes take two steps: propose_write saves "
    "nothing and returns a preview, a write_id and a payload_hash; read the preview back to the person in full and "
    "call commit_write only after their explicit yes, passing their words in user_confirmation. Give times only as "
    "the person's words (stated_time_text, due_text); the CRM sets recorded_at itself. There is no tool that sends "
    "email: create_email_draft saves a draft for the person to send."
)
Op = Literal["create_note", "create_task", "create_contact", "update_contact", "create_company", "update_deal_stage"]


class Change(BaseModel):
    """One record to create or change. Fill only the fields the op takes."""

    model_config = ConfigDict(extra="forbid")
    op: Op
    contact_id: str | None = None
    company_id: str | None = None
    deal_id: str | None = None
    property_id: str | None = None
    summary: str | None = Field(None, description="create_note: one line")
    discussed: list[str] | None = Field(None, description="create_note: short facts, in the person's words")
    next_steps: list[str] | None = Field(None, description="create_note: actions as the person named them")
    stated_time_text: str | None = Field(None, description="when it happened, word for word from the person")
    title: str | None = Field(None, description="create_task: the action")
    due_text: str | None = Field(None, description="create_task: when it is due, word for word from the person")
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    job_title: str | None = None
    name: str | None = Field(None, description="create_company: the company name")
    industry: str | None = None
    stage: str | None = Field(None, description="update_deal_stage: one of " + ", ".join(crm_data.STAGES))


def build_server(crm: CRM, actor: str | None = None) -> MCPServer:
    who = actor or f"Claude via MCP for {crm.user}"
    server = MCPServer("brokerage-crm", instructions=INSTRUCTIONS, version="1.0.0")

    def tool(title: str, read_only: bool) -> Callable[[Callable[..., Awaitable[dict[str, Any]]]], Any]:
        def decorator(fn: Callable[..., Awaitable[dict[str, Any]]]) -> Any:
            @functools.wraps(fn)
            async def guarded(*args: Any, **kwargs: Any) -> dict[str, Any]:
                try:
                    return await fn(*args, **kwargs)
                except CRMError as e:  # the CRM already logged it; the model gets the reason in plain words
                    raise ToolError(e.message) from e

            server.add_tool(guarded, name=fn.__name__, title=title, description=fn.__doc__,
                            annotations=ToolAnnotations(title=title, readOnlyHint=read_only, destructiveHint=False,
                                                        idempotentHint=read_only, openWorldHint=False))
            return guarded
        return decorator

    @tool("Search the CRM", True)
    async def search_crm(query: str, record_type: Literal["contact", "company", "deal", "property"] | None = None
                         ) -> dict[str, Any]:
        """Search contacts, companies, deals and properties by name, email or address. Every match is returned, so
        two people with the same first name both appear: ask the person which one they mean."""
        return {"query": query, "results": crm.search(who, query, record_type)}

    @tool("Open a record", True)
    async def get_record(record_id: str) -> dict[str, Any]:
        """One record by id (C-, CO-, D-, P-). A contact comes with their company, deals, recent notes, open tasks
        and upcoming meetings; a deal with its stage, notes, tasks and days since the last activity."""
        return crm.get(who, record_id)

    @tool("List deals", True)
    async def list_deals(stage: str | None = None, owner: str | None = None) -> dict[str, Any]:
        """Deals with stage, owner, last activity and a stale flag (no logged activity for 21+ days), plus counts
        by stage."""
        return crm.pipeline(who, stage, owner)

    @tool("Check the calendar", True)
    async def get_calendar(days_ahead: int = 7, contact_id: str | None = None) -> dict[str, Any]:
        """Upcoming meetings, calls and tours, with who attends. days_ahead is 0 to 31."""
        return {"events": crm.calendar(who, days_ahead, contact_id)}

    @tool("Propose a CRM change", False)
    async def propose_write(summary: str, changes: list[Change]) -> dict[str, Any]:
        """Propose a change. Saves nothing: returns a preview, a write_id and a payload_hash. Read the preview back
        in full, flags included, and wait for an explicit yes. Times go in only as the person's words."""
        return crm.propose_write(who, summary, [c.model_dump(exclude_none=True) for c in changes])

    @tool("Save a confirmed change", False)
    async def commit_write(write_id: str, payload_hash: str, user_confirmation: str) -> dict[str, Any]:
        """Save a proposed write after the person said yes to its read back. user_confirmation is their own words
        ("yes, save it"); it is checked and logged. Refused if the payload changed, the write expired (30 minutes),
        was already used, or the words are not a plain yes."""
        return crm.commit_write(who, write_id, payload_hash, user_confirmation)

    @tool("Discard a proposed change", False)
    async def discard_write(write_id: str) -> dict[str, Any]:
        """Drop a proposed write that the person does not want. Nothing is saved."""
        return crm.discard_write(who, write_id)

    @tool("Save an email draft", False)
    async def create_email_draft(contact_id: str, subject: str, body: str) -> dict[str, Any]:
        """Save an email to a CRM contact as a draft for the person to review and send. Never sends."""
        return crm.create_draft(who, contact_id, subject, body)

    @tool("Read the activity log", True)
    async def get_activity_log(limit: int = 20) -> dict[str, Any]:
        """The latest entries of the CRM's activity log: system time, actor, action, detail, outcome."""
        return {"entries": crm.log[-max(1, min(int(limit), 200)):]}

    return server


def main() -> None:
    user = os.environ.get("TEAMOS_MCP_USER", crm_data.BROKERS[0]["name"])
    crm = CRM.new(date.today(), StatedConfirm(), user=user)
    build_server(crm).run("stdio")


if __name__ == "__main__":
    main()
