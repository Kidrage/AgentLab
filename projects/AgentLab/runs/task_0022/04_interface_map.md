# Interface Map

## Interfaces Affected

| Interface | Type | Change |
|---|---|---|
| agentlab.sh (CLI wrapper) | Shell script | Add 6 new codex-* commands |
| agent_runtime/run_task.py (CLI) | Python/typer | Add 6 new typer commands (codex_start, codex_status, codex_handoff, codex_resume, codex_verify_artifacts, continue_with_api) |
| config/execution_modes.yml | YAML config | New config file defining 3 execution modes |
| DRIVER_PROTOCOL.md | Documentation | Add codex_full_driver mode definition, update mode switching rules |
| docs/ | New directory | New spec document |
| agent_templates/ | New directory/codex_full_driver/ | 10 new role templates |

## Existing Contracts

| Interface | Current behavior | File |
|---|---|---|
| agentlab.sh | Delegates to agent_runtime/run_task.py via exec | agentlab.sh |
| run_task.py run-agent | Runs a single agent via CLI, has Coder handoff gate | agent_runtime/run_task.py |
| run_task.py init-task | Creates task folder and templates | agent_runtime/run_task.py |
| run_task.py prepare | Builds workflow plan | agent_runtime/run_task.py |
| run_task.py status | Shows task state | agent_runtime/run_task.py |
| DRIVER_PROTOCOL.md | Defines codex_coder_only mode, Codex Plus rules | DRIVER_PROTOCOL.md |
| config/ | Various YAML configs for execution, routing, budgets | config/ |

## Proposed Contract Changes

| Interface | New behavior | Compatibility risk |
|---|---|---|
| agentlab.sh | Accept `codex-start`, `codex-status`, `codex-handoff`, `codex-resume`, `codex-verify-artifacts`, `continue-with-api` as commands | None — additive |
| agent_runtime/run_task.py | Add 6 new typer commands with `codex_` prefix | None — additive |
| DRIVER_PROTOCOL.md | Add "codex_full_driver" mode, update Coder mode switching table | Low — documentation only |
| config/execution_modes.yml | New config with 3 modes: api_native, codex_coder_only, codex_full_driver | None — new file |

## File Schema Changes
- No existing file schemas are changed. All new files use the same YAML/Markdown patterns as existing AgentLab files.

## CLI Command Changes

New commands:

```bash
./agentlab.sh codex-start --project <ProjectName> --task-id <task_id> --request-file <path> --mode full-driver
./agentlab.sh codex-status --project <ProjectName> --task-id <task_id>
./agentlab.sh codex-handoff --project <ProjectName> --task-id <task_id>
./agentlab.sh codex-resume --project <ProjectName> --task-id <task_id> --from handoff_packet.yml
./agentlab.sh codex-verify-artifacts --project <ProjectName> --task-id <task_id>
./agentlab.sh continue-with-api --project <ProjectName> --task-id <task_id> --from handoff_packet.yml
```

These commands delegate to the new Python modules: codex_artifact_validator.py, handoff_builder.py, api_continuation.py.

## Backward Compatibility
- All existing commands unchanged
- All existing file formats unchanged
- New execution_modes.yml is purely additive (not referenced by existing code yet)
- DRIVER_PROTOCOL.md additions are documentation-only

## Migration Notes
- No migration needed — all new features are additive
- Existing agentlab.sh, run_task.py, and config files remain fully backward-compatible

## Next Agent
CodexPromptGenerator