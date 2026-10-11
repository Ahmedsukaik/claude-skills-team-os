"""The assistant's tools in the web demo: their definitions for the model, and the code that runs them.

Every call goes through `run_tool`, which treats the input as untrusted (it may come from a model
that was talked into something, or from an edited browser session). The CRM (crm/) enforces its
own rules; this module adds two that only the demo can check, because only the demo sees the
whole conversation:

- no write is proposed before the house-rules skill is loaded in the chat;
- a time in a write (`stated_time_text`, `due_text`) must be the broker's own words, found in
  what the broker typed in this chat. A date the model worked out is refused.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from crm import CRM, CRMError
from crm.store import OPS

from .skills import SkillError, SkillLibrary, default_library

HOUSE_RULES = "house-rules"
STR = {"type": "string"}


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"name": name, "description": description, "strict": True,
            "input_schema": {"type": "object", "properties": properties, "required": required, "additionalProperties": False}}


def tool_definitions(library: SkillLibrary) -> list[dict[str, Any]]:
    skill_names = {"type": "string", "enum": library.names()}
    change = {"type": "object", "additionalProperties": False, "required": ["op"], "properties": {
        "op": {"type": "string", "enum": list(OPS)},
        "contact_id": STR, "company_id": STR, "deal_id": STR, "property_id": STR,
        "summary": {"type": "string", "description": "create_note: one line."},
        "discussed": {"type": "array", "items": STR, "description": "create_note: short facts, in the person's words."},
        "next_steps": {"type": "array", "items": STR, "description": "create_note: actions as the person named them."},
        "stated_time_text": {"type": "string", "description": "When it happened, copied word for word from the person. "
                                                              "Leave out if they gave no time. Never a date you worked out."},
        "title": {"type": "string", "description": "create_task: the action, starting with a verb."},
        "due_text": {"type": "string", "description": "create_task: when it is due, copied word for word from the person. "
                                                      "Leave out if they gave no time."},
        "first_name": STR, "last_name": STR, "email": STR, "job_title": STR,
        "name": {"type": "string", "description": "create_company: the company name."},
        "industry": STR,
        "stage": {"type": "string", "description": "update_deal_stage: the new stage name."},
    }}
    return [
        _tool("load_skill", "Load one of the firm's skills: returns its instructions (SKILL.md) and the list of its "
                            "supporting files. Load a skill before acting on a request it fits.",
              {"name": skill_names}, ["name"]),
        _tool("read_skill_file", "Read a supporting file of a loaded skill (a field map, a template, an example), when "
                                 "its instructions point to it.",
              {"skill": skill_names, "path": {"type": "string", "description": "The file path as the skill lists it."}},
              ["skill", "path"]),
        _tool("search_crm", "Search the CRM for contacts, companies, deals and properties by name, email or address. "
                            "Returns ids to use in other tools. Every match is returned, so two people with the same "
                            "name both appear.",
              {"query": {"type": "string", "description": "A name, company, property address or deal name."},
               "record_type": {"type": "string", "enum": ["contact", "company", "deal", "property"]}}, ["query"]),
        _tool("get_record", "Open one CRM record by id (C-, CO-, D-, P-). A contact comes with their company, deals, "
                            "recent notes, open tasks and upcoming meetings; a deal with its stage, notes, tasks and "
                            "days since the last activity.",
              {"record_id": {"type": "string"}}, ["record_id"]),
        _tool("list_deals", "List deals with their stage, owner, last activity and whether they are stale (no logged "
                            "activity for 21 days or more), plus counts by stage. Read only.",
              {"stage": {"type": "string"}, "owner": {"type": "string", "description": "A broker's name."}}, []),
        _tool("get_calendar", "Upcoming meetings, calls and tours from the firm's calendar, with who attends.",
              {"days_ahead": {"type": "integer", "description": "How many days ahead, 0 to 31. Default 7."},
               "contact_id": {"type": "string", "description": "Only meetings with this contact."}}, []),
        _tool("propose_write", "Propose a change to the CRM. Saves nothing: it checks the change and returns a "
                               "preview, a write_id and a payload_hash. Read the preview back to the broker in full. "
                               "Times are given only as the broker's words (stated_time_text, due_text); the CRM sets "
                               "recorded_at from its own clock and turns words into a date only when they are exact. "
                               "A duplicate contact or company is blocked and the existing record returned.",
              {"summary": {"type": "string", "description": "One line describing the whole write."},
               "changes": {"type": "array", "items": change, "description": "One entry per record to create or change."}},
              ["summary", "changes"]),
        _tool("commit_write", "Save a proposed write. In this demo only the broker can save: they press Confirm on the "
                              "read back card, which carries their confirmation. A call from you is refused and saves "
                              "nothing. When the broker says yes in the chat, ask them to press Confirm on the card.",
              {"write_id": STR, "payload_hash": STR}, ["write_id", "payload_hash"]),
        _tool("create_email_draft", "Save an email to a CRM contact as a draft in the broker's mailbox. It is never "
                                    "sent: the broker reviews and sends it themselves. There is no tool that sends email.",
              {"contact_id": STR, "subject": STR, "body": STR}, ["contact_id", "subject", "body"]),
    ]


TOOLS = tool_definitions(default_library())
TOOL_NAMES = {t["name"] for t in TOOLS}


@dataclass
class ToolResult:
    content: str
    is_error: bool = False
    label: str = ""
    skill: str | None = None          # a skill loaded by this call
    write_id: str | None = None       # a write proposed by this call
    outcome: str = "ok"


@dataclass
class ToolContext:
    crm: CRM
    skills: SkillLibrary
    actor: str                                         # "Claude for Priya Natarajan"
    loaded: set[str] = field(default_factory=set)      # skills loaded so far in this chat
    broker_words: list[str] = field(default_factory=list)


def _norm(text: str) -> str:
    text = text.lower().replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    return " ".join(re.sub(r"[^\w:/'\-]+", " ", text).split())


def said_by_broker(words: str, broker_words: list[str]) -> bool:
    phrase = _norm(words)
    return bool(phrase) and any(f" {phrase} " in f" {_norm(t)} " for t in broker_words)


def _ok(data: Any, label: str, **extra: Any) -> ToolResult:
    return ToolResult(json.dumps(data, ensure_ascii=False), False, label, **extra)


def _err(error: str, message: str, label: str, outcome: str = "refused", **data: Any) -> ToolResult:
    return ToolResult(json.dumps({"error": error, "message": message, **data}, ensure_ascii=False), True, label,
                      outcome=outcome)


def run_tool(ctx: ToolContext, name: str, data: Any) -> ToolResult:
    if not isinstance(data, dict):
        return _err("invalid", "Tool input must be an object.", "A step was refused")
    try:
        return _run(ctx, name, data)
    except CRMError as e:
        label = {"duplicate_contact": "Blocked: that contact is already in the CRM",
                 "duplicate_company": "Blocked: that company is already in the CRM",
                 "needs_confirm": "Save refused: it needs the broker's Confirm"}.get(e.code, "Refused by the CRM")
        return _err(e.code, e.message, label, e.outcome, **e.extra)
    except SkillError as e:
        return _err("skill", str(e), "A skill file was not found")
    except (TypeError, ValueError, KeyError) as e:
        return _err("invalid", f"Bad input for {name}: {type(e).__name__}.", "A step was refused")


def _str(data: dict[str, Any], key: str, default: str = "") -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise TypeError(key)
    return value


def _run(ctx: ToolContext, name: str, data: dict[str, Any]) -> ToolResult:
    crm = ctx.crm
    if name == "load_skill":
        skill = ctx.skills.get(_str(data, "name"))
        ctx.loaded.add(skill.name)
        return _ok({"skill": skill.name, "instructions": skill.body, "files": list(skill.files)},
                   f"Loaded the {skill.name} skill", skill=skill.name)
    if name == "read_skill_file":
        skill_name, path = _str(data, "skill"), _str(data, "path")
        return _ok({"skill": skill_name, "path": path, "content": ctx.skills.read_file(skill_name, path)},
                   f"Read {skill_name}: {path}")
    if name == "search_crm":
        query = _str(data, "query")
        kind = data.get("record_type") or None
        results = crm.search(ctx.actor, query, kind if isinstance(kind, str) else None)
        return _ok({"query": query, "results": results}, f"Looked up '{query[:40]}' ({len(results)} found)")
    if name == "get_record":
        record_id = _str(data, "record_id")
        rec = crm.get(ctx.actor, record_id)
        return _ok(rec, f"Opened {crm.label(record_id)}")
    if name == "list_deals":
        stage, owner = data.get("stage") or None, data.get("owner") or None
        return _ok(crm.pipeline(ctx.actor, stage if isinstance(stage, str) else None, owner if isinstance(owner, str) else None),
                   "Read the deal pipeline")
    if name == "get_calendar":
        days = data.get("days_ahead", 7)
        contact = data.get("contact_id") or None
        events = crm.calendar(ctx.actor, days if isinstance(days, int) and not isinstance(days, bool) else 7,
                              contact if isinstance(contact, str) else None)
        return _ok({"events": events}, "Checked the calendar")
    if name == "propose_write":
        if HOUSE_RULES not in ctx.loaded:
            crm.write_log(ctx.actor, "propose write", "refused: the house-rules skill was not loaded", "refused")
            return _err("house_rules_not_loaded", "Load the house-rules skill first (load_skill), then propose again. "
                                                  "Every write follows the house rules.", "Write refused: house rules not loaded")
        changes = data.get("changes")
        for change in changes if isinstance(changes, list) else []:
            for key in ("stated_time_text", "due_text"):
                words = change.get(key) if isinstance(change, dict) else None
                if isinstance(words, str) and words.strip() and not said_by_broker(words, ctx.broker_words):
                    crm.write_log(ctx.actor, "propose write", f"refused: '{words[:60]}' is not in the broker's words",
                                  "refused")
                    return _err("time_not_stated", f"'{words}' is not something the broker said. Copy a time exactly as "
                                                   "the broker said it, or leave it out. Never work a date out yourself.",
                                "Write refused: a time not in the broker's words")
        preview = crm.propose_write(ctx.actor, _str(data, "summary"), changes)
        return _ok(preview, "Prepared a change for the broker's confirm", write_id=preview["write_id"])
    if name == "commit_write":
        # The model never holds the broker's confirmation, so this is refused by the CRM's confirm policy.
        result = crm.commit_write(ctx.actor, data.get("write_id"), data.get("payload_hash"), None)
        return _ok(result, "Saved")  # not reachable with the demo's Confirm button policy
    if name == "create_email_draft":
        draft = crm.create_draft(ctx.actor, _str(data, "contact_id"), _str(data, "subject"), _str(data, "body"))
        return _ok(draft, "Saved an email draft (not sent)")
    return _err("unknown_tool", f"There is no tool {name}.", "A step was refused")
