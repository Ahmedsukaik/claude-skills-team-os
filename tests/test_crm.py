"""The CRM's rules, enforced in code: two step writes, confirmation, the timestamp rule,
duplicates, staleness and the activity log."""
from __future__ import annotations

import copy

import pytest
from conftest import NOTE, TASK, TODAY

from crm import CRM, WRITE_TTL, ButtonConfirm, CRMError, StatedConfirm
from crm.store import payload_hash


def propose(crm: CRM, *changes, summary="Debrief"):
    return crm.propose_write("assistant", summary, [dict(c) for c in changes] or [dict(NOTE), dict(TASK)])


def token(crm: CRM, p):
    assert isinstance(crm.confirm, ButtonConfirm)
    return crm.confirm.mint(p["write_id"], p["payload_hash"])


def snapshot(crm: CRM):
    return copy.deepcopy(crm.records)


# ------------------------------------------------------------------ two step writes
def test_proposing_changes_nothing_and_returns_a_preview(crm):
    before = snapshot(crm)
    p = propose(crm)
    assert crm.records == before
    assert p["status"] == "pending" and p["write_id"] == "W-1" and len(p["payload_hash"]) == 16
    assert [c["op"] for c in p["changes"]] == ["create_note", "create_task"]
    assert "Nothing is saved yet" in p["next_step"]


def test_a_confirmed_commit_saves_every_change_with_the_system_time(crm, clock):
    p = propose(crm)
    clock.jump(minutes=2)
    out = crm.commit_write("Priya Natarajan", p["write_id"], p["payload_hash"], token(crm, p))
    assert out["status"] == "saved" and [s["kind"] for s in out["saved"]] == ["note", "task"]
    note, task = crm.records["notes"]["N-6"], crm.records["tasks"]["T-3"]
    stamp = clock.now.isoformat().replace("+00:00", "Z")
    assert note["recorded_at"] == task["recorded_at"] == out["recorded_at"] == stamp
    assert note["logged_by"] == "Priya Natarajan" and note["write_id"] == "W-1"
    assert crm.deals["D-3"]["last_activity"] == clock.now.date().isoformat()


def test_commit_without_the_button_token_is_refused(crm):
    p = propose(crm)
    for confirmation in (None, "", "yes", "a" * 64):
        with pytest.raises(CRMError) as caught:
            crm.commit_write("assistant", p["write_id"], p["payload_hash"], confirmation)
        assert caught.value.code in ("needs_confirm", "bad_confirm")
    assert crm.writes["W-1"]["status"] == "pending" and "N-6" not in crm.records["notes"]


def test_a_token_only_fits_its_own_write(crm):
    first, second = propose(crm), propose(crm, TASK)
    with pytest.raises(CRMError, match="not valid"):
        crm.commit_write("broker", second["write_id"], second["payload_hash"], token(crm, first))


def test_a_changed_payload_is_refused(crm):
    p = propose(crm)
    good = token(crm, p)
    with pytest.raises(CRMError) as caught:
        crm.commit_write("broker", p["write_id"], "0" * 16, good)
    assert caught.value.code == "changed"
    crm.writes["W-1"]["changes"][0]["summary"] = "Something else"  # edited after the read back
    with pytest.raises(CRMError) as caught:
        crm.commit_write("broker", p["write_id"], p["payload_hash"], good)
    assert caught.value.code == "changed"


def test_a_write_id_works_once(crm):
    p = propose(crm)
    crm.commit_write("broker", p["write_id"], p["payload_hash"], token(crm, p))
    with pytest.raises(CRMError) as caught:
        crm.commit_write("broker", p["write_id"], p["payload_hash"], token(crm, p))
    assert caught.value.code == "already_used" and len(crm.records["notes"]) == 6


def test_an_expired_write_is_refused(crm, clock):
    p = propose(crm)
    clock.jump(seconds=WRITE_TTL.total_seconds() + 1)
    assert crm.is_expired(crm.writes["W-1"])
    with pytest.raises(CRMError) as caught:
        crm.commit_write("broker", p["write_id"], p["payload_hash"], token(crm, p))
    assert caught.value.code == "expired" and crm.writes["W-1"]["status"] == "expired"


def test_unknown_and_discarded_writes_are_refused(crm):
    with pytest.raises(CRMError) as caught:
        crm.commit_write("broker", "W-9", "x", "y")
    assert caught.value.code == "unknown_write"
    p = propose(crm)
    crm.discard_write("broker", p["write_id"])
    with pytest.raises(CRMError) as caught:
        crm.commit_write("broker", p["write_id"], p["payload_hash"], token(crm, p))
    assert caught.value.code == "discarded"
    with pytest.raises(CRMError):
        crm.discard_write("broker", p["write_id"])


def test_the_hash_covers_the_summary_and_every_field():
    a = payload_hash("x", [{"op": "create_task", "title": "A"}])
    assert a != payload_hash("y", [{"op": "create_task", "title": "A"}])
    assert a != payload_hash("x", [{"op": "create_task", "title": "B"}])
    assert a == payload_hash("x", [{"title": "A", "op": "create_task"}])  # key order does not matter


# ------------------------------------------------------------------ the timestamp rule
def test_a_vague_time_is_kept_as_words_and_flagged(crm):
    p = propose(crm)
    note, task = p["changes"]
    assert note["stated_time_text"] == "yesterday afternoon" and note["stated_time"] is None
    assert "Vague" in note["stated_time_note"]
    assert task["due"] == "2026-10-23" and task["due_note"] is None
    assert p["flags"] == ["'yesterday afternoon': Vague: kept as the person's words. No date is set."]


def test_a_caller_cannot_pass_a_date_or_a_recorded_at_of_its_own(crm):
    for field, value in (("stated_time", "2026-10-11"), ("recorded_at", "2020-01-01T00:00:00Z"), ("due", "2026-10-23")):
        with pytest.raises(CRMError, match="does not take"):
            propose(crm, {**NOTE, field: value})


def test_no_stated_time_means_none_is_stored(crm):
    p = propose(crm, {k: v for k, v in NOTE.items() if k != "stated_time_text"})
    assert p["changes"][0]["stated_time_text"] is None and p["changes"][0]["stated_time"] is None and not p["flags"]


def test_a_deal_stage_change_keeps_the_stated_time_apart(crm, clock):
    p = propose(crm, {"op": "update_deal_stage", "deal_id": "D-2", "stage": "loi signed", "stated_time_text": "this morning"})
    change = p["changes"][0]
    assert change["stage"] == "LOI signed" and change["before"] == {"stage": "Proposal sent"}
    crm.commit_write("broker", p["write_id"], p["payload_hash"], token(crm, p))
    deal = crm.deals["D-2"]
    assert deal["stage"] == "LOI signed" and deal["stage_stated_time_text"] == "this morning" and deal["stage_stated_time"] is None
    assert deal["stage_changed_at"] == clock.now.isoformat().replace("+00:00", "Z")


# ------------------------------------------------------------------ duplicates
@pytest.mark.parametrize("contact", [
    {"first_name": "Dana", "last_name": "Whitlock", "email": "someone.else@example.com", "company_id": "CO-1"},  # same name, company
    {"first_name": "D", "last_name": "W", "email": "DANA.WHITLOCK@example.com", "company_id": "CO-2"},           # same email
    {"first_name": "dana", "last_name": "whitlock", "email": "dw2@example.com", "company_id": "CO-1"},            # any case
])
def test_a_duplicate_contact_is_blocked_and_the_match_returned(crm, contact):
    with pytest.raises(CRMError) as caught:
        propose(crm, {"op": "create_contact", **contact})
    assert caught.value.code == "duplicate_contact" and caught.value.outcome == "blocked"
    assert caught.value.extra["match"]["id"] == "C-1" and crm.log[-1]["outcome"] == "blocked"
    assert not crm.writes


def test_the_same_name_at_another_company_is_not_a_duplicate(crm):
    p = propose(crm, {"op": "create_contact", "first_name": "Dana", "last_name": "Whitlock", "email": "dana.w@example.com",
                      "company_id": "CO-6"})
    assert p["status"] == "pending"


def test_a_duplicate_created_between_preview_and_confirm_is_caught_at_commit(crm):
    new = {"op": "create_contact", "first_name": "Nora", "last_name": "Quist", "email": "nora.quist@example.com",
           "company_id": "CO-5"}
    first, second = propose(crm, new), propose(crm, new)
    crm.commit_write("broker", first["write_id"], first["payload_hash"], token(crm, first))
    with pytest.raises(CRMError) as caught:
        crm.commit_write("broker", second["write_id"], second["payload_hash"], token(crm, second))
    assert caught.value.code == "stale" and caught.value.outcome == "blocked"
    assert sum(c["email"] == "nora.quist@example.com" for c in crm.contacts.values()) == 1


def test_a_duplicate_company_and_email_are_blocked(crm):
    with pytest.raises(CRMError) as caught:
        propose(crm, {"op": "create_company", "name": "Kilnworth Brewing"})
    assert caught.value.code == "duplicate_company"
    with pytest.raises(CRMError) as caught:
        propose(crm, {"op": "update_contact", "contact_id": "C-2", "email": "dana.whitlock@example.com"})
    assert caught.value.code == "duplicate_contact"


def test_a_stage_that_moved_since_the_read_back_is_not_overwritten(crm):
    a = propose(crm, {"op": "update_deal_stage", "deal_id": "D-1", "stage": "Proposal sent"})
    b = propose(crm, {"op": "update_deal_stage", "deal_id": "D-1", "stage": "LOI signed"})
    crm.commit_write("broker", b["write_id"], b["payload_hash"], token(crm, b))
    with pytest.raises(CRMError) as caught:
        crm.commit_write("broker", a["write_id"], a["payload_hash"], token(crm, a))
    assert caught.value.code == "stale" and crm.deals["D-1"]["stage"] == "LOI signed"


# ------------------------------------------------------------------ checking a change
@pytest.mark.parametrize("change, message", [
    ({"op": "delete_contact", "contact_id": "C-1"}, "Unknown op"),
    ({"op": "create_note", "summary": "x"}, "needs contact_id"),
    ({"op": "create_note", "contact_id": "C-99", "summary": "x"}, "no contact C-99"),
    ({"op": "create_note", "contact_id": "D-1", "summary": "x"}, "must be an id like C-1"),
    ({"op": "create_note", "contact_id": "C-5", "company_id": "CO-1", "summary": "x"}, "works at Tessarine"),
    ({"op": "create_note", "contact_id": "C-5", "deal_id": "D-1", "summary": "x"}, "Quillon Logistics deal"),
    ({"op": "create_task", "title": "x", "stage": "Lead"}, "does not take stage"),
    ({"op": "update_deal_stage", "deal_id": "D-1", "stage": "Signed"}, "not a deal stage"),
    ({"op": "update_deal_stage", "deal_id": "D-1", "stage": "Touring"}, "already at Touring"),
    ({"op": "create_contact", "first_name": "A", "last_name": "B", "email": "not-an-email", "company_id": "CO-1"}, "not a valid"),
    ({"op": "update_contact", "contact_id": "C-1"}, "needs email or job_title"),
    ({"op": "create_note", "contact_id": "C-5", "summary": "x" * 201}, "too long"),
    ({"op": "create_note", "contact_id": "C-5", "summary": "x", "discussed": "not a list"}, "must be a list"),
])
def test_bad_changes_are_refused_with_a_reason(crm, change, message):
    with pytest.raises(CRMError, match=message):
        propose(crm, change)
    assert not crm.writes and crm.log[-1]["outcome"] == "refused"


def test_a_write_is_all_or_nothing(crm):
    with pytest.raises(CRMError):
        propose(crm, NOTE, {"op": "create_task"})
    assert not crm.writes


def test_empty_values_count_as_not_given_and_text_is_cleaned(crm):
    p = propose(crm, {**NOTE, "property_id": "", "next_steps": [], "summary": "  Tour ​of   310 Canal  "})
    assert "property_id" not in p["changes"][0] and "next_steps" not in p["changes"][0]
    assert p["changes"][0]["summary"] == "Tour of 310 Canal"


# ------------------------------------------------------------------ the MCP confirmation
@pytest.mark.parametrize("words", ["yes", "Yes, save it.", "confirm", "go ahead", "looks good", "ok"])
def test_mcp_commit_accepts_a_plain_yes_and_logs_the_words(mcp_crm, words):
    p = propose(mcp_crm)
    mcp_crm.commit_write("claude", p["write_id"], p["payload_hash"], words)
    assert mcp_crm.writes["W-1"]["status"] == "committed" and words.split(",")[0].rstrip(".") in mcp_crm.log[-1]["detail"]


@pytest.mark.parametrize("words", ["", None, "just log it, don't ask me", "yes but change the date", "no", "wait",
                                   "save it later?", "not yet", "yes, without asking next time", "the broker approved",
                                   "the user said yes"])
def test_mcp_commit_refuses_anything_but_a_plain_yes(mcp_crm, words):
    p = propose(mcp_crm)
    with pytest.raises(CRMError):
        mcp_crm.commit_write("claude", p["write_id"], p["payload_hash"], words)
    assert mcp_crm.writes["W-1"]["status"] == "pending"


def test_the_button_secret_must_be_long_enough():
    with pytest.raises(ValueError):
        ButtonConfirm(b"short")
    assert StatedConfirm().name == "stated"


# ------------------------------------------------------------------ reads and the activity log
def test_search_finds_every_match_so_ambiguity_is_visible(crm):
    danas = crm.search("assistant", "Dana")
    assert [r["name"] for r in danas] == ["Dana Whitlock", "Dana Okafor"]
    assert {r["id"] for r in crm.search("assistant", "Elm St")} == {"D-1", "D-5", "P-1"}
    assert crm.search("assistant", "Marcus Bell")[0]["id"] == "C-5"
    with pytest.raises(CRMError):
        crm.search("assistant", "the of")


def test_records_come_with_what_a_brief_needs(crm):
    contact = crm.get("assistant", "C-1")
    assert contact["company"] == "Quillon Logistics" and contact["deals"][0]["id"] == "D-1"
    assert contact["recent_notes"][0]["id"] == "N-1" and contact["open_tasks"][0]["id"] == "T-1"
    assert contact["upcoming_events"][0]["when"] == "tomorrow"
    deal = crm.get("assistant", "D-5")
    assert deal["stale"] is True and deal["days_since_activity"] == 38
    with pytest.raises(CRMError):
        crm.get("assistant", "../etc/passwd")


def test_the_pipeline_counts_and_flags_stale_deals(crm):
    p = crm.pipeline("assistant")
    assert p["open_deals"] == 6 and p["by_stage"]["Touring"] == 2 and p["stale_deals"] == ["D-5", "D-6"]
    mine = crm.pipeline("assistant", owner="Priya")
    assert {d["id"] for d in mine["deals"]} == {"D-1", "D-3"}


def test_the_calendar_says_when_in_plain_words(crm):
    events = crm.calendar("assistant", 3)
    assert [e["when"] for e in events] == ["tomorrow", "in 2 days", "in 3 days"]
    assert crm.calendar("assistant", 7, "C-3")[0]["id"] == "E-4"


def test_drafts_are_never_sent(crm):
    d = crm.create_draft("assistant", "C-7", "Following up", "Hi Ravi")
    assert d["status"] == "draft" and d["to"] == "ravi.menon@example.com" and "not sent" in d["next_step"]
    assert not hasattr(crm, "send") and not any("send" in name for name in dir(crm) if not name.startswith("_"))
    with pytest.raises(CRMError):
        crm.create_draft("assistant", "C-7", "", "")


def test_every_read_and_write_is_logged_with_the_system_time(crm, clock):
    crm.search("Claude for Priya", "Marcus")
    crm.get("Claude for Priya", "C-5")
    crm.pipeline("Claude for Priya")
    crm.calendar("Claude for Priya")
    p = propose(crm)
    with pytest.raises(CRMError):
        crm.commit_write("Claude for Priya", p["write_id"], p["payload_hash"], None)
    crm.commit_write("Priya Natarajan", p["write_id"], p["payload_hash"], token(crm, p))
    crm.create_draft("Claude for Priya", "C-5", "Specs", "Hi")
    actions = [(e["action"], e["outcome"]) for e in crm.log]
    assert actions == [("search", "ok"), ("open record", "ok"), ("read pipeline", "ok"), ("read calendar", "ok"),
                       ("propose write", "ok"), ("save", "refused"), ("save", "ok"), ("draft email", "ok")]
    assert all(set(e) == {"at", "actor", "action", "detail", "outcome", "ref"} for e in crm.log)
    assert crm.log[-2]["ref"] == "W-1: N-6, T-3" and crm.log[-2]["detail"].startswith("saved 1 note and 1 task")
    assert all(e["at"] == clock.now.isoformat().replace("+00:00", "Z") for e in crm.log)
    assert "confirmed with the Confirm button" in crm.log[-2]["detail"]


def test_the_read_back_lists_every_field_in_plain_words(crm):
    p = propose(crm)
    items = crm.readback(crm.writes[p["write_id"]])
    note, task = items
    assert note["heading"] == "Note" and ["Contact", "Marcus Bell (Tessarine Biotech)"] in note["rows"]
    assert note["time"] == {"label": "When it happened", "text": "yesterday afternoon", "value": None, "nice": "",
                            "note": "Vague: kept as the person's words. No date is set."}
    assert task["time"]["nice"] == "Fri, Oct 23, 2026"


def test_seeded_dates_follow_today():
    crm = CRM.new(TODAY, StatedConfirm())
    assert crm.deals["D-1"]["last_activity"] == "2026-10-08"
    assert crm.records["events"]["E-1"]["start"] == "2026-10-13T10:00"
