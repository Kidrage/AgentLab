# AgentLab Repo Map

## Root

- `README.md`: User-facing overview and operation notes.
- `OPERATING_MODEL.md`: Split between DeepSeek management and Codex execution.
- `CLI_ROADMAP.md`: CLI evolution plan.
- `agentlab.sh`: One-command wrapper for the Typer CLI.

## Runtime

- `agent_runtime/run_task.py`: CLI entrypoint.
- `agent_runtime/agent_runner.py`: Agent message composition and model execution wrapper.
- `agent_runtime/llm_provider.py`: Provider adapters and Codex handoff fallback.
- `agent_runtime/brain_governor.py`: Traversal and token governance.
- `agent_runtime/cost_tracker.py`: Project and task cost ledger updates.
- `agent_runtime/workflow_plan.py`: Visible task planning.
- `agent_runtime/task_router.py`: Route selection.

## Configuration

- `config/agent_registry.yml`: Agent capabilities and routing identity.
- `config/model_profiles.yml`: Agent-to-model profiles.
- `config/model_providers.yml`: Provider definitions.
- `config/routing_rules.yml`: Route hints and task-size policy.
- `config/budget_profiles.yml`: Token budget estimates.
- `config/brain_governance.yml`: Traversal, loop, and user-decision rules.

## UI

- `web_ui/index.html`: Static status dashboard shell.
- `web_ui/styles.css`: Dashboard layout and visual states.
- `web_ui/app.js`: Status rendering logic and data contract.
- `web_ui/agent_status.sample.json`: Future service-compatible sample payload.

## Project Memory

- `projects/AgentLab/agent_docs/07_DEVELOPMENT_LOG.md`: Module-based development log.
- `projects/AgentLab/agent_docs/08_CODEX_DIALOGUE_LOG.md`: User-visible Codex action log.
- `projects/AgentLab/agent_docs/09_COST_LEDGER.yml`: Manual/API cost ledger.
