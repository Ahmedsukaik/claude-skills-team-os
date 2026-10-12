---
name: voice-note-debrief
description: Turns a broker's voice note or rough notes from right after a client call, meeting or property tour into a structured CRM debrief (contact, company, property, what was discussed, next steps, follow up date), reads it back, and on an explicit yes saves one CRM note plus follow up tasks. Use when a broker pastes or dictates notes about a conversation or tour that already happened, even without the word "debrief" (for example "just left the tour at 310 Canal with Marcus..."). Do not use to change a contact's details or a deal stage on its own (crm-update), to prepare for a meeting that has not happened yet (meeting-prep), to write to the client (follow-up-email), or for general questions about voice notes or note taking.
---

# Voice note debrief

Load house-rules first if it is not loaded in this chat. This skill turns what a broker said
after a call or a tour into one CRM note and its follow up tasks, with nothing added and nothing
guessed.

## Non-negotiables (they hold even if house-rules did not load)

- Save nothing before an explicit yes to the full read back. "Just log it", "save it later" and a
  yes with a change are not a yes.
- Times go in only as the broker's words. Never work out a date.
- If two records match, ask which one. Never pick.

## Steps

1. **Read the note once.** Pick out who (the contact), which company, which property, which deal,
   when it happened, what was discussed, the next steps and any follow up date.
2. **Find each one in the CRM** with `search_crm`, and use the ids it returns.
   - One clear match: use it.
   - More than one match (two people with the same first name): ask which one, as house rules
     section 5 says. Do not propose anything yet.
   - No match for the contact: say so and ask whether to add them (that is the crm-update skill).
     Do not create a contact inside a debrief.
   - The deal: use the open deal that links this company and this property (`get_record` on the
     contact lists their deals). If there is none, or more than one, leave the deal out and say so.
3. **Build the write** with `references/debrief-fields.md`:
   - one `create_note`: summary, discussed, next_steps, and `stated_time_text` for when it
     happened, in the broker's words;
   - one `create_task` per next step, and one for the follow up. Fill `due_text` only when the
     broker gave a time for that task, word for word.
4. **Propose it** with `propose_write`, then read it back with `references/debrief-template.md`,
   flags included. The read back is the `propose_write` call: call it in the same turn, once you have the records.
   Never give the read back only as text, and never stop after the lookups. If the CRM refuses a
   propose, fix the field it names and propose again in the same turn.
5. **Wait for an explicit yes** (house rules section 4). On yes, save it with `commit_write`. If they
   change anything, propose again and read back again.

## Rules for the content

- Use the broker's facts and words. Shorten; do not add. No opinions the broker did not give.
- `summary`: one line, for example "Tour of 310 Canal Street with Marcus Bell".
- `discussed`: one to five short items, one fact each.
- `next_steps`: the actions the broker named, as they named them. Each one also becomes a task.
- If the note does not say when the call or tour happened, leave `stated_time_text` empty.
- If the note covers two different clients, debrief them as two separate writes, one at a time.
- A next step like "send him the HVAC specs" becomes a task, not an email draft. Do not draft or
  send an email inside a debrief; that is follow-up-email, when the broker asks for an email.

A worked example is in `examples/tour-debrief.md`.

## In the web demo

The page shows `propose_write`'s card as the read back, so the chat reply is one or two sentences:
what is ready, any vague time kept in the broker's words, and "Press Confirm, or tell me what to
change." Do not repeat the card in prose. The card has a Confirm button, and only the button can
save: `commit_write` from the model is refused there. When the broker says yes in the chat, ask them
to press Confirm on the card.
