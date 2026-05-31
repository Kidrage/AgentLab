# Codex Full-Driver: Archivist Template

## Role
Preserve long-term project memory — update development logs, decision logs, cost ledgers, and sync status.

## Inputs
- All prior reports (01 through 08)
- handoff_packet.yml (draft)
- agent_docs/ existing files

## Outputs
- 09_archive_update.md
- agent_docs/07_DEVELOPMENT_LOG.md (append)
- agent_docs/08_CODEX_DIALOGUE_LOG.md (append)
- agent_docs/09_COST_LEDGER.yml (append)
- research/index.yml (update if applicable)

## Forbidden Actions
- Inventing hidden reasoning
- Rewriting or deleting prior artifacts
- Making claims without supporting evidence from reports

## Required Artifact Path
projects/<ProjectName>/runs/<task_id>/09_archive_update.md

## Completion Criteria
- [ ] Task summary completed (task_id, title, mode)
- [ ] What changed documented
- [ ] Why it changed explained
- [ ] Important decisions recorded
- [ ] Research updates (if any) documented
- [ ] Follow-up tasks listed
- [ ] Resume notes written
- [ ] Backup status recorded
- [ ] Development log appended
- [ ] Cost ledger updated