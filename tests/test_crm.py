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
@pytest.mark.parametrize("words", ["yes", "Yes, save it.", "confirm", "go ahead", "looks good", "ok", "Yes please",
                                   "OK, go ahead", "that's right, save it"])
def test_mcp_commit_accepts_a_plain_yes_and_logs_the_words(mcp_crm, words):
    p = propose(mcp_crm)
    mcp_crm.commit_write("claude", p["write_id"], p["payload_hash"], words)
    assert mcp_crm.writes["W-1"]["status"] == "committed" and words.split(",")[0].rstrip(".") in mcp_crm.log[-1]["detail"]


@pytest.mark.parametrize("words", ["", None, "just log it, don't ask me", "yes but change the date", "no", "wait",
                                   "save it later?", "not yet", "yes, without asking next time", "the broker approved",
                                   "the user said yes", "save it later", "yes, and also add Hana", "Correct the email first",
                                   "Do it later", "OK let me check with my manager first", "Sure, after lunch",
                                   "yes " + "and " * 400 + "also add Hana", "ok " * 200 + "no"])
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
                            "note": "Vague: kept as the person's words. No date is set.", "warning": None}
    assert task["time"]["nice"] == "Fri, Oct 23, 2026"
    assert task["rows"] == [["Task", "Follow up with Marcus"], ["For", "Marcus Bell (Tessarine Biotech)"],
                            ["Deal", "Tessarine Biotech at 310 Canal Street (Touring)"]]


def test_the_read_back_keeps_a_warning_apart_from_an_exact_date(crm):
    p = propose(crm, {"op": "create_task", "title": "Send the floor plan", "due_text": "by October 1, 2026"})
    item = crm.readback(crm.writes[p["write_id"]])[0]
    assert item["time"]["value"] == "2026-10-01" and item["time"]["note"] is None and "already past" in item["time"]["warning"]
    assert any("deadline" in f for f in p["flags"])
    assert ["For", "no contact"] in item["rows"] and ["Deal", "no deal"] in item["rows"]


def test_seeded_dates_follow_today():
    crm = CRM.new(TODAY, StatedConfirm())
    assert crm.deals["D-1"]["last_activity"] == "2026-10-08"
    assert crm.records["events"]["E-1"]["start"] == "2026-10-13T10:00"


# ------------------------------------------------------------------ one write, checked as a whole
NEW_NORA = {"op": "create_contact", "first_name": "Nora", "last_name": "Quist", "email": "nora.quist@example.com",
            "company_id": "CO-5"}


@pytest.mark.parametrize("changes, code", [
    ([NEW_NORA, {**NEW_NORA, "first_name": "Norah", "email": "NORA.QUIST@example.com"}], "duplicate_contact"),  # case only
    ([{"op": "create_company", "name": "Acme"}, {"op": "create_company", "name": "Acme Inc"}], "duplicate_company"),
    ([{"op": "update_contact", "contact_id": "C-2", "email": "celia.b@example.com"},
      {**NEW_NORA, "email": "celia.b@example.com"}], "duplicate_contact"),
    ([NEW_NORA, {"op": "update_contact", "contact_id": "C-2", "email": "nora.quist@example.com"}], "duplicate_contact"),
    ([{"op": "update_deal_stage", "deal_id": "D-1", "stage": "Proposal sent"},
      {"op": "update_deal_stage", "deal_id": "D-1", "stage": "LOI signed"}], "invalid"),
    ([{"op": "update_contact", "contact_id": "C-2", "job_title": "Finance Director"},
      {"op": "update_contact", "contact_id": "C-2", "email": "celia.b@example.com"}], "invalid"),
])
def test_duplicates_inside_one_write_are_caught(crm, changes, code):
    with pytest.raises(CRMError) as caught:
        propose(crm, *changes)
    assert caught.value.code == code and not crm.writes


def test_a_write_with_different_records_still_goes_through(crm):
    p = propose(crm, NEW_NORA, {"op": "create_company", "name": "Fernway Pharmacy"},
                {"op": "update_deal_stage", "deal_id": "D-1", "stage": "Proposal sent"})
    assert p["status"] == "pending" and crm.counters["C"] == 12 and crm.counters["CO"] == 6  # the check did not touch the CRM
    crm.commit_write("broker", p["write_id"], p["payload_hash"], token(crm, p))
    assert crm.contacts["C-13"]["email"] == "nora.quist@example.com" and crm.companies["CO-7"]["name"] == "Fernway Pharmacy"


# ------------------------------------------------------------------ empty after cleaning
@pytest.mark.parametrize("change", [
    {**NOTE, "summary": "   "},
    {**NOTE, "summary": chr(0x200B) * 3},
    {**NOTE, "summary": chr(0x202E) + " " + chr(0xFEFF)},
    {"op": "create_task", "title": chr(0x2060) + "  "},
    {**NEW_NORA, "last_name": chr(0x200B)},
    {"op": "create_company", "name": " " + chr(0x2066) + chr(0x2069)},
])
def test_a_required_field_that_is_empty_once_cleaned_is_refused(crm, change):
    with pytest.raises(CRMError, match="an empty value, or one with no letter or digit, does not count"):
        propose(crm, change)


def test_empty_list_items_are_dropped(crm):
    p = propose(crm, {**NOTE, "discussed": [" ", chr(0x200B), "Liked the dock"]})
    assert p["changes"][0]["discussed"] == ["Liked the dock"]


# ------------------------------------------------------------------ names in any alphabet
def test_a_lookalike_letter_from_another_alphabet_is_refused(crm):
    lookalike = "D" + chr(0x0430) + "na"  # a Cyrillic a
    with pytest.raises(CRMError, match="different alphabets"):
        propose(crm, {**NEW_NORA, "first_name": lookalike, "last_name": "Whitlock", "email": "dw@example.com",
                      "company_id": "CO-1"})
    with pytest.raises(CRMError, match="different alphabets"):
        propose(crm, {"op": "create_company", "name": "Quill" + chr(0x043E) + "n Logistics"})  # a Cyrillic o


def test_accents_and_case_do_not_hide_a_duplicate(crm):
    for first, last in (("D" + chr(0xE1) + "na", "Whitlock"), ("DANA", "WHITLOCK"), ("Dana", "Whitlock" + chr(0x301))):
        with pytest.raises(CRMError) as caught:
            propose(crm, {**NEW_NORA, "first_name": first, "last_name": last, "email": "dana.w2@example.com",
                          "company_id": "CO-1"})
        assert caught.value.code == "duplicate_contact" and caught.value.extra["match"]["id"] == "C-1"


def test_names_in_other_scripts_are_compared_not_ignored(crm):
    arabic = (chr(0x0645) + chr(0x062D) + chr(0x0645) + chr(0x062F), chr(0x0639) + chr(0x0644) + chr(0x064A))
    cjk = (chr(0x738B), chr(0x82B3))
    first = propose(crm, {**NEW_NORA, "first_name": arabic[0], "last_name": arabic[1], "email": "m.ali@example.com"})
    crm.commit_write("broker", first["write_id"], first["payload_hash"], token(crm, first))
    second = propose(crm, {**NEW_NORA, "first_name": cjk[0], "last_name": cjk[1], "email": "wang.fang@example.com"})
    assert second["status"] == "pending"  # a different name in another script is not a duplicate
    with pytest.raises(CRMError) as caught:  # the same Arabic name at the same company is
        propose(crm, {**NEW_NORA, "first_name": arabic[0], "last_name": arabic[1], "email": "other@example.com"})
    assert caught.value.code == "duplicate_contact"
    assert crm.search("assistant", arabic[0])[0]["id"] == "C-13"


def test_errors_carry_plain_words_for_people(crm):
    p = propose(crm)
    with pytest.raises(CRMError) as caught:
        crm.commit_write("assistant", p["write_id"], p["payload_hash"], None)
    assert caught.value.plain == "Only the broker can save this, with Confirm. Nothing was saved."
    assert "Tell the broker" in caught.value.message and crm.log[-1]["detail"] == caught.value.plain



# ------------------------------------------------------------------ invisible characters and separators
INVISIBLE = [0x061C, 0x00AD, 0x034F, 0x180E, 0xE0041, 0xE007F, 0x3164, 0x115F, 0x2800, 0xFE0F, 0xE0100, 0x200B, 0x202E,
             0x2066, 0xFEFF]


@pytest.mark.parametrize("point", INVISIBLE, ids=[f"U+{p:04X}" for p in INVISIBLE])
def test_an_invisible_character_cannot_hide_a_duplicate(crm, point):
    with pytest.raises(CRMError) as caught:
        propose(crm, {**NEW_NORA, "first_name": "Da" + chr(point) + "na", "last_name": "Whitlock", "email": "dw2@example.com",
                      "company_id": "CO-1"})
    assert caught.value.code == "duplicate_contact" and caught.value.extra["match"]["id"] == "C-1"


@pytest.mark.parametrize("first", ["Da-na", "Da.na", "Da na", "Da" + chr(0x00AD) + "na", "DA_NA"])
def test_a_separator_cannot_split_a_name(crm, first):
    with pytest.raises(CRMError) as caught:
        propose(crm, {**NEW_NORA, "first_name": first, "last_name": "Whitlock", "email": "dw3@example.com", "company_id": "CO-1"})
    assert caught.value.code == "duplicate_contact"


@pytest.mark.parametrize("change", [
    {**NOTE, "summary": "..."},
    {**NOTE, "summary": chr(0x2800) * 4},
    {"op": "create_task", "title": "-- !!"},
    {**NEW_NORA, "last_name": chr(0x3164)},
    {"op": "create_company", "name": "&"},
])
def test_a_required_field_needs_a_letter_or_digit(crm, change):
    with pytest.raises(CRMError, match="no letter or digit"):
        propose(crm, change)


def test_invisible_characters_are_removed_from_saved_text(crm):
    p = propose(crm, {**NOTE, "summary": "Tour" + chr(0x00AD) + chr(0xE0041) + " of 310 Canal" + chr(0xFE0F)})
    assert p["changes"][0]["summary"] == "Tour of 310 Canal"


# ------------------------------------------------------------------ companies: suffixes and look-alikes
@pytest.mark.parametrize("name", ["Tessarine Biotech Ltd", "Tessarine Biotech Group", "TESSARINE BIOTECH, INC.",
                                  "Tessarine Biotech Corporation", "Tessarine Bio-tech GmbH"])
def test_a_company_suffix_does_not_make_a_new_company(crm, name):
    with pytest.raises(CRMError) as caught:
        propose(crm, {"op": "create_company", "name": name})
    assert caught.value.code == "duplicate_company" and caught.value.extra["match"]["name"] == "Tessarine Biotech"


def test_a_company_that_starts_like_another_is_flagged_on_the_card(crm):
    p = propose(crm, {"op": "create_company", "name": "Quillon"})
    assert p["changes"][0]["similar_to"] == "Quillon Logistics (CO-1)"
    assert any("looks like Quillon Logistics" in f for f in p["flags"])
    item = crm.readback(crm.writes[p["write_id"]])[0]
    assert ["Looks like", "Quillon Logistics (CO-1)"] in item["rows"]
    assert propose(crm, {"op": "create_company", "name": "Fernway Pharmacy"})["flags"] == []


def test_a_malformed_change_is_refused_not_a_crash(crm):
    for change in ({"op": ["create_note"]}, {"op": {"x": 1}}):
        with pytest.raises(CRMError, match="Unknown op"):
            propose(crm, change)


@pytest.mark.parametrize("words", ["yes?", "ok?", "ok \U0001F44D", "\U0001F44D", "please", "please.", "Please!",
                                   "yes; go ahead", "yes - go ahead", "ok :)", "yes...?", "yes (go ahead)"])
def test_only_a_plain_yes_with_plain_punctuation_counts(mcp_crm, words):
    p = propose(mcp_crm)
    with pytest.raises(CRMError) as caught:
        mcp_crm.commit_write("claude", p["write_id"], p["payload_hash"], words)
    assert caught.value.code in ("not_a_yes", "needs_confirm") and mcp_crm.writes["W-1"]["status"] == "pending"


@pytest.mark.parametrize("words", ["Yes, please!", "please, go ahead", "OK.", "that’s right, save it", "yes yes"])
def test_a_plain_yes_with_please_or_punctuation_counts(mcp_crm, words):
    p = propose(mcp_crm)
    mcp_crm.commit_write("claude", p["write_id"], p["payload_hash"], words)
    assert mcp_crm.writes["W-1"]["status"] == "committed"
