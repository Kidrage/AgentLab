# Interface Map

## UI Layer

- `web_ui/index.html`: page shell and stable DOM targets.
- `web_ui/styles.css`: responsive dashboard layout and status states.
- `web_ui/app.js`: rendering logic, controls, and fallback snapshot.

## Data Layer

- `web_ui/agent_status.sample.json`: future-compatible status payload.
- `window.AgentLabUI`: small browser-side hook for later refresh/testing.

## Runtime Boundary

The Python runtime is unchanged in this task. Future work can add a CLI command
that generates the status snapshot from:

- `config/agent_registry.yml`
- `projects/<ProjectName>/runs/<task_id>/state.yml`
- `projects/<ProjectName>/runs/<task_id>/workflow_plan.yml`
- `projects/<ProjectName>/runs/<task_id>/cost_ledger.yml`
- `projects/<ProjectName>/runs/<task_id>/brain_decisions.yml`

## Integration Notes

The page works from `file://` using the embedded fallback snapshot. When served
over HTTP, it attempts to load `agent_status.sample.json`.
