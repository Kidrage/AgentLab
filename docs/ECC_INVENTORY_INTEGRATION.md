# ECC Inventory Integration

ECC is treated as an external agent/skill provider. AgentLab does not vendor ECC code. AgentLab does not enable all ECC tools by default. AgentLab scans ECC inventory, imports selected capabilities as disabled external skills, and later creates handoff tasks.

Configuration lives in `config/ecc_integration.yml`:

- `enabled: false`
- `mode: inventory_only`
- local path candidates: `${ECC_HOME}`, `./external/everything-claude-code`, `./external/ECC`
- scan limits: `max_files`, `max_file_kb`
- import policy defaults: commands, hooks, and MCP servers are not enabled

The scanner in `agent_runtime/external_agents/ecc_inventory.py` only performs static inventory:

- scans `AGENTS.md`, `README.md`, `skills/**/SKILL.md`, `commands/**`, `*.yml`, `*.yaml`, `*.json`
- emits `artifacts/external_skill_inventory.json` when requested
- records partial results and warnings when paths are missing or files exceed limits
- records hooks / commands / MCP server declarations as disabled metadata only

Explicitly not supported in P1-A:

- No ECC execution yet.
- No external scripts are executed.
- No hooks are loaded.
- No MCP servers are started.
- No automatic source code copying.

## Artifact Paths

Real scan output is local runtime state and is ignored by git:

```text
artifacts/external_skill_inventory.json
```

A small mock example is tracked at:

```text
examples/external_skill_inventory.example.json
```

The repository root must not be used for real `external_skill_inventory.json`.

## CLI

```bash
./agentlab.sh external-skills scan-ecc
./agentlab.sh external-skills import-ecc --dry-run
./agentlab.sh external-skills import-ecc
```

`scan-ecc` is static-only. If the ECC path does not exist, it writes
`found=false`, records a warning, and exits successfully because missing ECC is
not fatal.
