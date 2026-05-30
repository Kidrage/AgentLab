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

## Useful Commands

- `./agentlab.sh prepare --project AgentLab --task-id task_0009 --write-plan`
- `./agentlab.sh brain-status --project AgentLab --task-id task_0009`
- `./agentlab.sh harness-status --project AgentLab --task-id task_0009`
- `./agentlab.sh policy-status --project AgentLab`
- `./agentlab.sh log-event --project AgentLab --task-id task_0009 --agent Coder --summary "..."`
