# The skills

Six Claude skills for a small commercial real estate brokerage. The firm in the examples,
Marrowby Commercial, is fictional, and so is every person and record. Each folder is one skill:
a `SKILL.md` (a short YAML header with `name` and `description`, then the instructions) and the
supporting files it points to.

| Skill | What it does | Writes to the CRM? |
|---|---|---|
| `house-rules` | the shared rules: CRM as system of record, the timestamp rule, read back and wait for a yes, ambiguity, privacy, tone | no (it governs the others) |
| `voice-note-debrief` | a voice note after a call or tour becomes one CRM note plus follow up tasks | yes, after a yes |
| `crm-update` | add a contact or company, change a contact's email or job title, move a deal's stage | yes, after a yes |
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

**Where they work.** The skills load wherever Claude supports skills. The CRM tools they call come
from an MCP server. On claude.ai in the browser the skills load but the CRM tools do not: use
Claude Code or Claude Desktop with the local server in `mcp_server/`, or host the server over
HTTP and add it as a custom connector (Organization settings > Connectors).

**Claude (Team or Enterprise plan).** Skills need code execution. On Team it is on by default. On
Enterprise, an owner first turns on Code execution and file creation, and Skills (Organization
settings > Plugins & skills). Zip each folder so the zip holds `house-rules/SKILL.md`. An owner
can provision the zips for everyone; a person can upload one under Customize > Skills > + >
Create skill > Upload a skill.

**Claude Code.** From the repository folder, copy the six folders into `.claude/skills/` in a
project (shared through the repository) or into `~/.claude/skills/` for one person:

```bash
mkdir -p .claude/skills && cp -R skills/house-rules skills/voice-note-debrief skills/crm-update skills/meeting-prep skills/follow-up-email skills/weekly-pipeline .claude/skills/
```

```powershell
New-Item -ItemType Directory -Force .claude\skills | Out-Null; Get-ChildItem skills -Directory | Copy-Item -Destination .claude\skills -Recurse -Force
```

**The CRM tools.** The skills call nine tools from the `brokerage-crm` MCP server:
`brokerage-crm:search_crm`, `get_record`, `list_deals`, `get_calendar` and `get_activity_log`
(reads); `propose_write`, then `commit_write` or `discard_write` (writes, in two steps); and
`create_email_draft` (a draft, never sent). In this repository they work against the fake CRM; in
a real setup the same tool names would wrap HubSpot, the calendar and Gmail. The main README has
the commands to add the server to Claude Code and Claude Desktop, and a smoke test.

## Changing a skill

1. Edit the `SKILL.md` or a supporting file. Keep the description under 1024 characters, with no
   `: ` or ` #` inside it (they break the YAML header).
2. Run `python -m pytest tests/test_skills.py` (format checks) and `python -m evals` (triggering
   and behaviour).
3. The cases test the descriptions only when a live model answers; the fixed rules were written
   for them. When the demo is deployed, run `python -m evals --url <demo>` (about an hour), and
   before a rollout run the cases with Claude Sonnet and Claude Opus as well as Haiku.
