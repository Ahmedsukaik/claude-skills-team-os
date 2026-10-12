"""A small fake CRM (HubSpot-like contacts, companies, deals, notes and tasks) with its rules in code.

The rules hold whoever calls: the model through a tool, the MCP server, or a test.

1. Two step writes. `propose_write` checks a change and returns a preview, a `write_id` and a
   `payload_hash`; nothing changes. `commit_write` applies it only with a valid confirmation
   (see confirm.py), only if the payload still hashes to what was previewed, only before the
   write expires, and only once. If the CRM changed in between (the deal moved on, the same
   contact was added), the commit is refused and the write must be proposed again.
2. The timestamp rule. Every saved record gets `recorded_at` from the CRM's clock. A time the
   person stated is kept in their words, and as a date only when the words are exact
   (timestamps.py). Callers cannot pass a date of their own: only the words.
3. Duplicate check. Creating a contact with an email already in the CRM, or the same name at
   the same company, is blocked and returns the match. The same for a company name. Names are
   compared folded (text.py), and every change is checked against the CRM as it would be after
   the earlier changes of the same write, so one write cannot hold two copies of a contact.
4. Every read and write is logged: actor, action, detail, outcome, system time.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from . import data
from .confirm import ConfirmPolicy
from .errors import CRMError
from .text import has_letter_or_digit, mixed_script, name_key, strip_control, words
from .timestamps import nice, read_stated_time

WRITE_TTL = timedelta(minutes=30)
MAX_CHANGES = 8
MAX_LIST = 12
LIMITS = {"summary": 200, "title": 200, "first_name": 60, "last_name": 60, "email": 120, "job_title": 80, "name": 120,
          "industry": 80, "stage": 40, "stated_time_text": 120, "due_text": 120, "item": 300}
OPS: dict[str, tuple[set[str], set[str]]] = {   # op: (required, optional)
    "create_note": ({"contact_id", "summary"}, {"company_id", "deal_id", "property_id", "discussed", "next_steps",
                                                "stated_time_text"}),
    "create_task": ({"title"}, {"contact_id", "deal_id", "due_text"}),
    "create_contact": ({"first_name", "last_name", "email", "company_id"}, {"job_title"}),
    "update_contact": ({"contact_id"}, {"email", "job_title"}),
    "create_company": ({"name"}, {"industry"}),
    "update_deal_stage": ({"deal_id", "stage"}, {"stated_time_text"}),
}
LIST_FIELDS = {"discussed", "next_steps"}
EMAIL = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+$")
WORDS_DROPPED = {"the", "a", "an", "of", "and", "for", "with", "from", "at", "to", "in", "on", "s", "co", "inc", "llc"}
# Words that do not make a company different: "Acme", "Acme Inc" and "Acme Group" are one company.
COMPANY_SUFFIXES = {"ltd", "corp", "corporation", "company", "group", "limited", "plc", "llp", "gmbh", "inc", "llc", "co"}
ID = re.compile(r"^(?:C|CO|D|P|N|T|E|W|M)-\d{1,5}$")
KINDS = {"C": "contact", "CO": "company", "D": "deal", "P": "property", "N": "note", "T": "task", "E": "event", "M": "draft"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def tokens(text: str) -> list[str]:
    return [t for t in words(text) if t not in WORDS_DROPPED]


def company_key(name: str) -> str:
    """A company name as one run of letters and digits, without "Inc", "Group" and the like."""
    return "".join(t for t in tokens(name) if t not in COMPANY_SUFFIXES)


def payload_hash(summary: str, changes: list[dict[str, Any]]) -> str:
    body = json.dumps({"summary": summary, "changes": changes}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def _text(value: Any, name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise CRMError("invalid", f"{name} must be text.")
    value = " ".join(strip_control(value).split())
    if len(value) > limit:
        raise CRMError("invalid", f"{name} is too long (at most {limit} characters).")
    return value


@dataclass
class CRM:
    today: date
    confirm: ConfirmPolicy
    user: str = "Priya Natarajan"                       # the person this CRM session acts for
    clock: Callable[[], datetime] = utc_now
    records: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    writes: dict[str, dict[str, Any]] = field(default_factory=dict)
    drafts: dict[str, dict[str, Any]] = field(default_factory=dict)
    log: list[dict[str, Any]] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)

    @classmethod
    def new(cls, today: date, confirm: ConfirmPolicy, user: str = "Priya Natarajan",
            clock: Callable[[], datetime] = utc_now) -> CRM:
        crm = cls(today, confirm, user, clock, data.seed(today))
        for prefix, table in (("C", "contacts"), ("CO", "companies"), ("D", "deals"), ("P", "properties"),
                              ("N", "notes"), ("T", "tasks"), ("E", "events")):
            crm.counters[prefix] = max((int(k.split("-")[1]) for k in crm.records[table]), default=0)
        crm.counters.update(W=0, M=0)
        return crm

    # ------------------------------------------------------------------ helpers
    @property
    def contacts(self) -> dict[str, dict[str, Any]]:
        return self.records["contacts"]

    @property
    def companies(self) -> dict[str, dict[str, Any]]:
        return self.records["companies"]

    @property
    def deals(self) -> dict[str, dict[str, Any]]:
        return self.records["deals"]

    @property
    def properties(self) -> dict[str, dict[str, Any]]:
        return self.records["properties"]

    def now(self) -> str:
        return iso(self.clock())

    def record(self, record_id: str) -> dict[str, Any] | None:
        table = {"C": "contacts", "CO": "companies", "D": "deals", "P": "properties", "N": "notes", "T": "tasks",
                 "E": "events"}.get(record_id.split("-")[0])
        return self.records[table].get(record_id) if table else None

    def _next(self, prefix: str) -> str:
        self.counters[prefix] = self.counters.get(prefix, 0) + 1
        return f"{prefix}-{self.counters[prefix]}"

    def write_log(self, actor: str, action: str, detail: str, outcome: str = "ok", ref: str = "") -> None:
        """detail is plain words; ref holds the record and write ids involved."""
        self.log.append({"at": self.now(), "actor": actor, "action": action, "detail": detail[:300], "outcome": outcome,
                         "ref": ref[:120]})

    def label(self, record_id: str | None) -> str:
        rec = self.record(record_id) if record_id else None
        if rec is None:
            return record_id or ""
        if record_id and record_id.startswith("C-"):
            return f"{rec['name']} ({self.companies[rec['company_id']]['name']})"
        if record_id and record_id.startswith("D-"):
            return f"{rec['name']} ({rec['stage']})"
        return str(rec.get("name") or rec.get("summary") or rec.get("title") or record_id)

    def _need(self, record_id: Any, prefix: str, what: str) -> dict[str, Any]:
        if not isinstance(record_id, str) or not ID.match(record_id) or not record_id.startswith(prefix + "-"):
            raise CRMError("invalid", f"{what} must be an id like {prefix}-1 from a search.")
        rec = self.record(record_id)
        if rec is None:
            raise CRMError("not_found", f"There is no {what.replace('_id', '').replace('_', ' ')} {record_id}.")
        return rec

    # ------------------------------------------------------------------ reads (each one logged)
    def search(self, actor: str, query: str, kind: str | None = None, limit: int = 12) -> list[dict[str, Any]]:
        query = _text(query, "query", 120)
        wanted = tokens(query)
        if not wanted:
            self.write_log(actor, "search", f"'{query}': nothing to search for", "refused")
            raise CRMError("invalid", "Search with a name, a company, a property or a deal.")
        found: list[tuple[int, dict[str, Any]]] = []
        for rec_kind, table, text in self._searchable():
            if kind and kind != rec_kind:
                continue
            words = tokens(text)
            if all(any(w.startswith(q) for w in words) for q in wanted):
                exact = sum(q in words for q in wanted)
                found.append((exact, self._brief(rec_kind, table)))
        found.sort(key=lambda x: -x[0])
        results = [r for _, r in found[:limit]]
        self.write_log(actor, "search", f"'{query}': {len(results)} found")
        return results

    def _searchable(self) -> list[tuple[str, dict[str, Any], str]]:
        out = []
        for c in self.contacts.values():
            out.append(("contact", c, f"{c['name']} {c['email']} {self.companies[c['company_id']]['name']}"))
        out += [("company", co, co["name"]) for co in self.companies.values()]
        out += [("deal", d, d["name"]) for d in self.deals.values()]
        out += [("property", p, f"{p['name']} {p['address']}") for p in self.properties.values()]
        return out

    def _brief(self, kind: str, rec: dict[str, Any]) -> dict[str, Any]:
        if kind == "contact":
            return {"id": rec["id"], "type": "contact", "name": rec["name"], "job_title": rec["job_title"],
                    "company_id": rec["company_id"], "company": self.companies[rec["company_id"]]["name"], "email": rec["email"]}
        if kind == "deal":
            return {"id": rec["id"], "type": "deal", "name": rec["name"], "stage": rec["stage"], "owner": rec["owner"],
                    "contact_id": rec["contact_id"], "contact": self.contacts[rec["contact_id"]]["name"],
                    "company_id": rec["company_id"], "property_id": rec["property_id"]}
        if kind == "property":
            return {"id": rec["id"], "type": "property", "name": rec["name"], "address": rec["address"],
                    "property_type": rec["type"], "square_feet": rec["square_feet"]}
        return {"id": rec["id"], "type": "company", "name": rec["name"], "industry": rec.get("industry")}

    def get(self, actor: str, record_id: str) -> dict[str, Any]:
        rec = self.record(record_id) if isinstance(record_id, str) and ID.match(record_id) else None
        if rec is None:
            self.write_log(actor, "open record", "not found", "refused", str(record_id)[:40])
            raise CRMError("not_found", f"There is no record {record_id}. Use an id from a search.")
        out = self._full(record_id, rec)
        self.write_log(actor, "open record", self.label(record_id), ref=record_id)
        return out

    def _notes_for(self, key: str, value: str, n: int = 3) -> list[dict[str, Any]]:
        notes = [x for x in self.records["notes"].values() if x.get(key) == value]
        notes.sort(key=lambda x: x["recorded_at"], reverse=True)
        return [{k: x[k] for k in ("id", "summary", "discussed", "next_steps", "stated_time_text", "stated_time",
                                   "recorded_at", "logged_by")} for x in notes[:n]]

    def _tasks_for(self, key: str, value: str) -> list[dict[str, Any]]:
        return [{k: t[k] for k in ("id", "title", "status", "due_text", "due", "logged_by")}
                for t in self.records["tasks"].values() if t.get(key) == value and t["status"] == "open"]

    def _full(self, record_id: str, rec: dict[str, Any]) -> dict[str, Any]:
        out = copy.deepcopy(rec)
        if record_id.startswith("C-"):
            out["company"] = self.companies[rec["company_id"]]["name"]
            out["deals"] = [{**self._brief("deal", d), "last_activity": d["last_activity"], **self._activity_age(d)}
                            for d in self.deals.values() if d["contact_id"] == record_id]
            out["recent_notes"] = self._notes_for("contact_id", record_id)
            out["open_tasks"] = self._tasks_for("contact_id", record_id)
            out["upcoming_events"] = [self._event(e) for e in self._events(14) if record_id in e["contact_ids"]]
        elif record_id.startswith("CO-"):
            out["contacts"] = [self._brief("contact", c) for c in self.contacts.values() if c["company_id"] == record_id]
            out["deals"] = [self._brief("deal", d) for d in self.deals.values() if d["company_id"] == record_id]
        elif record_id.startswith("D-"):
            out["contact"] = self.contacts[rec["contact_id"]]["name"]
            out["company"] = self.companies[rec["company_id"]]["name"]
            out["property"] = self.properties[rec["property_id"]]["name"]
            out["recent_notes"] = self._notes_for("deal_id", record_id)
            out["open_tasks"] = self._tasks_for("deal_id", record_id)
            out.update(self._activity_age(rec))
        elif record_id.startswith("P-"):
            out["deals"] = [self._brief("deal", d) for d in self.deals.values() if d["property_id"] == record_id]
        return out

    def _activity_age(self, deal: dict[str, Any]) -> dict[str, Any]:
        days = (self.today - date.fromisoformat(deal["last_activity"])).days
        return {"days_since_activity": days, "stale": deal["stage"] in data.OPEN_STAGES and days >= data.STALE_DAYS}

    def pipeline(self, actor: str, stage: str | None = None, owner: str | None = None) -> dict[str, Any]:
        deals = []
        for d in self.deals.values():
            if stage and d["stage"].lower() != stage.lower():
                continue
            if owner and owner.lower() not in d["owner"].lower():
                continue
            deals.append({**self._brief("deal", d), "company": self.companies[d["company_id"]]["name"],
                          "property": self.properties[d["property_id"]]["name"], "last_activity": d["last_activity"],
                          **self._activity_age(d)})
        order = {s: i for i, s in enumerate(data.STAGES)}
        deals.sort(key=lambda d: (order[d["stage"]], d["id"]))
        by_stage = {s: sum(1 for d in deals if d["stage"] == s) for s in data.STAGES}
        out: dict[str, Any] = {"as_of": self.today.isoformat(), "stale_rule": f"an open deal with no logged activity for {data.STALE_DAYS} "
               "days or more", "by_stage": by_stage, "open_deals": sum(by_stage[s] for s in data.OPEN_STAGES),
               "stale_deals": [d["id"] for d in deals if d["stale"]], "deals": deals}
        self.write_log(actor, "read pipeline", f"{len(deals)} deals, {len(out['stale_deals'])} stale")
        return out

    def _events(self, days_ahead: int) -> list[dict[str, Any]]:
        end = self.today + timedelta(days=days_ahead)
        return sorted((e for e in self.records["events"].values()
                       if self.today <= date.fromisoformat(e["start"][:10]) <= end), key=lambda e: e["start"])

    def _event(self, e: dict[str, Any]) -> dict[str, Any]:
        days = (date.fromisoformat(e["start"][:10]) - self.today).days
        when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
        return {"id": e["id"], "title": e["title"], "start": e["start"], "when": when, "minutes": e["minutes"],
                "broker": e["broker"], "people": [{"id": c, "name": self.contacts[c]["name"]} for c in e["contact_ids"]],
                "property": self.properties[e["property_id"]]["name"] if e.get("property_id") else None}

    def calendar(self, actor: str, days_ahead: int = 7, contact_id: str | None = None) -> list[dict[str, Any]]:
        days_ahead = max(0, min(int(days_ahead), 31))
        events = [self._event(e) for e in self._events(days_ahead) if not contact_id or contact_id in e["contact_ids"]]
        who = f" with {self.contacts[contact_id]['name']}" if contact_id in self.contacts else ""
        self.write_log(actor, "read calendar", f"next {days_ahead} days{who}"
                       + f": {len(events)} events")
        return events

    # ------------------------------------------------------------------ email drafts (never sent)
    def create_draft(self, actor: str, contact_id: str, subject: str, body: str) -> dict[str, Any]:
        try:
            contact = self._need(contact_id, "C", "contact_id")
            subject, body = _text(subject, "subject", 160), _text_block(body)
            if not subject or not body:
                raise CRMError("invalid", "A draft needs a subject and a body.")
        except CRMError as e:
            self.write_log(actor, "draft email", e.plain, e.outcome)
            raise
        draft = {"id": self._next("M"), "to": contact["email"], "to_name": contact["name"], "contact_id": contact_id,
                 "subject": subject, "body": body, "status": "draft", "created_at": self.now()}
        self.drafts[draft["id"]] = draft
        self.write_log(actor, "draft email", f"to {contact['name']}: {subject} (draft, not sent)", ref=draft["id"])
        return {**draft, "next_step": "Saved as a draft in the broker's mailbox. It is not sent; the broker reviews and "
                                      "sends it themselves."}

    # ------------------------------------------------------------------ two step writes
    def propose_write(self, actor: str, summary: str, changes: Any) -> dict[str, Any]:
        try:
            summary = _text(summary, "summary", LIMITS["summary"])
            if not summary:
                raise CRMError("invalid", "Give the write a one line summary.")
            if not isinstance(changes, list) or not changes or len(changes) > MAX_CHANGES:
                raise CRMError("invalid", f"changes must be a list of 1 to {MAX_CHANGES} changes.")
            inputs = [self._input(c) for c in changes]
            normalized = self._check_all(inputs)
        except CRMError as e:
            self.write_log(actor, "propose write", f"{summary if isinstance(summary, str) else ''}: {e.plain}"[:300],
                           e.outcome)
            raise
        now = self.clock()
        write: dict[str, Any] = {"id": self._next("W"), "status": "pending", "summary": summary, "input": inputs, "changes": normalized,
                 "hash": payload_hash(summary, normalized), "proposed_by": actor, "proposed_at": iso(now),
                 "expires_at": iso(now + WRITE_TTL), "result": None, "flags": _flags(normalized)}
        self.writes[write["id"]] = write
        self.write_log(actor, "propose write", f"{summary} ({len(normalized)} change{'' if len(normalized) == 1 else 's'}), "
                       "waiting for a confirm", ref=write["id"])
        return self.preview(write)

    def preview(self, write: dict[str, Any]) -> dict[str, Any]:
        return {"write_id": write["id"], "status": write["status"], "payload_hash": write["hash"], "summary": write["summary"],
                "changes": copy.deepcopy(write["changes"]), "flags": list(write["flags"]), "proposed_at": write["proposed_at"],
                "expires_at": write["expires_at"],
                "next_step": "Nothing is saved yet. Read this back to the person in full, including any flags, and wait "
                             "for an explicit yes. recorded_at is set by the CRM clock at the moment it is saved."}

    def commit_write(self, actor: str, write_id: Any, payload_hash_given: Any, confirmation: Any) -> dict[str, Any]:
        write = self.writes.get(write_id) if isinstance(write_id, str) else None
        try:
            if write is None:
                raise CRMError("unknown_write", f"There is no proposed write {write_id}. Propose it first.",
                               plain="Nothing was proposed with that id, so nothing was saved.")
            if write["status"] == "committed":
                raise CRMError("already_used", f"{write_id} was already saved. A write id works once.",
                               plain="Already saved. A read back saves once.")
            if write["status"] == "discarded":
                raise CRMError("discarded", f"{write_id} was discarded. Propose it again if it is still wanted.",
                               plain="This change was discarded. Nothing was saved.")
            if write["status"] == "expired" or self.clock() > datetime.fromisoformat(write["expires_at"].replace("Z", "+00:00")):
                write["status"] = "expired"
                minutes = int(WRITE_TTL.total_seconds() // 60)
                raise CRMError("expired", f"{write_id} expired (a read back is valid for {minutes} minutes). Propose it "
                                          "again and read it back.",
                               plain=f"The read back expired after {minutes} minutes. Nothing was saved.")
            if payload_hash_given != write["hash"] or payload_hash(write["summary"], write["changes"]) != write["hash"]:
                raise CRMError("changed", "The payload does not match what was read back. Nothing was saved. Propose it "
                                          "again and read it back.",
                               plain="What was read back does not match, so nothing was saved.")
            how = self.confirm.check(write, confirmation)
            self._still_valid(write)
        except CRMError as e:
            self.write_log(actor, "save", e.plain, e.outcome, str(write_id)[:40])
            raise
        saved = [self._apply(c, write["id"]) for c in write["changes"]]
        write["status"], write["committed_at"] = "committed", self.now()
        write["result"] = {"saved": saved, "confirmed": how, "committed_by": actor}
        ids = ", ".join(s["id"] for s in saved)
        self.write_log(actor, "save", f"saved {_counted(saved)} ({how})", ref=f"{write['id']}: {ids}")
        return {"write_id": write["id"], "status": "saved", "saved": saved, "recorded_at": write["committed_at"]}

    def discard_write(self, actor: str, write_id: Any) -> dict[str, Any]:
        write = self.writes.get(write_id) if isinstance(write_id, str) else None
        if write is None or write["status"] != "pending":
            self.write_log(actor, "discard", "nothing waiting to discard", "refused", str(write_id)[:40])
            raise CRMError("not_pending", f"{write_id} is not waiting for a confirm.")
        write["status"] = "discarded"
        self.write_log(actor, "discard", f"{write['summary']}: discarded, nothing saved", ref=write_id)
        return {"write_id": write_id, "status": "discarded"}

    def is_expired(self, write: dict[str, Any]) -> bool:
        if write["status"] == "expired":
            return True
        return write["status"] == "pending" and self.clock() > datetime.fromisoformat(write["expires_at"].replace("Z", "+00:00"))

    def _still_valid(self, write: dict[str, Any]) -> None:
        """Between the read back and the confirm the CRM may have changed: check every change again."""
        try:
            again = self._check_all(write["input"])
        except CRMError as e:
            raise CRMError("stale", f"The CRM changed since the read back: {e.message} Nothing was saved.",
                           outcome=e.outcome, plain=f"The CRM changed since the read back: {e.plain} Nothing was saved.",
                           **e.extra) from e
        if again != write["changes"]:
            raise CRMError("stale", "The CRM changed since the read back. Nothing was saved. Propose it again.",
                           plain="The CRM changed since the read back. Nothing was saved.")

    def _check_all(self, inputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Check each change against the CRM as it would be after the earlier changes of the same
        write, so two creates of one contact, "Acme" and "Acme Inc", or an update and a create to
        the same email are caught inside one write. A record may be changed once per write."""
        sim = CRM(self.today, self.confirm, self.user, self.clock, copy.deepcopy(self.records), counters=dict(self.counters))
        changed: set[str] = set()
        out = []
        for raw in inputs:
            c = sim._normalize(raw)
            target = c.get("contact_id") if c["op"] == "update_contact" else c.get("deal_id") if c["op"] == "update_deal_stage" \
                else None
            if target in changed:
                raise CRMError("invalid", f"{target} is changed twice in one write. Make one change per record.",
                               plain="One record is changed twice in the same write. Nothing was proposed.")
            if target:
                changed.add(target)
            sim._apply(c, "W-check")
            out.append(c)
        return out

    # ------------------------------------------------------------------ checking one change
    def _input(self, raw: Any) -> dict[str, Any]:
        """Keep the fields a change may carry. A value that is empty once cleaned (spaces, zero
        width characters) counts as not given, so a required field cannot be blank."""
        if not isinstance(raw, dict):
            raise CRMError("invalid", "Each change must be an object with an op.")
        op = raw.get("op")
        if not isinstance(op, str) or op not in OPS:
            raise CRMError("invalid", f"Unknown op {op!r}. Use one of: {', '.join(OPS)}.")
        required, optional = OPS[op]
        out: dict[str, Any] = {"op": op}
        extra = []
        for key in sorted(k for k in raw if k != "op"):
            value = raw[key]
            if value is None or value == "" or value == []:
                continue
            if key not in required | optional:
                extra.append(key)
            elif key in LIST_FIELDS:
                if not isinstance(value, list) or len(value) > MAX_LIST:
                    raise CRMError("invalid", f"{key} must be a list of at most {MAX_LIST} short items.")
                items = [v for v in (_text(v, key, LIMITS["item"]) for v in value) if v]
                if items:
                    out[key] = items
            else:
                cleaned = _text(value, key, LIMITS.get(key, 40))
                if cleaned and (key not in required or has_letter_or_digit(cleaned)):
                    out[key] = cleaned
        if extra:
            raise CRMError("invalid", f"{op} does not take {', '.join(extra)}.")
        missing = sorted(required - set(out))
        if missing:
            raise CRMError("invalid", f"{op} needs {', '.join(missing)} (an empty value, or one with no letter or digit, "
                                      "does not count).")
        return out

    def _normalize(self, c: dict[str, Any]) -> dict[str, Any]:
        op = c["op"]
        out = dict(c)
        if op == "create_note":
            contact = self._need(c["contact_id"], "C", "contact_id")
            company = c.get("company_id", contact["company_id"])
            self._need(company, "CO", "company_id")
            if company != contact["company_id"]:
                raise CRMError("invalid", f"{contact['name']} works at {self.companies[contact['company_id']]['name']}, "
                                          f"not {self.companies[company]['name']}.")
            out["company_id"] = company
            if c.get("deal_id"):
                deal = self._need(c["deal_id"], "D", "deal_id")
                if deal["company_id"] != company:
                    raise CRMError("invalid", f"{deal['id']} is a {self.companies[deal['company_id']]['name']} deal, not "
                                              f"{self.companies[company]['name']}.")
            if c.get("property_id"):
                self._need(c["property_id"], "P", "property_id")
            out.update(read_stated_time(c.get("stated_time_text"), self.today, "past").as_fields("stated_time"))
        elif op == "create_task":
            if c.get("contact_id"):
                self._need(c["contact_id"], "C", "contact_id")
            if c.get("deal_id"):
                self._need(c["deal_id"], "D", "deal_id")
            out.update(read_stated_time(c.get("due_text"), self.today, "future").as_fields("due"))
        elif op == "create_contact":
            self._need(c["company_id"], "CO", "company_id")
            _one_alphabet(c["first_name"], c["last_name"])
            out["email"] = email = c["email"].lower()
            if not EMAIL.match(email):
                raise CRMError("invalid", f"{c['email']} is not a valid email address.")
            match = self._duplicate_contact(email, c["first_name"], c["last_name"], c["company_id"])
            if match:
                raise CRMError("duplicate_contact", f"{match['name']} ({match['email']}) is already in the CRM as "
                                                    f"{match['id']}. Nothing new was created; update that contact instead.",
                               outcome="blocked", plain=f"{match['name']} is already in the CRM. Nothing new was created.",
                               match=self._brief("contact", match))
        elif op == "update_contact":
            contact = self._need(c["contact_id"], "C", "contact_id")
            if "email" not in c and "job_title" not in c:
                raise CRMError("invalid", "update_contact needs email or job_title.")
            if "email" in c:
                out["email"] = email = c["email"].lower()
                if not EMAIL.match(email):
                    raise CRMError("invalid", f"{c['email']} is not a valid email address.")
                other = next((x for x in self.contacts.values() if x["email"] == email and x["id"] != contact["id"]), None)
                if other:
                    raise CRMError("duplicate_contact", f"{email} already belongs to {other['name']} ({other['id']}).",
                                   outcome="blocked", plain=f"That email already belongs to {other['name']}. Nothing was "
                                                            "changed.", match=self._brief("contact", other))
            out["before"] = {k: contact[k] for k in ("email", "job_title") if k in c}
            if all(out[k] == contact[k] for k in out["before"]):
                raise CRMError("no_change", f"{contact['name']} already has those details.")
        elif op == "create_company":
            _one_alphabet(c["name"])
            key = company_key(c["name"])
            match = next((co for co in self.companies.values() if key and company_key(co["name"]) == key), None)
            if match:
                raise CRMError("duplicate_company", f"{match['name']} is already in the CRM as {match['id']}.",
                               outcome="blocked", plain=f"{match['name']} is already in the CRM. Nothing new was created.",
                               match=self._brief("company", match))
            # "Quillon" and "Quillon Logistics": maybe the same company. Not blocked, but flagged on the card.
            near = [co for co in self.companies.values() if len(key) >= 4 and len(company_key(co["name"])) >= 4
                    and (company_key(co["name"]).startswith(key) or key.startswith(company_key(co["name"])))]
            if near:
                out["similar_to"] = ", ".join(f"{co['name']} ({co['id']})" for co in near[:3])
        elif op == "update_deal_stage":
            deal = self._need(c["deal_id"], "D", "deal_id")
            stage = next((s for s in data.STAGES if s.lower() == c["stage"].lower()), None)
            if stage is None:
                raise CRMError("invalid", f"{c['stage']!r} is not a deal stage. Stages: {', '.join(data.STAGES)}.")
            if deal["stage"] == stage:
                raise CRMError("no_change", f"{deal['name']} is already at {stage}.")
            out["stage"] = stage
            out["before"] = {"stage": deal["stage"]}
            out.update(read_stated_time(c.get("stated_time_text"), self.today, "past").as_fields("stated_time"))
        return out

    def _duplicate_contact(self, email: str, first: str, last: str, company_id: str) -> dict[str, Any] | None:
        name = (name_key(first), name_key(last))   # letters and digits only: "Da-na" is "Dana"
        for x in self.contacts.values():
            if x["email"] == email:
                return x
            if all(name) and (name_key(x["first_name"]), name_key(x["last_name"])) == name and x["company_id"] == company_id:
                return x
        return None

    # ------------------------------------------------------------------ applying a confirmed write
    def _apply(self, c: dict[str, Any], write_id: str) -> dict[str, Any]:
        now = self.now()
        op = c["op"]
        base = {"recorded_at": now, "logged_by": self.user, "write_id": write_id}
        if op == "create_note":
            rec = {"id": self._next("N"), "contact_id": c["contact_id"], "company_id": c["company_id"],
                   "deal_id": c.get("deal_id"), "property_id": c.get("property_id"), "summary": c["summary"],
                   "discussed": c.get("discussed", []), "next_steps": c.get("next_steps", []),
                   "stated_time_text": c["stated_time_text"], "stated_time": c["stated_time"],
                   "stated_time_note": c["stated_time_note"], "stated_time_warning": c["stated_time_warning"], **base}
            self.records["notes"][rec["id"]] = rec
            if rec["deal_id"]:
                self.deals[rec["deal_id"]]["last_activity"] = self.clock().date().isoformat()
            return {"id": rec["id"], "kind": "note", "label": rec["summary"]}
        if op == "create_task":
            rec = {"id": self._next("T"), "title": c["title"], "contact_id": c.get("contact_id"), "deal_id": c.get("deal_id"),
                   "status": "open", "due_text": c["due_text"], "due": c["due"], "due_note": c["due_note"],
                   "due_warning": c["due_warning"], **base}
            self.records["tasks"][rec["id"]] = rec
            return {"id": rec["id"], "kind": "task", "label": rec["title"]}
        if op == "create_contact":
            rec = {"id": self._next("C"), "first_name": c["first_name"], "last_name": c["last_name"],
                   "name": f"{c['first_name']} {c['last_name']}", "email": c["email"], "job_title": c.get("job_title", ""),
                   "company_id": c["company_id"], **base}
            self.contacts[rec["id"]] = rec
            return {"id": rec["id"], "kind": "contact", "label": rec["name"]}
        if op == "update_contact":
            rec = self.contacts[c["contact_id"]]
            for key in c["before"]:
                rec[key] = c[key]
            rec["updated_at"], rec["updated_by"] = now, self.user
            return {"id": rec["id"], "kind": "contact", "label": f"{rec['name']}: " + ", ".join(
                f"{k.replace('_', ' ')} {c['before'][k] or 'none'} -> {c[k]}" for k in c["before"])}
        if op == "create_company":
            rec = {"id": self._next("CO"), "name": c["name"], "industry": c.get("industry", ""), **base}
            self.companies[rec["id"]] = rec
            return {"id": rec["id"], "kind": "company", "label": rec["name"]}
        deal = self.deals[c["deal_id"]]
        deal.update(stage=c["stage"], stage_changed_at=now, stage_changed_by=self.user, last_activity=self.clock().date().isoformat(),
                    stage_stated_time_text=c["stated_time_text"], stage_stated_time=c["stated_time"],
                    stage_stated_time_note=c["stated_time_note"], stage_stated_time_warning=c["stated_time_warning"])
        return {"id": deal["id"], "kind": "deal", "label": f"{deal['name']}: {c['before']['stage']} -> {c['stage']}"}

    # ------------------------------------------------------------------ the read back, in plain words
    def readback(self, write: dict[str, Any]) -> list[dict[str, Any]]:
        """What a write will record, change by change, for the page's read back card."""
        out = []
        for c in write["changes"]:
            op = c["op"]
            item: dict[str, Any] = {"op": op, "rows": [], "lists": [], "time": None}
            if op == "create_note":
                item["heading"] = "Note"
                item["rows"] = [["Summary", c["summary"]], ["Contact", self.label(c["contact_id"])]]
                if c.get("property_id"):
                    item["rows"].append(["Property", self.label(c["property_id"])])
                if c.get("deal_id"):
                    item["rows"].append(["Deal", self.label(c["deal_id"])])
                item["lists"] = [[k, c[key]] for k, key in (("What was discussed", "discussed"), ("Next steps", "next_steps"))
                                 if c.get(key)]
                item["time"] = _time_view("When it happened", c, "stated_time")
            elif op == "create_task":
                item["heading"] = "Task"
                item["rows"] = [["Task", c["title"]],
                                ["For", self.label(c["contact_id"]) if c.get("contact_id") else "no contact"],
                                ["Deal", self.label(c["deal_id"]) if c.get("deal_id") else "no deal"]]
                item["time"] = _time_view("Due", c, "due")
            elif op == "create_contact":
                item["heading"] = "New contact"
                item["rows"] = [["Name", f"{c['first_name']} {c['last_name']}"], ["Email", c["email"]],
                                ["Company", self.label(c["company_id"])]] + ([["Job title", c["job_title"]]] if c.get("job_title") else [])
            elif op == "update_contact":
                item["heading"] = "Contact update"
                item["rows"] = [["Contact", self.label(c["contact_id"])]] + [
                    [k.replace("_", " ").capitalize(), f"{c['before'][k] or 'none'} -> {c[k]}"] for k in c["before"]]
            elif op == "create_company":
                item["heading"] = "New company"
                item["rows"] = [["Name", c["name"]]] + ([["Industry", c["industry"]]] if c.get("industry") else []) + \
                    ([["Looks like", c["similar_to"]]] if c.get("similar_to") else [])
            else:
                item["heading"] = "Deal stage"
                deal = self.deals[c["deal_id"]]
                item["rows"] = [["Deal", deal["name"]], ["Contact", self.label(deal["contact_id"])],
                                ["Stage", f"{c['before']['stage']} -> {c['stage']}"]]
                if c.get("stated_time_text"):
                    item["time"] = _time_view("When it happened", c, "stated_time")
            out.append(item)
        return out


def _counted(saved: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for s in saved:
        counts[s["kind"]] = counts.get(s["kind"], 0) + 1
    return " and ".join(f"{n} {kind}{'' if n == 1 else 's'}" for kind, n in counts.items())


def _one_alphabet(*names: str) -> None:
    for name in names:
        word = mixed_script(name)
        if word:
            raise CRMError("invalid", f"'{word}' mixes letters from different alphabets, which usually means a lookalike "
                                      "character. Ask the person to type the name again.",
                           plain=f"'{word}' mixes letters from different alphabets. Nothing was proposed.")


def _text_block(value: Any) -> str:
    if not isinstance(value, str):
        raise CRMError("invalid", "body must be text.")
    value = strip_control(value).strip()
    if len(value) > 4000:
        raise CRMError("invalid", "body is too long (at most 4000 characters).")
    return value


def _flags(changes: list[dict[str, Any]]) -> list[str]:
    """Everything the person should check: a time kept as words, and a date that looks odd."""
    flags = []
    for c in changes:
        if c.get("similar_to"):
            flags.append(f"'{c['name']}' looks like {c['similar_to']}, already in the CRM. Check it is not the same company.")
        for prefix in ("stated_time", "due"):
            for kind in ("note", "warning"):
                said = c.get(f"{prefix}_{kind}")
                if said:
                    flags.append(f"'{c[prefix + '_text']}': {said}")
    return flags


def _time_view(label: str, c: dict[str, Any], prefix: str) -> dict[str, Any]:
    return {"label": label, "text": c.get(f"{prefix}_text"), "value": c.get(prefix), "nice": nice(c.get(prefix)),
            "note": c.get(f"{prefix}_note"), "warning": c.get(f"{prefix}_warning")}
