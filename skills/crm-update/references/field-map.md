# CRM update field map

Each request becomes one or more changes in one `propose_write`.

| The broker asks to | op | Required fields | Optional fields |
|---|---|---|---|
| add a contact | `create_contact` | `first_name`, `last_name`, `email`, `company_id` | `job_title` |
| change a contact's email or title | `update_contact` | `contact_id` and the field(s) to change | |
| add a company | `create_company` | `name` | `industry` |
| move a deal to a stage | `update_deal_stage` | `deal_id`, `stage` | `stated_time_text` |

## Exactly which fields each op takes

The CRM refuses any other field (for example, `create_task` does not take `company_id`), so a
first proposal with only these fields goes through.

| op | Required | Optional, and nothing else |
|---|---|---|
| `create_note` | `contact_id`, `summary` | `company_id`, `deal_id`, `property_id`, `discussed`, `next_steps`, `stated_time_text` |
| `create_task` | `title` | `contact_id`, `deal_id`, `due_text` |
| `create_contact` | `first_name`, `last_name`, `email`, `company_id` | `job_title` |
| `create_company` | `name` | `industry` |
| `update_contact` | `contact_id` | `email`, `job_title` (at least one of them) |
| `update_deal_stage` | `deal_id`, `stage` | `stated_time_text` |

## Notes

- `company_id`, `contact_id` and `deal_id` come from `search_crm`. If the company of a new contact
  is not in the CRM yet, add the company first as its own write, then the contact.
- The CRM refuses a change that would not change anything (a deal already at that stage), and a
  contact whose email or name and company already exist. Report what it says.
- For `update_contact` and `update_deal_stage`, the proposal shows the value before the change.
  Include it in the read back: "Stage: Touring -> LOI signed".
- The CRM checks the change again at the moment of saving. If the record changed in the meantime,
  the save is refused: propose again and read back again.
