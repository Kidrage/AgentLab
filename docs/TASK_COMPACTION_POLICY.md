# Task Compaction Policy

Task compaction is not deletion. It is a structured way to let future agents read the task outcome without rereading every raw log and handoff.

## Task States

- `active`: current work, full context may be needed.
- `closed`: completed task with raw evidence preserved.
- `compacted`: task has a compact index and memory-promotion candidates.
- `archived`: cold storage, read only by explicit request.

## Compact Outputs

`task_compact/` contains:

- `task_summary.md`
- `final_verdict.yml`
- `artifact_index.yml`
- `decision_delta.yml`
- `memory_promotions.yml`
- `unresolved_items.yml`
- `reusable_patterns.yml`
- `cost_summary.yml`
- `agent_contribution_summary.yml`

Raw files are preserved unless a future command explicitly enables pruning. S2.5 does not prune by default.
