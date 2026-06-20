# AgentLab Agent Map

This file is a compact navigation map for agents working in this repository.
Keep detailed policy in `config/*.yml` and long-lived project memory in
`projects/<ProjectName>/agent_docs/`.

## Source Of Truth

- Workspace projects live as siblings under `projects/<ProjectName>/`.
- Project memory lives in `projects/<ProjectName>/agent_docs/`.
- Task state lives in `projects/<ProjectName>/runs/<task_id>/`.
- Runtime policy lives in `config/*.yml`.
- Coder handoffs and external executor rules live in `DRIVER_PROTOCOL.md` and
  `OPERATING_MODEL.md`.

## Scope Rules

- New project: create a top-level sibling under `projects/`.
- New task: create work inside the selected project.
- Subtask: append work under the selected task ledger entry.
- Do not treat chat history as authoritative if a local memory file disagrees.

## Brain Layer Rules

- DeepSeek owns Supervisor, planning, review, routing, and policy decisions
  unless `config/execution_policy.yml` is explicitly changed by the user.
- Codex Plus owns Coder execution and local file edits.
- Before execution, publish route, budget, editable scope, and validation gates.
- Prefer the smallest safe route; include agents only when their function is
  needed.
- Repeated human feedback or audit findings must be promoted into config,
  validation gates, scripts, or concise project memory.

## Editing Rules

- Use existing patterns and helpers before adding new abstractions.
- Preserve unrelated user changes in the worktree.
- Use `apply_patch` for manual edits.
- Record real commands and real validation results only.
- Never store credentials or private tokens in project memory.

## Dual-End Collaboration Protocol (双端协作协约)

- **Network Topology / Link Layout**:
  - **Local Mac**: Primary development environment and source of truth.
  - **Relay Hub (TrueNAS at `10.147.17.61:2222`)**: Resource exchange relay station and backup.
  - **Cloud Runtime (Server at `10.147.17.250`)**: Running / deployment environment. Directly accessible via SSH from Local Mac and connected to the TrueNAS repository.
- **Sync Workflow**:
  - Local Mac pushes skills, configs, memory snapshots to `10.147.17.61` using `./agentlab.sh truenas-sync --execute`.
  - Cloud Runtime (`10.147.17.250`) pulls updates from `10.147.17.61` using `rsync` to synchronize `skills`, `mcp`, and task status.
  - Cloud Runtime execution results are pushed back to `10.147.17.61` and then pulled to Local Mac to ensure all memory capabilities are synchronized.

## Useful Commands

- `./agentlab.sh prepare --project AgentLab --task-id task_0009 --write-plan`
- `./agentlab.sh brain-status --project AgentLab --task-id task_0009`
- `./agentlab.sh harness-status --project AgentLab --task-id task_0009`
- `./agentlab.sh policy-status --project AgentLab`
- `./agentlab.sh log-event --project AgentLab --task-id task_0009 --agent Coder --summary "..."`

