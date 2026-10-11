# The skills

Six Claude skills for a small commercial real estate brokerage. The firm in the examples,
Marrowby Commercial, is fictional, and so is every person and record. Each folder is one skill:
a `SKILL.md` (a short YAML header with `name` and `description`, then the instructions) and the
supporting files it points to.

| Skill | What it does | Writes to the CRM? |
|---|---|---|
| `house-rules` | the shared rules: CRM as system of record, the timestamp rule, read back and wait for a yes, ambiguity, privacy, tone | no (it governs the others) |
| `voice-note-debrief` | a voice note after a call or tour becomes one CRM note plus follow up tasks | yes, after a yes |
| `crm-update` | add a contact or company, change a contact's details, move a deal stage | yes, after a yes |
| `meeting-prep` | a short brief before a meeting, from the CRM and the calendar | no |
| `follow-up-email` | a client email saved as a draft, never sent | no (a draft only) |
| `weekly-pipeline` | deals by stage and stale deals | no |

## How they work together

- **house-rules always applies.** Its description tells Claude to load it with any task skill,
  and every task skill starts with "Use with house-rules: load it first". A task skill adds
  steps; it never removes a house rule. When they disagree, house-rules wins.
- **One task skill per request.** The descriptions say what each skill is for and, just as
  important, what it is not for, naming the skill that is ("Do not use to log a call
  (voice-note-debrief)"). That is what keeps two skills from both firing on one request.
- **A skill that needs another hands over instead of doing its work.** A debrief that finds an
  unknown contact asks first and leaves the new contact to crm-update; meeting-prep finishes the
  brief before any change.

## How triggering is designed

Claude sees only each skill's name and description until it decides to load one. So the
descriptions carry the triggering, and each follows the same three parts:

1. **What it does**, in the words a broker would use ("a voice note or rough notes from right
   after a client call, meeting or property tour").
2. **When to use it**, including the phrasings that do not name the task ("even without the
   word debrief, for example 'just left the tour at 310 Canal with Marcus...'"). This stops a
   skill from being skipped when it should fire.
3. **When not to use it**, with the near misses that share its words: a question about how to
   record a voice note, what a deal stage means, what a sales pipeline is, or a lunch spot near
   a property. This stops a skill from firing when it should not.

The evaluation in `evals/` checks both directions: 41 requests, each labelled with the skill
that must load or with none, including near misses.

## What is enforced where

The skills ask Claude to behave; the CRM tools enforce what must never go wrong. See the main
README for the full table. In short:

| Rule | In the skill | In code |
|---|---|---|
| propose, then save | yes | yes: nothing saves without `propose_write` first, a matching hash and a confirmation |
| read back, wait for a yes | yes | web demo: only the Confirm button can save; MCP: the person's words are required and checked |
| timestamps | yes | yes: `recorded_at` from the CRM clock; a stated time becomes a date only when exact |
| duplicates | yes | yes: a duplicate contact or company is blocked and the match returned |
| ambiguity (two Danas) | yes | no: the read back card shows the full name and company, so a wrong pick is caught before saving |
| drafts never sent | yes | yes: there is no send tool |

## Installing them

**Claude (Team or Enterprise plan).** An owner turns on skills for the organization in the admin
settings. Zip each skill folder (the folder itself, with `SKILL.md` at its top) and upload it
under Settings, Capabilities, Skills, or have an owner add it for the whole organization so
every broker runs the same version. Claude.ai menu names change from time to time; Anthropic's
help center has the current steps.

**Claude Code.** Copy the folders into `.claude/skills/` in a project (shared through the
repository) or into `~/.claude/skills/` for one person:

```bash
cp -r skills/house-rules skills/voice-note-debrief ... .claude/skills/
```

**The CRM tools.** The skills call tools named `search_crm`, `get_record`, `list_deals`,
`get_calendar`, `propose_write`, `commit_write` and `create_email_draft`. In this repository they
come from the MCP server in `mcp_server/` (against the fake CRM); in a real setup the same tool
names would wrap HubSpot, the calendar and Gmail. See the main README to run the MCP server.

## Changing a skill

1. Edit the `SKILL.md` or a supporting file. Keep the description under 1024 characters, with no
   `: ` or ` #` inside it (they break the YAML header).
2. Run `python -m pytest tests/test_skills.py` (format checks) and `python -m evals` (triggering
   and behaviour).
3. When the demo is deployed, run `python -m evals --url <demo>` to check the live model too.
