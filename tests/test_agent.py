"""The agent with a live model (scripted here): skills load through tools, the badge follows
what loaded, the CRM's rules hold whatever the model does, and the fixed rules take over when the
live model cannot answer."""
from __future__ import annotations

import json

import pytest
from conftest import Chat, ScriptedModel, last_tool_results, story_texts, text, tool

from teamos.agent import NOTES, Agent
from teamos.models import ModelUnavailable, Turn
from teamos.prompts import SYSTEM_PROMPT

NOTE = story_texts()["voice_note"]
FOLLOW_UP = "on " + NOTE.split(" on ")[-1].rstrip(".")  # with its "on": a cut date keeps its leading word
CHANGES = [{"op": "create_note", "contact_id": "C-5", "deal_id": "D-3", "property_id": "P-5",
            "summary": "Tour of 310 Canal Street with Marcus Bell", "discussed": ["Liked the loading dock"],
            "stated_time_text": "yesterday afternoon"},
           {"op": "create_task", "title": "Follow up with Marcus", "contact_id": "C-5", "due_text": FOLLOW_UP}]


def debrief_script(changes=None):
    return ScriptedModel(
        [tool(1, "load_skill", name="house-rules"), tool(2, "load_skill", name="voice-note-debrief")],
        [tool(3, "read_skill_file", skill="voice-note-debrief", path="references/debrief-fields.md"),
         tool(4, "search_crm", query="Marcus Bell"), tool(5, "search_crm", query="310 Canal Street")],
        [tool(6, "propose_write", summary="Tour of 310 Canal Street with Marcus Bell", changes=changes or CHANGES)],
        [text("Here is the debrief I will save. Nothing is saved yet. Press Confirm on the card to save it.")],
    )


def test_a_live_debrief_loads_skills_through_tools_one_step_per_request():
    model = debrief_script()
    chat = Chat(Agent(live=model))
    first = chat.do({"type": "broker", "text": NOTE})
    assert first["more"] and len(model.calls) == 1
    assert first["view"]["transcript"][-1]["kind"] == "working"
    assert first["view"]["transcript"][-1]["skills"] == ["house-rules", "voice-note-debrief"]
    while chat.last["more"]:
        chat.do({"type": "continue"})
    reply = chat.reply()
    assert len(model.calls) == 4 and reply["mode"] == "live" and reply["cost_usd"] > 0
    assert reply["skills"] == ["house-rules", "voice-note-debrief"]  # the badge: what the model loaded
    assert [s["label"] for s in reply["steps"]][:3] == ["Loaded the house-rules skill", "Loaded the voice-note-debrief skill",
                                                         "Read voice-note-debrief: references/debrief-fields.md"]
    assert chat.view["pending"][0]["changes"][0]["stated_time"] is None


def test_the_model_gets_the_skill_list_and_the_instructions_only_when_it_asks():
    model = debrief_script()
    Chat(Agent(live=model)).say(NOTE)
    assert model.systems[0] == SYSTEM_PROMPT and "<name>voice-note-debrief</name>" in SYSTEM_PROMPT
    assert "## Steps" not in json.dumps(model.calls[0])  # nothing of a SKILL.md body before load_skill
    loaded = last_tool_results(model.calls[1])
    body = json.loads(loaded[1]["content"])
    assert body["skill"] == "voice-note-debrief" and "## Steps" in body["instructions"]
    assert "references/debrief-fields.md" in body["files"]
    assert {t["name"] for t in model.tools[0]} >= {"load_skill", "read_skill_file", "propose_write", "commit_write"}


def test_tool_results_go_back_in_the_api_shape():
    model = debrief_script()
    Chat(Agent(live=model)).say(NOTE)
    roles = [m["role"] for m in model.calls[3]]
    assert roles == ["user", "assistant", "user", "assistant", "user", "assistant", "user"]
    results = last_tool_results(model.calls[3])
    assert results[0]["tool_use_id"] == "toolu_test_006" and "is_error" not in results[0]
    assert '"payload_hash"' in results[0]["content"]


def test_no_skill_loaded_shows_no_skill_used():
    model = ScriptedModel([text("I can only help with the firm's CRM work.")])
    chat = Chat(Agent(live=model))
    chat.say("What's a good lunch spot near the Elm St warehouse?")
    assert chat.reply()["skills"] == [] and chat.reply()["steps"] == [] and chat.reply()["skills_earlier"] == []


def test_a_write_before_the_house_rules_are_loaded_is_refused():
    model = ScriptedModel(
        [tool(1, "propose_write", summary="x", changes=CHANGES)],
        [tool(2, "load_skill", name="house-rules")],
        [tool(3, "propose_write", summary="x", changes=CHANGES)],
        [text("Read back ready.")])
    chat = Chat(Agent(live=model))
    chat.say(NOTE)
    first = json.loads(last_tool_results(model.calls[1])[0]["content"])
    assert first["error"] == "house_rules_not_loaded"
    assert [w["id"] for w in chat.view["pending"]] == ["W-1"]  # proposed once the rules were loaded


def test_a_date_the_model_worked_out_itself_is_refused():
    guessed = [dict(CHANGES[0], stated_time_text="October 11, 2026")]  # the broker said "yesterday afternoon"
    model = ScriptedModel([tool(1, "load_skill", name="house-rules")],
                          [tool(2, "propose_write", summary="x", changes=guessed)],
                          [text("Sorry.")])
    chat = Chat(Agent(live=model))
    chat.say(NOTE)
    error = json.loads(last_tool_results(model.calls[2])[0]["content"])
    assert error["error"] == "time_not_stated" and not chat.view["pending"]
    assert chat.view["log"][-1]["outcome"] == "refused"


def test_the_broker_words_may_differ_in_case_and_punctuation():
    loose = [dict(CHANGES[0], stated_time_text="Yesterday Afternoon"), dict(CHANGES[1], due_text=FOLLOW_UP.replace(",", ""))]
    model = debrief_script(loose)
    chat = Chat(Agent(live=model))
    chat.say(NOTE)
    assert chat.view["pending"] and chat.view["pending"][0]["changes"][1]["due"] == "2026-10-23"


def test_just_log_it_the_model_cannot_save_on_its_own():
    model = ScriptedModel(
        [tool(1, "load_skill", name="house-rules"), tool(2, "load_skill", name="voice-note-debrief")],
        [tool(3, "propose_write", summary="Call with Ravi", changes=[
            {"op": "create_note", "contact_id": "C-7", "summary": "Call with Ravi", "stated_time_text": "just now"}])],
        lambda msgs: [tool(4, "commit_write", write_id="W-1",
                           payload_hash=json.loads(last_tool_results(msgs)[0]["content"])["payload_hash"])],
        [text("The CRM needs your Confirm. The read back is on the card.")])
    chat = Chat(Agent(live=model))
    chat.say(story_texts()["gate"])
    refused = json.loads(last_tool_results(model.calls[3])[0]["content"])
    assert refused["error"] == "needs_confirm"
    assert chat.view["metrics"]["writes_saved"] == 0 and chat.view["pending"][0]["id"] == "W-1"
    assert chat.reply()["steps"][-1] == {"tool": "commit_write", "label": "Save refused: it needs the broker's Confirm",
                                         "ok": False, "outcome": "refused"}
    chat.confirm("W-1")  # only the broker's button saves it
    assert chat.view["metrics"]["writes_saved"] == 1


def test_the_story_test_uses_the_models_own_tool_path():
    chat = Chat()
    chat.say(story_texts()["gate"])
    chat.do({"type": "test", "test": "commit_without_confirm"})
    row = chat.view["transcript"][-1]
    assert row["kind"] == "test" and row["refused"] and "Only the broker can save" in row["result"]
    assert "Tell the broker" not in row["result"]
    assert chat.view["log"][-1]["actor"] == "Test (acting as the assistant)" and chat.view["metrics"]["saves_refused"] == 1


def test_the_model_learns_about_a_confirm_from_the_system_not_the_broker():
    model = debrief_script()
    model.turns.append([text("Saved. Anything else?")])
    chat = Chat(Agent(live=model))
    chat.say(NOTE)
    chat.confirm()
    chat.say("thanks")
    update = [b["text"] for b in model.calls[-1][-1]["content"] if b.get("type") == "text"]
    assert update[0].startswith("<crm_update>The broker pressed Confirm. W-1 was saved: N-6 (note), T-3 (task)")
    assert update[1] == "thanks"
    assert chat.reply()["skills"] == [] and chat.reply()["skills_earlier"] == []


def test_a_reply_that_reads_the_crm_without_a_new_skill_names_the_skills_already_loaded():
    model = debrief_script()
    model.turns += [[tool(7, "get_record", record_id="D-3")], [text("Touring.")]]
    chat = Chat(Agent(live=model))
    chat.say(NOTE)
    chat.say("What stage is that deal at?")
    assert chat.reply()["skills"] == [] and chat.reply()["skills_earlier"] == ["voice-note-debrief", "house-rules"]


@pytest.mark.parametrize("kind", ["budget", "rate_limited", "auth", "error", "invalid"])
def test_when_the_live_model_cannot_answer_the_fixed_rules_do_and_say_so(kind):
    model = ScriptedModel(ModelUnavailable(kind))
    agent = Agent(live=model)
    chat = Chat(agent)
    chat.say("Give me the weekly pipeline summary.")
    first_step = chat.session["events"][1]
    assert first_step["mode"] == "guided" and first_step["note"] == NOTES[kind] and "ixed rules" in NOTES[kind]
    assert [t["text"] for t in chat.view["transcript"] if t["kind"] == "system"] == [NOTES[kind]]
    if kind != "invalid":  # the service rests after a failure, so the whole reply comes from the fixed rules
        assert chat.reply()["mode"] == "guided" and chat.reply()["skills"] == ["house-rules", "weekly-pipeline"]
    assert agent.live_available() is False  # the live model rests after any failure, a refused request included


def test_a_visitor_over_the_limit_gets_the_fixed_rules():
    model = ScriptedModel([text("Hello from Claude.")])
    chat = Chat(Agent(live=model))
    chat.say("Give me the weekly pipeline summary.", allowed=False)
    assert chat.reply()["mode"] == "guided" and not model.calls
    assert NOTES["visitor_limit"] in [t["text"] for t in chat.view["transcript"] if t["kind"] == "system"]


def test_an_empty_or_cut_off_live_reply_is_handled():
    empty = ScriptedModel(Turn([], "end_turn", "claude-haiku-5-5", "live"))
    chat = Chat(Agent(live=empty))
    chat.say("hello")
    assert chat.reply()["mode"] == "guided"
    cut = ScriptedModel(Turn([text("Here is the deb")], "max_tokens", "claude-haiku-5-5", "live"))
    chat = Chat(Agent(live=cut))
    chat.say("hello")
    assert chat.reply()["problem"] == "the reply was cut off" and "Nothing was saved" in chat.reply()["text"]


def test_a_malformed_live_step_falls_back_to_the_fixed_rules():
    bad = ScriptedModel([tool(1, "drop_database")])  # a tool that does not exist
    chat = Chat(Agent(live=bad))
    chat.say("Give me the weekly pipeline summary.")
    assert chat.session["events"][1]["mode"] == "guided" and chat.session["events"][1]["note"] == NOTES["invalid"]
    assert not any(e.get("content", [{}])[0].get("name") == "drop_database" for e in chat.session["events"][1:])


def test_the_page_cannot_continue_a_finished_reply_or_send_while_working():
    from teamos.agent import ActionError
    chat = Chat(Agent(live=debrief_script()))
    chat.do({"type": "broker", "text": NOTE})
    with pytest.raises(ActionError, match="still working"):
        chat.do({"type": "broker", "text": "again"})
    with pytest.raises(ActionError, match="still working"):
        chat.do({"type": "confirm", "write_id": "W-1"})
    while chat.last["more"]:
        chat.do({"type": "continue"})
    with pytest.raises(ActionError, match="no reply in progress"):
        chat.do({"type": "continue"})
    with pytest.raises(ActionError):
        chat.do({"type": "fly"})


def test_cost_and_usage_add_up_over_the_chat():
    chat = Chat(Agent(live=debrief_script()))
    chat.say(NOTE)
    m = chat.view["metrics"]
    assert m["live_calls"] == 4 and m["guided_calls"] == 0 and m["cost_usd"] > 0
    assert m["input_tokens"] == 4 * (1500 + 4000) and m["cached_tokens"] == 4 * 4000 and m["avg_ms"] == 900


def test_a_date_cut_out_of_a_relative_phrase_is_refused():
    said = "Called Ravi Menon. Follow up two weeks after Friday, October 23, 2026."
    cut = [{"op": "create_task", "title": "Follow up with Ravi", "contact_id": "C-7", "due_text": "Friday, October 23, 2026"}]
    whole = [{**cut[0], "due_text": "two weeks after Friday, October 23, 2026"}]
    model = ScriptedModel([tool(1, "load_skill", name="house-rules")],
                          [tool(2, "propose_write", summary="x", changes=cut)],
                          [tool(3, "propose_write", summary="x", changes=whole)], [text("Read back ready.")])
    chat = Chat(Agent(live=model))
    chat.say(said)
    refused = json.loads(last_tool_results(model.calls[2])[0]["content"])
    assert refused["error"] == "time_not_stated" and "relative phrase" in refused["message"]
    due = chat.view["pending"][0]["changes"][0]
    assert due["due_text"] == "two weeks after Friday, October 23, 2026" and due["due"] is None  # kept as words


def test_failed_live_calls_are_logged_without_secrets(caplog):
    import anthropic
    import httpx2
    from conftest import free_port  # noqa: F401  (the same test helpers as the other files)

    from teamos.models import ClaudeModel

    response = httpx2.Response(400, headers={"request-id": "req_local_123"},
                               request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    error = anthropic.BadRequestError("messages.0: the prompt says SECRET-PROMPT-TEXT", response=response,
                                      body={"error": {"message": "the prompt says SECRET-PROMPT-TEXT"}})

    class Failing:
        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            raise error

    model = ClaudeModel(client=Failing())
    with caplog.at_level("WARNING", logger="teamos.models"), pytest.raises(ModelUnavailable):
        model.respond("system", [], [{"role": "user", "content": "hi"}])
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "kind=invalid" in logged and "status=400" in logged and "req_local_123" in logged
    assert "SECRET-PROMPT-TEXT" not in logged and "sk-" not in logged


@pytest.mark.parametrize("said, cut, why", [
    ("Send Ravi the plans by Friday, October 23, 2026.", "Friday, October 23, 2026", "missing its leading 'by'"),
    ("Follow up two weeks after the tour, which is Friday, October 23, 2026.", "Friday, October 23, 2026",
     "part of a relative phrase"),
    ("Sign it no later than October 30, 2026.", "October 30, 2026", "part of a relative phrase"),
])
def test_a_date_cut_out_of_a_longer_phrase_is_not_the_broker_words(said, cut, why):
    from teamos.tools import time_check
    assert why in (time_check(cut, [said]) or "")


def test_a_date_with_its_leading_word_is_the_broker_words_and_by_keeps_its_flag():
    from crm import CRM, StatedConfirm
    from teamos.tools import time_check
    said = "Send Ravi the plans by Friday, October 23, 2026."
    assert time_check("by Friday, October 23, 2026", [said]) is None
    assert time_check("Friday, October 23, 2026", ["Follow up with Ravi Menon, Friday, October 23, 2026."]) is None
    assert time_check("October 30, 2026", ["Follow up on October 30, 2026."]) is None   # a plain "on" may go
    assert time_check("October 30, 2026", ["The lease is due October 30, 2026."]) is None
    assert "relative phrase" in time_check("October 30, 2026", ["Sign it before October 30, 2026."])
    from datetime import date
    crm = CRM.new(date(2026, 10, 12), StatedConfirm())
    p = crm.propose_write("assistant", "x", [{"op": "create_task", "title": "Send the plans",
                                              "due_text": "by Friday, October 23, 2026"}])
    assert p["changes"][0]["due"] == "2026-10-23" and "deadline" in p["changes"][0]["due_warning"]


NESTED = [{"op": "create_note", "contact_id": "C-5", "summary": "x", "discussed": [[[["a"]]]]}]


@pytest.mark.parametrize("bad", [
    {"summary": "x", "changes": NESTED},
    {"summary": {"nested": {"deeper": ["x"]}}, "changes": []},
    {"summary": "x", "changes": ["not an object"]},
    {"summary": "x", "changes": [{"op": "create_note", "contact_id": {"id": "C-5"}}]},
])
def test_a_tool_input_of_the_wrong_shape_is_answered_by_the_fixed_rules(bad):
    model = ScriptedModel([tool(1, "load_skill", name="house-rules"), tool(2, "propose_write", **bad)])
    chat = Chat(Agent(live=model))
    chat.say(NOTE)
    assert NOTES["invalid"] in [t.get("text") for t in chat.view["transcript"] if t["kind"] == "system"]
    assert not any(c["op"] == "create_note" and c.get("summary") == "x" for p in chat.view["pending"] for c in p["changes"])
    chat.say("What can you do?")   # the chat goes on: nothing nested was signed into it
    assert chat.reply()["text"] == "Anything else?" and len(chat.replies()) == 2


def test_a_malformed_write_is_refused_and_logged():
    from datetime import date

    from crm import CRM, ButtonConfirm
    from teamos.skills import default_library
    from teamos.tools import ToolContext, run_tool
    crm = CRM.new(date(2026, 10, 12), ButtonConfirm(b"k" * 32))
    result = run_tool(ToolContext(crm, default_library(), "Claude for Priya Natarajan", {"house-rules"}), "propose_write",
                      {"summary": 5, "changes": []})
    assert result.is_error and crm.log[-1]["outcome"] == "refused" and "malformed" in crm.log[-1]["detail"]
