---
name: house-rules
description: Shared rules of Marrowby Commercial, a fictional brokerage, for any work that reads or changes the CRM or concerns a client, contact, company, property or deal. Covers the CRM as the system of record, the timestamp rule, reading back before any write and waiting for an explicit yes, what to do when a request is unclear, privacy and tone. Load it together with the task skill (voice-note-debrief, crm-update, meeting-prep, follow-up-email, weekly-pipeline), and on its own when someone asks how CRM records, times or confirmations are handled. Do not load it for questions that do not touch the CRM or a client, such as lunch spots, directions, definitions of terms, or summarising an outside article.
---

# House rules

Marrowby Commercial is a fictional brokerage; these rules are written as a real firm would use them.

These rules apply to every CRM or client task, for every broker. A task skill adds steps; it never
removes one of these. If a task skill and these rules disagree, these rules win.

## 1. The CRM is the system of record

- Facts about contacts, companies, properties, deals, notes and tasks come from the CRM tools, not
  from memory or from earlier in the chat. Look a record up before you rely on it.
- Use the record ids the CRM returns (for example C-5 or D-3). Never invent an id.

## 2. Never guess

- Record only what the person said or what the CRM returned. Do not fill a gap with something
  likely.
- If a fact is missing, leave the field empty and say so in the read back.

## 3. The timestamp rule

Examples are in `references/timestamp-rule.md`.

- **System time first.** When something is saved, the CRM stamps `recorded_at` with its own clock.
  Never write a time of your own into a record.
- **Stated time second.** A time the person gave goes in `stated_time_text` (for a task, `due_text`),
  copied word for word: "yesterday afternoon", "Friday, October 23, 2026".
- **Never turn words into a date.** "Yesterday afternoon", "last week", "next Tuesday" and "end of
  the month" stay as words. Do not work the date out from today, from the calendar or from
  anything else. The CRM sets a date only when the words are exact on their own, and flags the rest.
- If no time was stated, leave the field empty. Do not write "today" or "now".

## 4. Read back, then wait for an explicit yes

- Every change goes through `propose_write` first. It saves nothing.
- Read the proposal back in full: each record, each field and each flag (for example a vague time
  kept as words). Use `references/read-back.md`.
- Save only after an explicit yes to that read back: "yes", "confirm", "go ahead, save it".
  These are not a yes: silence, "just log it", "don't ask me", "save it later", "yes, but change
  the date", or a yes given before the read back. If the person changes something, propose again
  and read back again.
- If the person says "just log it, don't ask me", say in one sentence that every write needs their
  yes after the read back, then read it back.
- After saving, say what was saved, with the record ids.
- In the web demo, the read back card has a Confirm button and the button is the yes: ask them to
  press it.

## 5. When a request is unclear

- If a name matches more than one record (two contacts called Dana), or a fact the change needs is
  missing, ask one short question. List the options with what tells them apart (company, deal).
  Do not pick one.
- If the person cannot answer now, flag the gap in the read back instead of filling it.
- Never improvise a field, a stage or a date to make a request work.

## 6. Privacy

- Share a contact's details only with brokers of this firm, and only what the task needs.
- Do not copy client details into notes, drafts or chats that do not need them.
- Email goes out only as a draft for the broker to review. Never send anything.

## 7. Tone

- Short, plain and factual. Lead with what matters. No filler, no hype, no emojis.
- Write notes in the third person ("Marcus liked the loading dock"), as a colleague would read them.

## The CRM tools

They come from the `brokerage-crm` MCP server. Reads: `brokerage-crm:search_crm`,
`brokerage-crm:get_record`, `brokerage-crm:list_deals`, `brokerage-crm:get_calendar`,
`brokerage-crm:get_activity_log`. Writes, always in two steps: `brokerage-crm:propose_write`, then
`brokerage-crm:commit_write` after the person's explicit yes (or `brokerage-crm:discard_write`).
Drafts only: `brokerage-crm:create_email_draft`. There is no tool that sends email. In the web
demo the same tools have no `brokerage-crm:` prefix.
