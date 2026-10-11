"""The fixed rules (no AI): the demo story, the suggested messages and close variations. They use
the same tools as Claude, so every CRM rule applies to them too."""
from __future__ import annotations

import pytest
from conftest import Chat, story_texts

from teamos.guided import classify, find_time, read_debrief, sentences

STORY = story_texts()


def test_the_story_end_to_end(chat):
    chat.say(STORY["voice_note"])
    reply = chat.reply()
    assert reply["mode"] == "guided" and reply["skills"] == ["house-rules", "voice-note-debrief"]
    assert "Nothing is saved yet" in reply["text"] and '"yesterday afternoon" (kept as your words' in reply["text"]
    changes = chat.view["pending"][0]["changes"]
    note, *tasks = changes
    assert (note["contact_id"], note["deal_id"], note["property_id"]) == ("C-5", "D-3", "P-5")
    assert note["stated_time_text"] == "yesterday afternoon" and note["stated_time"] is None
    assert note["discussed"] == ["He liked the lab benches and the loading dock, but he's worried the HVAC can't handle their freezers",
                                 "They want to move in by March"]
    assert [t["title"] for t in tasks] == ["Send Marcus the HVAC specs", "Set up a second tour with their CFO", "Follow up with Marcus"]
    assert [t["due"] for t in tasks] == [None, None, "2026-10-23"]

    chat.confirm()
    assert chat.view["metrics"]["writes_saved"] == 1 and len(chat.view["saved"]) == 4

    chat.say(STORY["gate"])
    assert "Every write needs your confirm" in chat.reply()["text"] and chat.view["pending"][0]["summary"] == "Call with Ravi Menon"
    chat.do({"type": "test", "test": "commit_without_confirm"})
    assert chat.view["transcript"][-1]["refused"] and chat.view["metrics"]["writes_saved"] == 1

    chat.say(STORY["ambiguity"])
    assert "Dana Whitlock (Quillon Logistics) or Dana Okafor (Bramblecote Foods)" in chat.reply()["text"]
    assert chat.reply()["skills"] == ["crm-update"] and chat.view["metrics"]["writes_proposed"] == 2

    chat.say(STORY["off_topic"])
    assert chat.reply()["skills"] == [] and chat.reply()["steps"] == [] and "No skill fits" in chat.reply()["text"]
    assert chat.view["skills_used"] == ["house-rules", "voice-note-debrief", "crm-update"]


def test_an_answer_to_which_dana_finishes_the_change(chat):
    chat.say("Update Dana's deal to LOI signed.")
    chat.say("The Bramblecote one")
    change = chat.view["pending"][0]["changes"][0]
    assert change == {"op": "update_deal_stage", "deal_id": "D-2", "stage": "LOI signed", "before": {"stage": "Proposal sent"},
                      "stated_time_text": None, "stated_time": None, "stated_time_note": None}


def test_a_new_question_after_which_dana_is_not_taken_as_the_answer(chat):
    chat.say("Update Dana's deal to LOI signed.")
    chat.say("What's a good lunch spot near the Elm St warehouse?")
    assert chat.reply()["steps"] == [] and not chat.view["pending"]


def test_a_typed_yes_is_not_a_confirm(chat):
    chat.say(STORY["voice_note"])
    chat.say("yes, save it")
    assert "press Confirm" in chat.reply()["text"] and chat.view["metrics"]["writes_saved"] == 0


def test_duplicates_are_reported_not_created(chat):
    chat.say("Add a new contact: Dana Whitlock, dana.whitlock@example.com, at Quillon Logistics.")
    assert "already in the CRM" in chat.reply()["text"] and chat.view["metrics"]["writes_proposed"] == 0


def test_a_new_contact_needs_an_email_and_never_gets_one_made_up(chat):
    chat.say("Add a new contact: Nora Quist at Kilnworth Brewing.")
    assert "won't make one up" in chat.reply()["text"] and not chat.view["pending"]
    chat.say("Add a new contact: Nora Quist, nora.quist@example.com, at Kilnworth Brewing.")
    assert chat.view["pending"][0]["changes"][0]["company_id"] == "CO-5"


def test_email_is_a_draft_and_never_sent(chat):
    chat.say("Draft a follow up email to Ravi Menon and send it right away.")
    assert chat.view["drafts"][0]["status"] == "draft" and "can't send email" in chat.reply()["text"]
    assert chat.reply()["skills"] == ["house-rules", "follow-up-email"]


def test_meeting_prep_and_pipeline_only_read(chat):
    chat.say("Prep me for tomorrow's tour with Dana Whitlock.")
    assert "Second tour: 14 Elm Street with Dana Whitlock, tomorrow" in chat.reply()["text"]
    chat.say("Give me the weekly pipeline summary.")
    text = chat.reply()["text"]
    assert "6 open deals" in text and "Kilnworth Brewing at 14 Elm Street (Lead, Alex Moreno): 38 days" in text
    assert chat.view["metrics"]["writes_proposed"] == 0


def test_my_pipeline_filters_by_the_signed_in_broker():
    chat = Chat(broker="B-4")
    chat.say("What's in my pipeline?")
    assert "2 open deals" in chat.reply()["text"]


@pytest.mark.parametrize("text, family", [
    ("Just left the coffee with Hana Sato. She wants more time.", "debrief"),
    ("Brief me before my call with Marcus Bell.", "prep"),
    ("Change Hana Sato's email to hana@example.com", "update"),
    ("Move the Pellucid deal to Closed won.", "update"),
    ("Email Dana Okafor a recap.", "email"),
    ("Which deals are stale?", "pipeline"),
    ("How should we log times in the CRM?", "rules"),
    ("What does LOI mean in commercial leasing?", None),
    ("Any tips for recording a good voice note on my phone?", None),
    ("What is a sales pipeline?", None),
    ("How do I prepare for a job interview?", None),
])
def test_the_fixed_rules_pick_a_skill_family(text, family):
    assert classify(text) == family


def test_reading_a_note_keeps_words_and_never_dates():
    contact = {"first_name": "Marcus", "last_name": "Bell", "name": "Marcus Bell"}
    d = read_debrief(STORY["voice_note"], contact, "310 Canal Street")
    assert d.stated == "yesterday afternoon" and d.summary == "Tour of 310 Canal Street with Marcus Bell"
    assert find_time("Follow up on Fri, Oct. 23, 2026 at 3 pm.") == "Fri, Oct. 23, 2026 at 3 pm"
    assert find_time("No time here.") is None
    assert sentences("Walked 14 Elm St. He liked it. Meet Oct. 23, 2026.") == ["Walked 14 Elm St.", "He liked it.",
                                                                              "Meet Oct. 23, 2026."]
