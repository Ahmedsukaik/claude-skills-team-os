"""The evaluation's case files stay valid, the fixed rules pass every case, and the judges catch
what matters."""
from __future__ import annotations

import pytest

from evals.__main__ import (
    TASK_SKILLS,
    LocalRunner,
    judge_behaviour,
    judge_consistency,
    judge_trigger,
    load,
    structured,
)

TRIGGERING, BEHAVIOUR, CONSISTENCY = load("triggering.jsonl"), load("behaviour.jsonl"), load("consistency.jsonl")
RUNNER = LocalRunner(live=False)


def test_the_case_files_are_well_formed():
    assert 38 <= len(TRIGGERING) <= 45 and len({c["id"] for c in TRIGGERING}) == len(TRIGGERING)
    labels = [c["skill"] for c in TRIGGERING]
    assert set(labels) == {*TASK_SKILLS, "house-rules", None}
    assert labels.count(None) >= 8 and all(c.get("near_miss") for c in TRIGGERING if c["skill"] is None)
    assert all(labels.count(s) >= 5 for s in TASK_SKILLS)
    kinds = {c["kind"] for c in BEHAVIOUR}
    assert kinds >= {"gate held", "timestamp rule", "duplicate blocked", "ambiguity asked", "draft never sent"}
    assert all(len(c["brokers"]) == 3 and len(set(c["brokers"])) == 3 for c in CONSISTENCY)


@pytest.mark.parametrize("case", TRIGGERING, ids=lambda c: c["id"])
def test_the_fixed_rules_trigger_the_right_skill(case):
    assert judge_trigger(case, RUNNER.chat([case["say"]]), "guided") == []


@pytest.mark.parametrize("case", BEHAVIOUR, ids=lambda c: c["id"])
def test_the_fixed_rules_pass_the_behaviour_cases(case):
    assert judge_behaviour(case, RUNNER.chat(case["say"]), "guided") == []


@pytest.mark.parametrize("case", CONSISTENCY, ids=lambda c: c["id"])
def test_the_same_note_from_three_brokers_gives_the_same_fields(case):
    views = [RUNNER.chat([case["say"]], broker) for broker in case["brokers"]]
    assert judge_consistency(case, views, "guided") == []
    assert {v["broker"]["name"] for v in views} == {"Priya Natarajan", "Sam Whitfield", "Jordan Avery"}


def view_with(skills, steps=(), pending=(), metrics=None, text="ok", mode="live"):
    return {"transcript": [{"kind": "assistant", "text": text, "skills": list(skills), "mode": mode,
                            "steps": [{"tool": s} for s in steps]}],
            "pending": list(pending), "drafts": [], "metrics": {"writes_saved": 0, "writes_proposed": 0, **(metrics or {})}}


def test_the_triggering_judge_catches_misfires():
    debrief = {"id": "x", "skill": "voice-note-debrief", "say": "..."}
    assert judge_trigger(debrief, view_with(["house-rules", "voice-note-debrief"]), "live") == []
    assert "house-rules did not load with the task skill" in judge_trigger(debrief, view_with(["voice-note-debrief"]), "live")
    assert "also loaded crm-update" in judge_trigger(debrief, view_with(["house-rules", "voice-note-debrief", "crm-update"]),
                                                     "live")
    assert judge_trigger(debrief, view_with([]), "live")[0].startswith("voice-note-debrief did not load")
    near = {"id": "y", "skill": None, "say": "..."}
    assert judge_trigger(near, view_with([]), "live") == []
    assert judge_trigger(near, view_with([], steps=["search_crm"]), "live") == ["used the CRM (search_crm) for a question "
                                                                                "that needs no skill"]
    assert "a reply came from the fixed rules, not the live model" in judge_trigger(near, view_with([], mode="guided"), "live")


def test_the_behaviour_judge_catches_a_broken_gate_and_a_guessed_date():
    case = {"id": "g", "kind": "gate held", "say": [], "expect": {"pending_min": 1, "saved": 0,
                                                                   "times": [{"op": "create_note", "text": "last week", "value": None}]}}
    guessed = [{"changes": [{"op": "create_note", "stated_time_text": "last week", "stated_time": "2026-10-05"}]}]
    problems = judge_behaviour(case, view_with([], pending=guessed, metrics={"writes_saved": 1}), "live")
    assert "1 writes were saved, expected 0" in problems
    assert any(p.startswith("no create_note with time 'last week'") for p in problems)


def test_the_consistency_judge_compares_fields_not_prose():
    def pending(summary, contact):
        return [{"changes": [{"op": "create_note", "contact_id": contact, "summary": summary, "stated_time_text": "Last week",
                              "stated_time": None}]}]
    same = [view_with([], pending=pending(s, "C-10")) for s in ("Coffee with Hana", "Met Hana for coffee", "Hana coffee")]
    case = {"id": "c", "brokers": ["B-1", "B-2", "B-3"]}
    assert judge_consistency(case, same, "guided") == [] and structured(same[0])[0][-1] == "last week"
    different = same[:2] + [view_with([], pending=pending("Coffee", "C-11"))]
    assert judge_consistency(case, different, "guided")[0].startswith("B-3 got different fields")



def test_stated_words_match_with_or_without_a_plain_on_or_due():
    from evals.__main__ import same_words
    assert same_words("on October 30, 2026", "October 30, 2026") and same_words("Due October 30, 2026", "October 30, 2026")
    assert not same_words("by October 30, 2026", "October 30, 2026")   # "by" makes a deadline
