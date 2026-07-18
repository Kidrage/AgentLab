# AgentLab Runtime

`agent_runtime/` implements AgentLab's local task orchestration, role dispatch,
state, evidence, validation, recovery, and artifact governance.

## Authority Boundaries

- `config/routing_rules.yml`: route membership and order.
- `config/production_packs.yml`: domain lifecycle and output contracts.
- `config/agent_registry.yml`: role permissions, inputs, outputs, and templates.
- `config/agent_model_profiles.yml`: role backend/model selection.
- `config/worker_invocation_contracts.yml`: CLI command contracts.
- `config/model_capacity.yml`: approved same-role fallback routes.
- `config/execution_modes.yml`: AgentLab workflow driver to backend-mode mapping.

Runtime code may enforce these contracts but must not maintain a second
hard-coded role chain, model table, or active template registry.

## Planning And Execution

```text
mission_contract
-> route_decision
-> production_pack
-> workflow_plan
-> lifecycle / role sessions
-> validation and independent review
-> handoff or approved promotion
```

`workflow_plan.py` builds a plan without model calls. The default driver is
`agentlab_orchestrated_cli`, which resolves to the `full_cli` role matrix. Each
role may use a different worker; the driver does not make one CLI shell the task
host.

`run_task.py` exposes the CLI. `pipeline_runner.py` advances the configured
lifecycle, and `agent_runner.py` composes one role's bounded context and invokes
the resolved backend. `cli_executor.py` renders the registered CLI contract and
writes execution receipts.

```bash
./agentlab.sh prepare --project <Project> --task-id <task_id> --write-plan
./agentlab.sh run-agent <Role> --project <Project> --task-id <task_id> --execute
./agentlab.sh run-pipeline --project <Project> --task-id <task_id> --execute
```

Without `--execute`, execution commands remain dry-run/local planning paths.
No provider, model, or worker may be silently substituted.

## State And Artifacts

- Run state: `projects/<Project>/runs/<task_id>/`.
- Candidate capture: `projects/<Project>/runs/<task_id>/artifacts/`.
- Formal deliverables: `projects/<Project>/production/` after declared review,
  approval, and promotion.
- Durable project facts: project brain and artifact index files declared by the
  relevant production pack.
- Runtime/daemon/watchdog state: `.agentlab_runtime/`, never a project fact.

Persistent runtime writes should use `atomic_io.py`. Route-specific validators
must derive required evidence from the production pack and role contracts, not
from a fixed code-task report list.

## Workers And Adapters

Workers such as Hermes, Claude Code, Codex, Aider, Agy, Grok, and Qwen are
registered execution surfaces. A worker becomes usable for a role only when its
role binding, invocation contract, model profile, and capability requirements
all pass.

The retired standalone Aider plan builder did not participate in workflow
execution and has been removed. Aider remains available through the normal
registered Coder worker contract; it does not have a separate planning path.

## Verification

Use focused tests during edits and the complete suite for shared runtime or
authority changes. Default tests must not start live providers or production
tasks. See `docs/TEST_SUITE_GOVERNANCE.md`.
