# Debrief field map

Where each part of a voice note goes in the CRM. Every debrief is one `propose_write` with one
`create_note` and one `create_task` per action.

## The note (`op: create_note`)

| Debrief part | Field | Rule |
|---|---|---|
| Who | `contact_id` | required; from `search_crm`; ask if more than one match |
| Company | `company_id` | optional; the CRM fills it from the contact and refuses a mismatch |
| Property | `property_id` | only if the broker named or clearly described one property |
| Deal | `deal_id` | the open deal for this company and property; leave out if unclear |
| Headline | `summary` | one line, at most 200 characters |
| What was discussed | `discussed` | list, one to five short facts in the broker's words |
| Next steps | `next_steps` | list, the actions as the broker named them |
| When it happened | `stated_time_text` | the broker's exact words ("yesterday afternoon"), or leave out |

## Each task (`op: create_task`)

| Debrief part | Field | Rule |
|---|---|---|
| The action | `title` | starts with a verb: "Send Marcus the HVAC specs" |
| Who it concerns | `contact_id` | the same contact as the note |
| Deal | `deal_id` | the same deal as the note, if any |
| When it is due | `due_text` | the broker's exact words for this task only, or leave out |

## Never

- Never fill `stated_time`, `due` or `recorded_at`: the CRM sets them.
- Never put a date in `due_text` that the broker did not say.
- Never move a deal stage inside a debrief. If the broker says the deal moved, say you can do it
  as a separate change (crm-update) after this one is saved.
