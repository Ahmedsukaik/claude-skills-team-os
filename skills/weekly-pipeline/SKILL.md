---
name: weekly-pipeline
description: Writes a read only summary of the deal pipeline with deals by stage, the open total, and stale deals that have had no logged activity for 21 days or more, using list_deals. Use when a broker or the team asks for the weekly pipeline, a pipeline review, the state of open deals, or which deals are stale or need attention. Do not use for one deal or one client (meeting-prep), for changing a deal stage (crm-update), or for general questions about what a sales pipeline is. It never writes to the CRM. Always load it together with house-rules.
---

# Weekly pipeline

Before anything else, load house-rules unless it is already loaded in this chat, even for read only work: it sets what may be shown to the broker (names, never record ids), privacy and tone. This skill only reads.

## Steps

1. **Get the numbers** with `list_deals`. Filter by owner only if the broker asks for their own
   deals ("my pipeline").
2. **Write the summary** with `references/pipeline-format.md`.
3. **Stale deals** are the ones `list_deals` marks `stale`. Use its `days_since_activity`. Do not
   work out days yourself.

## Rules

- Every number comes from `list_deals`: counts by stage, the open total, days since activity.
- Closed deals are counted but not listed one by one, unless asked.
- For each stale deal, name the owner and suggest one next step from its stage (for example a
  check in call for a Lead). Do not change anything; if the broker wants a change, that is a
  separate request with its own read back.
- Keep it to one screen.
