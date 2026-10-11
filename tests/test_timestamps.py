"""The timestamp rule: a stated time becomes a date only when the words are exact on their own."""
from __future__ import annotations

from datetime import date

import pytest

from crm.timestamps import nice, read_stated_time

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
    ("by 23 October 2026, 15:00", "2026-10-23T15:00"),
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
    ("10/23/2026", "numbers only"),             # month and day order is not certain
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
                      "stated_time_note": "Vague: kept as the person's words. No date is set."}
    assert read_stated_time("October 23, 2026", TODAY).as_fields("due") == {"due_text": "October 23, 2026", "due": "2026-10-23",
                                                                          "due_note": None}


def test_dates_read_nicely():
    assert nice("2026-10-23") == "Fri, Oct 23, 2026"
    assert nice("2026-10-23T15:30") == "Fri, Oct 23, 2026, 3:30 PM"
    assert nice(None) == ""
