# AgentLab CLI Boundary

The CLI is a control surface over AgentLab state. It is not a second model
router and must not encode provider-specific defaults.

## Current Contract

- Task commands create, prepare, execute, pause, resume, inspect, and archive
  run-local state.
- `config/execution_modes.yml` selects the AgentLab workflow driver.
- `config/agent_model_profiles.yml` selects each role's worker/model.
- `config/worker_invocation_contracts.yml` owns command templates.
- Model and capacity changes use the `models` proposal/apply/doctor surfaces.
- Read-only status commands never trigger provider calls or mutate task state.

The Web UI, TUI, MCP server, and shell wrapper must call the same runtime APIs
and display resolved workflow-plan data. They may not maintain browser-local or
surface-local model assignments.

## Compatibility

Legacy execution-backend values remain parseable only for old workflow plans.
New tasks use an active driver. Full-driver commands and prompts are retired;
compatibility readers cannot start that mode or grant one shell the whole role
chain.

## Next CLI Work

Future CLI changes should reduce surfaces by sharing typed command handlers and
state projections. Add a command only when it exposes a durable runtime
capability that cannot be expressed clearly through an existing command family.
Provider-specific usage/status probes belong behind a common capacity interface,
while their exact syntax remains in worker/provider contracts.

The previous provider-specific roadmap is archived at
`docs/archive/root_agent_guides_legacy_20260718/CLI_ROADMAP.md`.
