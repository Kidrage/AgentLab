# AgentLab ProjectOps Constitution

This document defines the operational boundaries that keep AgentLab usable for
long projects such as novels, research programs, and multi-phase engineering.

## Repository Root

The repository root is for formal engineering entrypoints only. External IDE
agents must not write drafts, pasted text, handoffs, debug dumps, or scratch
reports directly into the root.

Use ignored runtime folders instead:

```text
.agentlab/inbox/
.agentlab/tmp/
.agentlab/scratch/
.agentlab/external_handoffs/
.agentlab/external_reports/
.agentlab/rejected_artifacts/
```

Run before commit or handoff:

```bash
./agentlab.sh repo-hygiene-check
```

## Project Routing

`projects/AgentLab/` is only for AgentLab self-development. Ordinary user
missions must be routed before task creation:

```bash
./agentlab.sh project-route --mission-contract <path>
```

Routing outcomes:

- `attach_existing_project`: mission explicitly names a known project.
- `create_new_project`: mission should become a new project.
- `self_development_project`: mission clearly modifies AgentLab itself.
- `ambiguous_requires_user_decision`: stop and ask; do not default to AgentLab.

Creative longform, research, business, document processing, audio/music,
multimodal, data analysis, and education work default to new projects.

## Longform Memory Rule

Longform creative work is treated as a large engineering project:

- durable canon lives in `agent_docs/PROJECT_BRIEF.md` and promoted memory files;
- phase/task work lives in `runs/<task_id>/`;
- raw drafts and agent notes are not the default future context;
- closed tasks are compacted before later phases read them.

This protects character continuity, world rules, plot state, and unresolved
threads from being rewritten by raw-log drift.

## Task Compaction

After a task closes, run:

```bash
./agentlab.sh task-compact --project <ProjectName> --task-id <task_id>
```

The compact directory is the default future read surface:

```text
runs/<task_id>/task_compact/
  task_summary.md
  final_verdict.yml
  artifact_index.yml
  decision_delta.yml
  memory_promotions.yml
  unresolved_items.yml
  reusable_patterns.yml
  cost_summary.yml
  agent_contribution_summary.yml
```

Raw files are preserved, but later agents should not read them unless a compact
item points to trace evidence.

## Handoff Packet Rule

Agent-to-agent handoff should be a small structured packet that points to
artifacts instead of embedding long reports.

Required fields:

```yaml
packet_id: ""
project_id: ""
task_id: ""
sender: ""
receiver: ""
purpose: ""
max_context_budget_tokens: 1200
must_read: []
summary:
  what_changed: ""
  key_findings: []
  open_risks: []
requested_action:
  type: ""
  acceptance: []
forbidden:
  - reread_full_raw_logs
  - modify_unrelated_files
```

## Contribution Ledger

Every meaningful agent contribution should be recorded:

```bash
./agentlab.sh agent-contributions --project <ProjectName> --task <task_id> \
  --agent-id <agent_id> --role <role> --summary "<what changed>" --accepted
```

The ledger feeds task compaction and project status, making accepted,
rejected, costly, or risk-producing work visible.

## Project Status

Use:

```bash
./agentlab.sh project-status --project <ProjectName> --json
```

Project status should be the first place a future agent checks for active,
closed, compacted, and archived tasks before reading run directories.
