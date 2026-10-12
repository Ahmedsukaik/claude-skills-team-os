---
name: crm-update
description: Makes one exact change to the CRM on a broker's request, which is to add a contact or company, change a contact's email or job title, or move a deal's stage (for example to "LOI signed"). If the change is not one of these, it says this CRM connection cannot make it and changes nothing, and does not put it in a note instead. Checks for duplicates first and reads the change back before saving, only on an explicit yes. Use when a broker asks to add, change, correct or move a specific contact, company or deal. Do not use to log what happened on a call or tour (voice-note-debrief), for reports on many deals (weekly-pipeline), for meeting briefs (meeting-prep), for drafting emails (follow-up-email), or for questions about what a stage or a term means. Always load it together with house-rules.
---

# CRM update

Before anything else, load house-rules unless it is already loaded in this chat, even for read only work: it sets what may be shown to the broker (names, never record ids), privacy and tone. This skill makes one small, exact
change to a contact, a company or a deal.

## Non-negotiables (they hold even if house-rules did not load)

- Save nothing before an explicit yes to the full read back. "Just log it", "save it later" and a
  yes with a change are not a yes.
- Times go in only as the broker's words. Never work out a date.
- If two records match, ask which one. Never pick.

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
   showing the value before and after. The read back is the `propose_write` call: call it in the same turn, once you have the records.
   Never give the read back only as text, and never stop after the lookups. If the CRM refuses a
   propose, fix the field it names and propose again in the same turn.
5. **Wait for an explicit yes** (house rules section 4). On yes, save with `commit_write`.

## Rules

- Change only what the broker asked for. Never "tidy up" other fields.
- If the broker says when a stage change happened ("they signed this morning"), put their words
  in `stated_time_text`. Do not turn them into a date.
- One record per question when something is unclear. Do not batch guesses.
- An email address must come from the broker. Never build one from a name and a company.
- If the change is not in the field map, say this CRM connection cannot make it and change
  nothing. Do not put it in a note instead.

## In the web demo

In the web demo the card is the read back. Your text reply is at most two short sentences: what is
ready and any time kept in the broker's words. Do not list the fields again. The card has a Confirm
button, and only the button can save: `commit_write` from the model is refused there. When the
broker says yes in the chat, ask them to press Confirm on the card.
