# The timestamp rule, with examples

Two times can belong to a record. They are kept apart and never mixed.

| Field | Who sets it | What it holds |
|---|---|---|
| `recorded_at` | the CRM's clock, at the moment of saving | the system time, always exact |
| `stated_time_text` / `due_text` | you, copied from the person's words | exactly what they said |
| `stated_time` / `due` | the CRM, from those words | a date (or date and time) only when the words are exact |

You only ever fill the `_text` field. The CRM works out the rest and flags anything it will not
turn into a date.

## What the CRM turns into a date

| The person said | Stored as a date? | Why |
|---|---|---|
| "Friday, October 23, 2026" | yes: 2026-10-23 | a full date, and Friday matches |
| "October 23, 2026 at 3:30 pm" | yes: 2026-10-23 15:30 | a full date and a time |
| "2026-10-23" | yes | a full date |
| "yesterday afternoon" | no, kept as words | depends on when it was said |
| "last week", "next Tuesday", "end of the month" | no, kept as words | relative |
| "around October 23, 2026" | no, kept as words | approximate |
| "October 23" | no, kept as words | no year |
| "10/11/2026" | no, kept as words | day and month order is not certain |
| "Thursday, October 23, 2026" | no, flagged | that date is a Friday: ask which is right |
| "October 23, 2026 at 3" | no, kept as words | morning or afternoon is not said |

## Do

- Copy the words exactly: `"stated_time_text": "yesterday afternoon"`.
- Copy the whole phrase around a date: "by Friday, October 23, 2026" keeps its "by" (a deadline, not
  an agreed day), and "two weeks after the tour, which is Friday, October 23, 2026" stays whole. A
  plain "on" or "due" in front of a date may be left out.
- Mention the flag in the read back: "When it happened: 'yesterday afternoon' (kept as your words,
  no date set)."
- Leave the field empty when no time was given.

## Do not

- Do not write `"stated_time_text": "October 10, 2026"` because the person said "yesterday".
- Do not take a time from the calendar because a meeting "probably" matches.
- Do not add a year to "October 23".
- Do not use the time of the chat as the time something happened.
