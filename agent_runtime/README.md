# AgentLab Runtime

Phase 2A/2B placeholder runtime for a reusable local multi-agent development workflow.

This runtime is intentionally conservative:

- It does not install dependencies.
- It does not edit source code automatically.
- It does not create real secret files.
- It prepares task context, agent definitions, policy checks, and report schemas only.
- It reads local config files and produces an inspectable workflow plan.

## Intended Flow

1. Configure `.env.example` values in a private `.env` outside version control when ready.
2. Add or map a project under `projects/<ProjectName>/`.
3. Create a new `runs/task_xxxx/` folder for each task.
4. Ask agents to write reports into that run folder.
5. Only apply source changes after explicit human review or instruction.

## Config Layer

Global workflow config lives in `../config/`:

- `agent_registry.yml`: agent capabilities and permissions.
- `agent_model_profiles.yml`: canonical role backend and model selection.
- `routing_rules.yml`: smallest-safe-route task routing.
- `budget_profiles.yml`: token budget estimates and stop thresholds.
- `execution_policy.yml`: DeepSeek brain requirement and Codex Coder quota decisions.
- `harness_policy.yml`: repo-local maps, feedback loops, mechanical gates, and guidance cleanup.
- `validation_gates.yml`: evidence required before acceptance.
- `memory_policy.yml`: local-first task state and project memory rules.

These files are the preferred place to edit AgentLab behavior. The markdown
templates define role prompts and report formats.

## Task Routing

`task_router.py` recommends the smallest safe set of agents for a task using
`../config/routing_rules.yml`:

- Small: Supervisor -> Coder -> Tester/Auditor
- Medium: Supervisor -> RepoScout -> Coder -> Tester/Auditor -> Archivist
- Interface-sensitive: adds Interface Mapper
- Research-sensitive: adds Researcher
- Large or risky: uses the full route when needed

The route is advisory in Phase 2A; Supervisor still owns the final plan.

## Workflow Plan

`workflow_plan.py` combines:

- project config
- task request
- agent registry
- model profiles
- routing rules
- token budgets
- validation gates
- memory policy
- optional Aider plan

Example:

```bash
python run_task.py prepare --project ExampleProject --task-id task_0001
```

Write the plan into `runs/task_xxxx/workflow_plan.yml`:

```bash
python run_task.py prepare --project ExampleProject --task-id task_0001 --write-plan
```

## CLI Commands

- `init-task`: create a run folder and placeholder reports.
- `prepare`: build and optionally save a workflow plan.
- `status`: show state, route, missing inputs, and report files.
- `models`: show provider/profile configuration without secrets.
- `policy-status`: show the hard DeepSeek brain and Codex Coder policy.
- `harness-status`: show whether the local harness map, project memory, and task feedback artifacts are healthy.
- `request-coder-quota`: ask the user to pause or explicitly delegate coding when Codex quota is insufficient.
- `run-agent`: dry-run or execute a single agent model call.

`run-agent` does not call a model unless `--execute` is passed.
When AgentLab is active, brain-stage agents must be executed through DeepSeek
even for simulations and small tasks. DeepSeek failures block and ask the user
instead of falling back to Codex simulation.

## Aider Adapter

`aider_adapter.py` can build an Aider invocation plan for the Coder phase. It
does not install or run Aider. Use it when you want AgentLab to keep ownership
of planning, validation, and archival while Aider handles a tightly scoped edit.

Example:

```bash
python run_task.py prepare --task-id task_0001 --execution-backend aider
```
