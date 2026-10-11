"""The timestamp rule, in code.

Every record gets `recorded_at` from the CRM's own clock. A time the person stated is kept
separately, in their words (`stated_time_text`), and turned into `stated_time` only when the
words are exact on their own:

    "2026-10-23", "October 23, 2026", "Friday, 23 October 2026 at 3:30 pm"   -> exact
    "yesterday afternoon", "last week", "next Tuesday", "around October 23"  -> kept as words
    "10/11/2026"            -> kept as words (day and month order is not certain)
    "October 23"            -> kept as words (no year)
    "Thursday, October 23, 2026" when that date is a Friday -> kept as words, flagged
    "before October 23, 2026", "two weeks after October 23, 2026" -> kept as words (relative)
    "by October 23, 2026"   -> a date, flagged: "by" makes it a deadline, not a set day

Nothing is inferred: today's date is never used to work out a value, only to flag a value
that looks odd (a due date already past, a meeting that has not happened yet).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

MONTHS = {name: i for i, names in enumerate(
    [("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"), ("may",), ("june", "jun"),
     ("july", "jul"), ("august", "aug"), ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"),
     ("december", "dec")], start=1) for name in names}
WEEKDAYS = {name: i for i, names in enumerate(
    [("monday", "mon"), ("tuesday", "tue", "tues"), ("wednesday", "wed"), ("thursday", "thu", "thur", "thurs"),
     ("friday", "fri"), ("saturday", "sat"), ("sunday", "sun")]) for name in names}

_MONTH = r"(?P<month>" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?"
_WEEKDAY = r"(?:(?P<weekday>" + "|".join(sorted(WEEKDAYS, key=len, reverse=True)) + r")\.?,?\s+)?"
_DAY = r"(?P<day>\d{1,2})(?:st|nd|rd|th)?"
_YEAR = r"(?P<year>\d{4})"
_TIME = (r"(?:,?\s+(?:at\s+)?(?:(?P<noon>noon)|(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>a\.?m\.?|p\.?m\.?)?))?")
_LEAD = r"^(?:(?P<lead>on|by|due)\s+)?"
PATTERNS = [
    re.compile(_LEAD + r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})(?:[t\s](?P<hour>\d{2}):(?P<minute>\d{2}))?$"),
    re.compile(_LEAD + _WEEKDAY + _MONTH + r"\s+" + _DAY + r",?\s+" + _YEAR + _TIME + r"$"),
    re.compile(_LEAD + _WEEKDAY + r"(?:the\s+)?" + _DAY + r"(?:\s+of)?\s+" + _MONTH + r",?\s+" + _YEAR + _TIME + r"$"),
]
NUMERIC = re.compile(r"\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b")
_ANY_MONTH = r"(?:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?"
_ANY_DAY = r"\d{1,2}(?:st|nd|rd|th)?"
NO_YEAR = re.compile(_LEAD + _WEEKDAY + r"(?:" + _ANY_MONTH + r"\s+" + _ANY_DAY + r"|(?:the\s+)?" + _ANY_DAY +
                     r"(?:\s+of)?\s+" + _ANY_MONTH + r")" + _TIME + r"$")

VAGUE = "Vague: kept as the person's words. No date is set."
NO_YEAR_NOTE = "No year given: kept as the person's words. No date is set."
NUMERIC_NOTE = "Written in numbers only, so the order of day and month is not certain: kept as the person's words."
WEEKDAY_NOTE = "The weekday does not match the date: kept as the person's words. Check it with them."
BY_WARNING = "Said with 'by': a deadline. The date is the latest day, not an agreed day."
# Words that make a nearby date relative ("two weeks after", "not before", "around"): a date cut out
# of such a phrase is not what the person said.
RELATIVE = re.compile(r"\b(?:after|before|until|till|not|around|about|approximately|roughly|circa|within|from|since|past|than|"
                      r"\d+\s+(?:days?|weeks?|months?)|(?:a|one|two|three|four|five|six|a few|a couple of|couple of)\s+"
                      r"(?:days?|weeks?|months?))\b", re.I)
RELATIVE_AFTER = re.compile(r"^(?:or so|or later|or earlier|at the latest|at the earliest|give or take)\b", re.I)
INVALID_NOTE = "Not a real date or time: kept as the person's words."


@dataclass(frozen=True)
class StatedTime:
    text: str | None            # the person's words, exactly as given (trimmed)
    value: str | None           # ISO date or date and time, only when the words are exact
    kind: str                   # "none", "date", "datetime", "vague"
    note: str | None = None     # why there is no value, in plain words
    warning: str | None = None  # an exact value that looks odd (in the past, in the future)

    @property
    def flagged(self) -> bool:
        return self.kind == "vague" or self.warning is not None

    def as_fields(self, prefix: str = "stated_time") -> dict[str, str | None]:
        """The fields a record stores: the words, the exact value (or None), why there is no value,
        and a warning about a value that looks odd. Kept apart: a date with a warning is still a date."""
        return {f"{prefix}_text": self.text, prefix: self.value, f"{prefix}_note": self.note, f"{prefix}_warning": self.warning}


def relative_near(text: str, start: int, end: int) -> str | None:
    """The relative words right before or after text[start:end], if any. "two weeks after Friday,
    October 23, 2026": the date inside is not a time the person gave."""
    sentence = re.split(r"[.!?;:]\s", text[max(0, start - 60):start])[-1]   # the same sentence only
    before = " ".join(re.findall(r"[\w']+", sentence)[-4:])                  # the last four words before the date
    after = " ".join(re.findall(r"[\w']+", text[end:end + 30])[:3])
    m = RELATIVE.search(before) or RELATIVE_AFTER.match(after)
    return m.group(0) if m else None


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().rstrip(".").strip()


def read_stated_time(text: str | None, today: date | None = None, expect: str = "any") -> StatedTime:
    """Read what a person said about a time. `expect` is "past" (when something happened),
    "future" (a due date) or "any"; with `today` it only adds a warning, never a value."""
    if text is None or not str(text).strip():
        return StatedTime(None, None, "none")
    words = clean(str(text))
    low = words.lower()
    for pattern in PATTERNS:
        m = pattern.match(low)
        if m:
            return _exact(words, m, today, expect)
    if NUMERIC.search(low):
        return StatedTime(words, None, "vague", NUMERIC_NOTE)
    if NO_YEAR.match(low):
        return StatedTime(words, None, "vague", NO_YEAR_NOTE)
    return StatedTime(words, None, "vague", VAGUE)


def _exact(words: str, m: re.Match[str], today: date | None, expect: str) -> StatedTime:
    g = m.groupdict()
    month = int(g["month"]) if g["month"].isdigit() else MONTHS[g["month"].rstrip(".")]
    try:
        day = date(int(g["year"]), month, int(g["day"]))
    except ValueError:
        return StatedTime(words, None, "vague", INVALID_NOTE)
    if g.get("weekday") and WEEKDAYS[g["weekday"].rstrip(".")] != day.weekday():
        return StatedTime(words, None, "vague", WEEKDAY_NOTE)
    value, kind = day.isoformat(), "date"
    hour, minute = g.get("hour"), g.get("minute")
    if g.get("noon"):
        hour, minute = "12", "00"
    if hour is not None:
        h, mi = int(hour), int(minute or 0)
        ampm = (g.get("ampm") or "").replace(".", "")
        if ampm:
            if not 1 <= h <= 12:
                return StatedTime(words, None, "vague", INVALID_NOTE)
            h = h % 12 + (12 if ampm == "pm" else 0)
        elif minute is None:  # "at 3" alone: morning or afternoon is not said
            return StatedTime(words, None, "vague", VAGUE)
        if not (0 <= h <= 23 and 0 <= mi <= 59):
            return StatedTime(words, None, "vague", INVALID_NOTE)
        value, kind = datetime(day.year, day.month, day.day, h, mi).isoformat(timespec="minutes"), "datetime"
    warnings = [BY_WARNING] if g.get("lead") == "by" else []
    if today is not None:
        if expect == "future" and day < today:
            warnings.append("This date is already past. Check it with the person.")
        elif expect == "past" and day > today:
            warnings.append("This date has not happened yet. Check it with the person.")
    return StatedTime(words, value, kind, None, " ".join(warnings) or None)


def nice(value: str | None) -> str:
    """'2026-10-23' -> 'Fri, Oct 23, 2026'; '2026-10-23T15:30' -> 'Fri, Oct 23, 2026, 3:30 PM'."""
    if not value:
        return ""
    if "T" in value:
        dt = datetime.fromisoformat(value)
        clock = dt.strftime("%I:%M %p").lstrip("0")
        return f"{dt.strftime('%a, %b')} {dt.day}, {dt.year}, {clock}"
    d = date.fromisoformat(value)
    return f"{d.strftime('%a, %b')} {d.day}, {d.year}"
