---
name: crm-update
description: Creates or updates CRM records on a broker's request, such as adding a contact or a company, changing a contact's email or job title, or moving a deal to another stage (for example "LOI signed"). Checks for duplicates first and reads the change back before saving, only on an explicit yes. Use when a broker asks to add, change, correct or move a specific contact, company or deal. Do not use to log what happened on a call or tour (voice-note-debrief), for reports on many deals (weekly-pipeline), for meeting briefs (meeting-prep), for drafting emails (follow-up-email), or for questions about what a stage or a term means.
---

# CRM update

Use with house-rules: load it first if it is not loaded yet. This skill makes one small, exact
change to a contact, a company or a deal.

## Steps

1. **Find the record** with `search_crm`.
   - More than one match ("Dana's deal" when there are two Danas): ask which one, with what tells
     them apart (company, deal name, stage). Do not propose anything until the broker answers.
   - No match when updating: say so. Do not create a record instead unless the broker asks.
2. **Before creating, check for a duplicate.** Search by the email and by the name. If the person
   or company is already there, show the match and ask whether to update it instead. The CRM
   also blocks duplicates: if `propose_write` returns `duplicate_contact` or `duplicate_company`,
   report the match it gives and stop.
3. **Map the request** with `references/field-map.md`. Deal stages must be one of the names in
   `references/deal-stages.md`, spelled as there. If the broker uses another word ("signed the
   LOI", "we're under offer"), map it only when the table lists it; otherwise ask.
4. **Propose it** with `propose_write`: one change per thing the broker asked for. Then read it back,
   showing the value before and after.
5. **Wait for an explicit yes** (house rules section 4). On yes, save with `commit_write`, or ask
   the broker to press Confirm where the read back card has a button.

## Rules

- Change only what the broker asked for. Never "tidy up" other fields.
- If the broker says when a stage change happened ("they signed this morning"), put their words
  in `stated_time_text`. Do not turn them into a date.
- One record per question when something is unclear. Do not batch guesses.
- An email address must come from the broker. Never build one from a name and a company.
