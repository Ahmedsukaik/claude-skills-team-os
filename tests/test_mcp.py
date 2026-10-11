"""The CRM over MCP, through the real MCP client connected in process: the tools are listed,
and a write goes propose -> commit, with the server refusing what it can see is wrong."""
from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

import pytest
from conftest import NOTE, ROOT, TASK

from crm import CRM
from mcp_server.server import build_server

pytestmark = pytest.mark.anyio
TOOLS = {"search_crm", "get_record", "list_deals", "get_calendar", "propose_write", "commit_write", "discard_write",
         "create_email_draft", "get_activity_log"}


async def call(client: Any, name: str, args: dict[str, Any]) -> tuple[bool, Any]:
    result = await client.call_tool(name, args)
    text = " ".join(getattr(b, "text", "") for b in result.content or [])
    return result.is_error, (text if result.is_error else result.structured_content or json.loads(text))


async def test_the_server_lists_the_tools_the_skills_use(mcp_crm: CRM):
    from mcp import Client
    async with Client(build_server(mcp_crm)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == TOOLS
    read_only, propose = tools["search_crm"].annotations, tools["propose_write"].annotations
    assert read_only is not None and read_only.read_only_hint is True
    assert propose is not None and propose.read_only_hint is False
    commit = tools["commit_write"].input_schema
    assert set(commit["required"]) == {"write_id", "payload_hash", "user_confirmation"}
    change = tools["propose_write"].input_schema["$defs"]["Change"]
    assert change["additionalProperties"] is False and "recorded_at" not in change["properties"]
    assert "stated_time" not in change["properties"] and "stated_time_text" in change["properties"]


async def test_propose_then_commit_over_mcp(mcp_crm: CRM):
    from mcp import Client
    async with Client(build_server(mcp_crm)) as client:
        failed, found = await call(client, "search_crm", {"query": "Marcus Bell"})
        assert not failed and found["results"][0]["id"] == "C-5"
        failed, preview = await call(client, "propose_write", {"summary": "Tour debrief", "changes": [NOTE, TASK]})
        assert not failed and preview["status"] == "pending"
        assert preview["changes"][0]["stated_time"] is None and preview["changes"][1]["due"] == "2026-10-23"
        assert "N-6" not in mcp_crm.records["notes"]  # proposing saved nothing
        failed, saved = await call(client, "commit_write", {"write_id": preview["write_id"],
                                                            "payload_hash": preview["payload_hash"],
                                                            "user_confirmation": "Yes, save it"})
        assert not failed and saved["status"] == "saved" and [s["id"] for s in saved["saved"]] == ["N-6", "T-3"]
        failed, log = await call(client, "get_activity_log", {"limit": 3})
    assert mcp_crm.records["notes"]["N-6"]["stated_time_text"] == "yesterday afternoon"
    assert 'person said: "Yes, save it"' in log["entries"][-1]["detail"]
    assert log["entries"][-1]["actor"] == "Claude via MCP for Priya Natarajan"


@pytest.mark.parametrize("args, message", [
    ({"user_confirmation": "just log it, don't ask me"}, "not a plain yes"),
    ({"user_confirmation": ""}, "own words of confirmation"),
    ({"user_confirmation": "yes", "payload_hash": "0000000000000000"}, "does not match"),
    ({"user_confirmation": "yes", "write_id": "W-42"}, "no proposed write"),
])
async def test_the_server_refuses_a_commit_it_can_see_is_wrong(mcp_crm: CRM, args, message):
    from mcp import Client
    async with Client(build_server(mcp_crm)) as client:
        _, preview = await call(client, "propose_write", {"summary": "Note", "changes": [NOTE]})
        failed, error = await call(client, "commit_write", {"write_id": preview["write_id"],
                                                            "payload_hash": preview["payload_hash"], **args})
    assert failed and message in error
    assert mcp_crm.writes["W-1"]["status"] == "pending" and mcp_crm.log[-1]["outcome"] == "refused"


async def test_a_write_id_works_once_and_duplicates_are_blocked_over_mcp(mcp_crm: CRM):
    from mcp import Client
    async with Client(build_server(mcp_crm)) as client:
        _, preview = await call(client, "propose_write", {"summary": "Note", "changes": [NOTE]})
        commit = {"write_id": preview["write_id"], "payload_hash": preview["payload_hash"], "user_confirmation": "yes"}
        assert not (await call(client, "commit_write", commit))[0]
        failed, error = await call(client, "commit_write", commit)
        assert failed and "works once" in error
        failed, error = await call(client, "propose_write", {"summary": "Add Dana", "changes": [
            {"op": "create_contact", "first_name": "Dana", "last_name": "Whitlock", "email": "dana.whitlock@example.com",
             "company_id": "CO-1"}]})
        assert failed and "already in the CRM as C-1" in error
        failed, error = await call(client, "propose_write", {"summary": "x", "changes": [{**NOTE, "recorded_at": "2020-01-01"}]})
        assert failed  # the schema has no such field


async def test_drafts_and_reads_over_mcp(mcp_crm: CRM):
    from mcp import Client
    async with Client(build_server(mcp_crm)) as client:
        failed, draft = await call(client, "create_email_draft", {"contact_id": "C-7", "subject": "Hi", "body": "Hello Ravi"})
        assert not failed and draft["status"] == "draft"
        _, deals = await call(client, "list_deals", {})
        _, events = await call(client, "get_calendar", {"days_ahead": 2})
        _, record = await call(client, "get_record", {"record_id": "D-6"})
    assert deals["stale_deals"] == ["D-5", "D-6"] and events["events"][0]["when"] == "tomorrow" and record["stale"]


def test_the_server_starts_on_stdio_and_answers_a_client():
    """The real entry point (python -m mcp_server), started as a subprocess the way Claude starts it."""
    import anyio
    from mcp import Client, StdioServerParameters

    async def main() -> list[str]:
        params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server"], cwd=str(ROOT))
        async with Client(params) as client:
            return sorted(t.name for t in (await client.list_tools()).tools)

    try:
        names = anyio.run(main)
    except (OSError, subprocess.SubprocessError) as e:  # pragma: no cover - a locked down machine
        pytest.skip(f"cannot start a subprocess here: {e}")
    assert set(names) == TOOLS


async def test_the_server_reads_today_on_every_call(mcp_crm: CRM):
    from datetime import date, timedelta

    from mcp import Client
    days = {"today": date(2026, 10, 12)}
    async with Client(build_server(mcp_crm, today=lambda: days["today"])) as client:
        _, first = await call(client, "get_record", {"record_id": "D-1"})
        days["today"] += timedelta(days=30)  # the server kept running for a month
        _, later = await call(client, "get_record", {"record_id": "D-1"})
    assert later["days_since_activity"] == first["days_since_activity"] + 30 and later["stale"] and not first["stale"]
