---
name: meeting-prep
description: Writes a short, read only brief before a meeting, call or tour with a client (who they are, their company, open deals and stages, the last notes, open tasks, and what to ask), from the CRM and the calendar. Use when a broker asks to prepare for, get ready for, or be briefed on an upcoming meeting, call or tour with a contact or a company. Do not use to log a meeting that already happened (voice-note-debrief), to change any record (crm-update), or to draft an email (follow-up-email). It never writes to the CRM.
---

# Meeting prep

Load house-rules first if it is not loaded in this chat. This skill only reads. It never
proposes or saves a change.

## Steps

1. **Find the meeting** with `get_calendar` (the next 7 days, or longer if the broker says so).
   If more than one meeting matches, ask which one. If none matches, say so and offer a brief on
   the contact anyway.
2. **Read the records**: `get_record` on the contact (their deals, recent notes, open tasks) and on
   the deal if there is one.
3. **Write the brief** with `references/brief-template.md`. Every fact comes from those results.
4. **Suggest questions** only from gaps and open points in the notes and tasks (an open question,
   an overdue task, a concern the client raised). Do not invent concerns.

## Rules

- Times and dates come from the calendar and the CRM exactly as returned.
- If a section has nothing in the CRM, write "nothing in the CRM" rather than filling it.
- Keep it to what fits on one phone screen: about 12 lines.
- If the broker asks you to change something while preparing, finish the brief, then handle the
  change as its own request (crm-update), with its own read back.
