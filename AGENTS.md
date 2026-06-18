# AgentLab Agent Map

This file is a compact navigation map for agents working in this repository.
Keep detailed policy in `config/*.yml` and long-lived project memory in
`projects/<ProjectName>/agent_docs/`.

## Repository Targeting Rules

- Do not assume this AgentLab checkout is the target repository for ordinary
  coding tasks.
- Before editing or pushing, confirm the real target repository path from the
  user's prompt, local repo evidence, branch/remotes, and nearby files.
- If the user gives an explicit path, use that path as the target repository.
- If the user does not give a path, inspect common local locations such as
  `~/Desktop/Coding/`, `~/Desktop/AgentLab/projects/`, and the current working
  directory with lightweight commands, then ask the user if the target remains
  ambiguous.
- Treat AgentLab itself as the target only when the task is explicitly about
  AgentLab or its local agent runtime/configuration.

## Source Of Truth

- Workspace projects live as siblings under `projects/<ProjectName>/`.
- Project memory lives in `projects/<ProjectName>/agent_docs/`.
- Task state lives in `projects/<ProjectName>/runs/<task_id>/`.
- Runtime policy lives in `config/*.yml`.
- Coder handoffs and external executor rules live in `DRIVER_PROTOCOL.md` and
  `OPERATING_MODEL.md`.

## Repository Constitution

- Keep the repository root limited to formal engineering entrypoints such as
  `agent_runtime/`, `config/`, `docs/`, `scripts/`, `tests/`, `skills/`,
  `projects/`, `acceptance_runs/`, `README.md`, and `agentlab.sh`.
- External IDE or agent scratch files must go under ignored `.agentlab/`
  folders such as `.agentlab/inbox/`, `.agentlab/tmp/`,
  `.agentlab/scratch/`, `.agentlab/external_handoffs/`,
  `.agentlab/external_reports/`, or `.agentlab/rejected_artifacts/`.
- Durable project artifacts must move into `projects/<ProjectName>/...` or
  `acceptance_runs/...`; do not leave drafts, handoffs, pasted text, or
  one-off reports in the repository root.
- Before committing or handing off, run `./agentlab.sh repo-hygiene-check`.
- The full ProjectOps boundary rules live in `docs/PROJECT_OPS_CONSTITUTION.md`.

## Scope Rules

- New project: create a top-level sibling under `projects/`.
- New task: create work inside the selected project.
- Subtask: append work under the selected task ledger entry.
- Do not treat chat history as authoritative if a local memory file disagrees.
- Ordinary user missions do not default to `projects/AgentLab/`. Use
  `./agentlab.sh project-route --mission-contract <path>` and create a
  separate project for creative longform, research, business, document,
  audio/music, multimodal, data, and education work unless the user explicitly
  asks to modify AgentLab itself.
- If routing is ambiguous, write a decision-required result and ask the user;
  do not silently attach the task to the AgentLab self-development project.

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

- `./agentlab.sh repo-hygiene-check`
- `./agentlab.sh project-route --mission-contract <path>`
- `./agentlab.sh project-init --project-id creative_novel --type creative_longform --title "..."`
- `./agentlab.sh task-compact --project AgentLab --task-id task_0009`
- `./agentlab.sh project-status --project AgentLab --json`
- `./agentlab.sh prepare --project AgentLab --task-id task_0009 --write-plan`
- `./agentlab.sh brain-status --project AgentLab --task-id task_0009`
- `./agentlab.sh harness-status --project AgentLab --task-id task_0009`
- `./agentlab.sh policy-status --project AgentLab`
- `./agentlab.sh log-event --project AgentLab --task-id task_0009 --agent Coder --summary "..."`
