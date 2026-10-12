---
name: follow-up-email
description: Drafts a follow up email from a broker to a client contact, based on the CRM record and the latest notes, and saves it as a draft for the broker to review. It never sends anything. Use when a broker asks to write, draft or prepare an email, a thank you, a recap or a reply to a contact who is in the CRM. Do not use for voice notes or debriefs that mention sending something (voice-note-debrief turns those into tasks), for internal messages to colleagues, to log a call (voice-note-debrief), to change records (crm-update), or for general writing help that does not involve a CRM contact. Always load it together with house-rules.
---

# Follow up email

Before anything else, load house-rules unless it is already loaded in this chat, even for read only work: it sets what may be shown to the broker (names, never record ids), privacy and tone. This skill writes a draft. Sending is
always the broker's own action, outside this skill.

## Steps

1. **Find the contact** with `search_crm`. If the name matches more than one person, ask which one.
2. **Read what to build on**: `get_record` on the contact gives their deals, recent notes and open
   tasks. Use the latest note for what was discussed and promised.
3. **Write the draft** with `references/email-style.md`: a subject, a greeting, two to four short
   paragraphs, the broker's name.
4. **Save it** with `create_email_draft`. Tell the broker it is saved as a draft in their mailbox and
   not sent, and show the subject and the text so they can check it here.

## Rules

- Never send, schedule or say "sent". If the broker asks you to send it, explain that drafts are
  all this skill makes, and that they send it themselves after a read.
- Only facts from the CRM or from the broker's request. No prices, dates or promises the notes do
  not contain.
- If a date in the notes is kept as words ("by March"), keep the words in the email.
- Do not include other clients' names or details.
- A draft is not a CRM write, so it needs no read back, but do show the text in the chat.
