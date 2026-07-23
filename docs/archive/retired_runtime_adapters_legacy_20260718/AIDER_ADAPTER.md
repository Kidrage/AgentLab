# Aider Adapter

AgentLab can use Aider as a Coder/Editor backend, but Aider does not replace the
AgentLab workflow.

## Responsibility Split

- AgentLab Supervisor owns task scope, routing, token budgets, and stop rules.
- AgentLab RepoScout owns repository discovery.
- AgentLab Interface Mapper owns contracts and boundaries.
- Aider may perform the Coder edit loop for explicitly selected files.
- AgentLab Tester/Auditor owns validation and review.
- AgentLab Archivist owns memory updates.

## Phase 2A Behavior

The adapter only produces an invocation plan. It does not:

- Install Aider.
- Run Aider.
- Edit source code.
- Commit changes.
- Claim tests passed.

## Required Inputs

- `projects/<ProjectName>/project_config.yml`
- `projects/<ProjectName>/agent_docs/00_CONTEXT_PACK.md`
- `projects/<ProjectName>/agent_docs/01_REPO_MAP.md`
- `agent_templates/coder.md`
- `projects/<ProjectName>/runs/task_xxxx/user_request.md`
- `projects/<ProjectName>/runs/task_xxxx/supervisor_plan.md`
- `projects/<ProjectName>/runs/task_xxxx/reposcout_report.md`

## Planned Command Shape

```bash
aider \
  --read /path/to/project_config.yml \
  --read /path/to/00_CONTEXT_PACK.md \
  --read /path/to/01_REPO_MAP.md \
  --read /path/to/coder.md \
  --read /path/to/supervisor_plan.md \
  --read /path/to/reposcout_report.md \
  --message-file /path/to/user_request.md \
  path/to/editable_file
```

Run the command from the target `repo/` directory so Aider can use the repository
git state as its safety net.

## Safety Rules

- Editable files must be chosen by the Supervisor plan.
- Read-only AgentLab context files must not be edited by Aider.
- Do not pass broad directory globs as editable targets.
- Tester/Auditor must inspect diffs and run approved validation afterward.
