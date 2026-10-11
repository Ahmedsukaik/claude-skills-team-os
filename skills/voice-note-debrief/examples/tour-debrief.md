# Example: a property tour debrief

All names are fictional.

## What the broker sent

> Voice note after the tour. Walked 310 Canal Street with Marcus Bell from Tessarine Biotech
> yesterday afternoon. He liked the lab benches and the loading dock, but he's worried the HVAC
> can't handle their freezers. They want to move in by March. Next steps: send him the HVAC
> specs, and set up a second tour with their CFO. Follow up with Marcus on Friday, October 23, 2026.

## What to look up

- `search_crm("Marcus Bell")` returns C-5, Marcus Bell, Tessarine Biotech (CO-3).
- `search_crm("310 Canal Street")` returns P-5, 310 Canal Street Lab Building.
- `get_record("C-5")` lists deal D-3, Tessarine Biotech at 310 Canal Street (Touring).

## The proposal

```json
{
  "summary": "Tour of 310 Canal Street with Marcus Bell",
  "changes": [
    {"op": "create_note", "contact_id": "C-5", "property_id": "P-5", "deal_id": "D-3",
     "summary": "Tour of 310 Canal Street with Marcus Bell",
     "stated_time_text": "yesterday afternoon",
     "discussed": ["He liked the lab benches and the loading dock",
                   "He's worried the HVAC can't handle their freezers",
                   "They want to move in by March"],
     "next_steps": ["Send him the HVAC specs", "Set up a second tour with their CFO"]},
    {"op": "create_task", "title": "Send Marcus the HVAC specs", "contact_id": "C-5", "deal_id": "D-3"},
    {"op": "create_task", "title": "Set up a second tour with their CFO", "contact_id": "C-5", "deal_id": "D-3"},
    {"op": "create_task", "title": "Follow up with Marcus", "contact_id": "C-5", "deal_id": "D-3",
     "due_text": "Friday, October 23, 2026"}
  ]
}
```

Note what is not there: no date for "yesterday afternoon", no due date for the first two tasks
(the broker gave none), and "by March" stays inside what was discussed.

## The read back

```
Here is the debrief I will save. Nothing is saved yet.

Note: Tour of 310 Canal Street with Marcus Bell
- Contact: Marcus Bell (Tessarine Biotech)
- Property: 310 Canal Street Lab Building
- Deal: Tessarine Biotech at 310 Canal Street (Touring)
- When it happened: "yesterday afternoon" (kept as your words, no date set)
- Discussed:
  - He liked the lab benches and the loading dock
  - He's worried the HVAC can't handle their freezers
  - They want to move in by March

Tasks:
- Send Marcus the HVAC specs: no date given
- Set up a second tour with their CFO: no date given
- Follow up with Marcus: due Fri, Oct 23, 2026

Flags: "yesterday afternoon" is vague, so it is kept as your words.

Reply yes to save it, or tell me what to change.
```
