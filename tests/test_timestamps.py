"""The timestamp rule: a stated time becomes a date only when the words are exact on their own."""
from __future__ import annotations

from datetime import date

import pytest

from crm.timestamps import lead_word, nice, read_stated_time, relative_near

TODAY = date(2026, 10, 12)


@pytest.mark.parametrize("words, value", [
    ("2026-10-23", "2026-10-23"),
    ("2026-10-23 15:30", "2026-10-23T15:30"),
    ("October 23, 2026", "2026-10-23"),
    ("Oct 23 2026", "2026-10-23"),
    ("Oct. 23, 2026", "2026-10-23"),
    ("Friday, October 23, 2026", "2026-10-23"),
    ("Fri Oct 23 2026", "2026-10-23"),
    ("23 October 2026", "2026-10-23"),
    ("the 23rd of October 2026", "2026-10-23"),
    ("on October 23, 2026 at 3:30 pm", "2026-10-23T15:30"),
    ("due 23 October 2026, 15:00", "2026-10-23T15:00"),
    ("October 23, 2026 at 9am", "2026-10-23T09:00"),
    ("October 23, 2026 at noon", "2026-10-23T12:00"),
    ("October 23, 2026 at 12 a.m.", "2026-10-23T00:00"),
    ("Friday, October 23, 2026.", "2026-10-23"),
])
def test_exact_words_become_a_date(words, value):
    stated = read_stated_time(words, TODAY)
    assert stated.value == value and stated.text == words.rstrip(".") and stated.note is None and not stated.flagged


@pytest.mark.parametrize("words, why", [
    ("yesterday afternoon", "Vague"),
    ("last week", "Vague"),
    ("next Tuesday", "Vague"),
    ("this morning", "Vague"),
    ("end of the month", "Vague"),
    ("around October 23, 2026", "Vague"),       # approximate
    ("early October 2026", "Vague"),
    ("October 23", "No year"),                  # the year would be a guess
    ("Friday the 23rd", "Vague"),               # no month and no year
    ("23rd of October", "No year"),
    ("10/11/2026", "numbers only"),             # October 11 or November 10
    ("10/23/2026", "numbers only"),             # numbers only, even when only one order is possible
    ("23.10.2026", "numbers only"),
    ("Thursday, October 23, 2026", "weekday"),  # it is a Friday
    ("February 30, 2026", "Not a real date"),
    ("October 23, 2026 at 3", "Vague"),         # morning or afternoon is not said
    ("October 23, 2026 at 13 pm", "Not a real"),
    ("2026-10-23 25:00", "Not a real"),
])
def test_anything_else_is_kept_as_words_and_flagged(words, why):
    stated = read_stated_time(words, TODAY)
    assert stated.value is None and stated.kind == "vague" and stated.flagged
    assert stated.text == words and why in (stated.note or "")


def test_no_time_given_means_empty_fields():
    for empty in (None, "", "   "):
        stated = read_stated_time(empty, TODAY)
        assert (stated.text, stated.value, stated.note) == (None, None, None) and not stated.flagged


def test_today_only_adds_a_warning_never_a_value():
    past_due = read_stated_time("October 1, 2026", TODAY, expect="future")
    assert past_due.value == "2026-10-01" and "already past" in (past_due.warning or "") and past_due.flagged
    not_yet = read_stated_time("October 30, 2026", TODAY, expect="past")
    assert not_yet.value == "2026-10-30" and "not happened yet" in (not_yet.warning or "")
    assert read_stated_time("yesterday", None).value is None


def test_the_fields_a_record_stores():
    fields = read_stated_time("yesterday afternoon", TODAY).as_fields("stated_time")
    assert fields == {"stated_time_text": "yesterday afternoon", "stated_time": None,
                      "stated_time_note": "Vague: kept as the person's words. No date is set.", "stated_time_warning": None}
    assert read_stated_time("October 23, 2026", TODAY).as_fields("due") == {"due_text": "October 23, 2026", "due": "2026-10-23",
                                                                          "due_note": None, "due_warning": None}


def test_a_date_with_a_warning_is_still_a_date_and_the_warning_is_kept_apart():
    fields = read_stated_time("by October 1, 2026", TODAY, expect="future").as_fields("due")
    assert fields["due"] == "2026-10-01" and fields["due_note"] is None
    assert "deadline" in fields["due_warning"] and "already past" in fields["due_warning"]


@pytest.mark.parametrize("words", ["before October 23, 2026", "not before October 23, 2026", "two weeks after October 23, 2026",
                                   "until October 23, 2026", "around October 23, 2026", "October 23, 2026 or so"])
def test_a_relative_phrase_around_a_date_stays_words(words):
    assert read_stated_time(words, TODAY).value is None


@pytest.mark.parametrize("text, date_part, near", [
    ("Follow up two weeks after Friday, October 23, 2026 please", "Friday, October 23, 2026", "two weeks"),
    ("Call him not before October 30, 2026.", "October 30, 2026", "not"),
    ("Send it within 3 days of October 30, 2026", "October 30, 2026", "within"),
    ("Follow up on October 30, 2026 or so", "October 30, 2026", "or so"),
    ("Follow up with Marcus on Friday, October 23, 2026.", "Friday, October 23, 2026", None),
    ("We talked about the roof. Follow up on October 30, 2026.", "October 30, 2026", None),
])
def test_relative_words_next_to_a_date_are_found(text, date_part, near):
    start = text.index(date_part)
    assert relative_near(text, start, start + len(date_part)) == near


def test_dates_read_nicely():
    assert nice("2026-10-23") == "Fri, Oct 23, 2026"
    assert nice("2026-10-23T15:30") == "Fri, Oct 23, 2026, 3:30 PM"
    assert nice(None) == ""


@pytest.mark.parametrize("text, date_part, near", [
    ("Follow up two weeks after the tour, which is Friday, October 23, 2026.", "Friday, October 23, 2026", "two weeks"),
    ("Send the lease prior to Friday, October 23, 2026.", "Friday, October 23, 2026", "prior to"),
    ("We need it ahead of October 30, 2026.", "October 30, 2026", "ahead of"),
    ("Call him the Monday following October 30, 2026.", "October 30, 2026", "following"),
    ("Due October 30, 2026 plus two days.", "October 30, 2026", "plus"),
    ("Done on October 30, 2026 if not sooner.", "October 30, 2026", "if not sooner"),
    ("Sign it no later than October 30, 2026.", "October 30, 2026", "no later than"),
    ("After the inspection we sign, so book Friday, October 23, 2026.", "Friday, October 23, 2026", "After"),
    ("Following up with Marcus on Friday, October 23, 2026.", "Friday, October 23, 2026", None),
    ("Two weeks ago he toured it. Follow up on Friday, October 23, 2026.", "Friday, October 23, 2026", None),
])
def test_a_relative_cue_anywhere_earlier_in_the_clause_counts(text, date_part, near):
    start = text.index(date_part)
    found = relative_near(text, start, start + len(date_part))
    assert (found.lower() if found else None) == (near.lower() if near else None)


def test_the_word_before_a_date_is_found():
    for text, word in (("send it by Friday, October 23, 2026", "by"), ("follow up on October 30, 2026", None),
                       ("due October 30, 2026", None), ("follow up with Ravi Menon October 30, 2026", None)):
        assert lead_word(text, text.index("October" if "Friday" not in text else "Friday")) == word
