# Working with Claude and the CRM: a guide for brokers

This guide is written for the brokers of Marrowby Commercial, a fictional brokerage used in this
demo. Every name and record in the examples is made up.

Claude works with the CRM for you: it can read records, the calendar and your notes, and it can
prepare changes. It cannot save anything on its own. Every change waits for your yes.

## After a call or a tour: send a voice note

Paste or dictate what happened, the way you would tell a colleague:

> Walked 310 Canal Street with Marcus Bell from Tessarine Biotech yesterday afternoon. He liked
> the loading dock but he's worried about the HVAC. Next steps: send him the HVAC specs. Follow up
> with Marcus on Friday, October 23, 2026.

You do not need to say "debrief". Claude finds the contact, the company, the property and the
deal in the CRM, and prepares one note and a task for each next step.

## The read back: check it, then confirm

Before anything is saved, Claude shows a card with exactly what will be recorded:

- **the note**: who, which company, which property and deal, what was discussed, next steps;
- **the tasks**, each with its due date (or "No date given"), and who it is for and which deal
  when that is not the same as the note's;
- **the times**: when it happened, in your words, next to "CRM clock: when you confirm";
- **To check**: anything Claude wants you to look at, such as a vague time kept as words, or a
  date said with "by" (a deadline, not an agreed day).

Read it like you would read an email before sending. If it is right, press **Confirm and save**.
If not, tell Claude what to change ("the follow up is with Ines, not Marcus"); it prepares a new
card. **Discard** drops it, and nothing is saved.

A yes typed in the chat is not enough in this demo: the Confirm button is the yes. A card is good
for 30 minutes; after that, ask again for a fresh one. A chat lasts until the end of the day: the
next day the page starts a new one.

## Times: say what you know, nothing is guessed

The CRM keeps two times for every record:

- **CRM clock**: the CRM's own time, at the moment you confirm. Nobody types it.
- **The time you stated**, in your words. It becomes a date only when your words are exact.

"Friday, October 23, 2026" or "October 23, 2026 at 3 pm" become a date. "Yesterday afternoon",
"last week", "next Tuesday" or "October 23" (no year) stay as your words and are flagged, so
nobody later mistakes a guess for a fact. So does a date inside a longer phrase, like "two weeks
after October 23, 2026" or "not before October 30, 2026": the date alone would say something you
did not. If you want a date in the CRM, say the full date.

## "Just log it, don't ask me"

Claude will still show the card. Every change is read back and waits for your confirm; that rule
is enforced by the CRM itself, not just by Claude's manners. It takes one tap.

## When Claude asks a question

If a name fits more than one person ("Dana's deal", and there are two Danas), Claude asks which
one, with what tells them apart. It never picks one for you. Answer with the name or the company
("the Bramblecote one").

## Other things you can ask

- **Update a record**: "Move Dana Okafor's deal to LOI signed", "Change Hana Sato's email to ...",
  "Add a new contact: ..., at Kilnworth Brewing". Claude checks for duplicates first; if the
  person is already in the CRM, it tells you instead of adding them again.
- **Meeting prep**: "Prep me for tomorrow's tour with Dana Whitlock." A short brief from the
  calendar and the CRM: where the deal stands, the last note, open tasks, what to ask. It changes
  nothing.
- **Follow up email**: "Draft a follow up email to Ravi Menon." Claude saves a draft in your
  mailbox and shows it in the chat. It never sends; you review and send it yourself.
- **Weekly pipeline**: "Give me the weekly pipeline summary." Deals by stage, and the deals with
  no activity for 21 days or more.

For anything else (directions, a definition, an article), Claude answers without touching the
CRM, and the reply shows "No skill used".

## The activity log

The CRM panel lists every lookup, prepared change, refusal and save, with the CRM's clock and who
did it ("Claude, for Priya" or your name). Use it to answer "why does the CRM say that?" or "who
changed this?".

## Fixed rules

If a reply is labelled "Fixed rules", the AI was not available at that moment and simple fixed
rules answered instead. They cover the common requests and follow the same CRM rules; for
anything unusual, try again later.
