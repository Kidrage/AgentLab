# AgentLab CLI Roadmap

AgentLab is being developed as a personal, local-first development workflow.
The CLI comes first; a UI can later sit on top of the same files and Python APIs.

## Execution Split

- DeepSeek API handles low-cost management and reasoning agents.
- Codex Plus handles real code edits, file changes, and project commands.
- If DeepSeek is unavailable, AgentLab writes a Codex fallback handoff file.

## Current CLI Contract

- `init-task`: create a task run folder and placeholder reports.
- `prepare`: build `workflow_plan.yml` from config, memory, and user request.
- `status`: inspect task state, route, missing inputs, and report files.
- `models`: inspect providers and model profiles without exposing secrets.
- `run-agent`: dry-run or execute one agent through the configured model API.

`run-agent` is dry-run by default. It calls a model only with `--execute`.

## Model Switching

Provider config lives in:

```text
config/model_providers.yml
```

Agent profile config lives in:

```text
config/model_profiles.yml
```

Environment values live privately in `.env`, based on:

```text
agent_runtime/.env.example
```

The initial provider path is OpenAI-compatible:

- DeepSeek: `LLM_PROVIDER=deepseek`
- OpenAI: `LLM_PROVIDER=openai`

Per-run overrides are available:

```bash
./agentlab.sh run-agent Supervisor --provider deepseek --model Deepseek-V4-Pro
./agentlab.sh run-agent Supervisor --provider openai --model <model-id>
```

Coder is configured as `codex_plus_manual`, so it is not called through DeepSeek
API. Use Codex directly for the implementation stage, then write/update
`implementation_report.md`.

## Future UI Boundary

A future UI should call the same runtime modules:

- `workflow_plan.build_workflow_plan`
- `state_store.load_state`
- `state_store.save_state`
- `agent_runner.compose_agent_messages`
- `agent_runner.run_agent_model`

The UI should not bypass `workflow_plan.yml`, `state.yml`, or the validation
gates. Those files are the audit trail.
