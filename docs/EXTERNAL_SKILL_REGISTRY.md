# External Skill Registry

AgentLab is a local-first AgentOps control layer. It can use external skill providers such as ECC, AnySearch, CodeGraph, Cline/Codex, but it does not blindly depend on them. AgentLab tracks cost, resources, evidence, skill usage, and internal skill incubation.

`config/external_skill_registry.yml` records external skills as metadata:

- `skill_id`: globally unique id such as `ecc.planner`.
- `source`: one of `ecc`, `anysearch`, `codegraph`, `agentlab_internal`, `custom_local`.
- `integration_mode`: currently `inventory_only` by default.
- `enabled`: dispatch gate; imported ECC skills default to `false`.
- `capabilities` and `suitable_task_types`: routing hints, not execution permission.
- `risk`, `license`, `cost`, `fallback`: governance metadata for future dispatch.

Disabled external skills cannot be dispatched. The registry API supports load, write, add/update, disable, uniqueness validation, and dispatchability checks. License `unknown` is flagged with `license_review_required: true`.

This registry does not vendor external source code, execute tools, or bypass CostLedger / ResourceLedger / ArtifactGate controls.

## Workflow CLI

Use the lightweight closure commands to inspect and import metadata only:

```bash
./agentlab.sh external-skills list
./agentlab.sh external-skills import-ecc --dry-run
./agentlab.sh external-skills import-ecc
```

`list` reads only `config/external_skill_registry.yml` and prints `skill_id`,
`source`, `enabled`, `capabilities`, risk level, and license review status. It
does not execute external tools.

Imported ECC skills remain:

- `enabled: false`
- `integration_mode: inventory_only`
- `risk.requires_approval: true`
- `license.license_review_required: true` when license is unknown

Validation helpers live in `agent_runtime/skills/config_validation.py` and check
unique `skill_id`, disabled-by-default external imports, unknown license review,
and policy safety requirements.
# P1-C/D External Provider Entries

`config/external_skill_registry.yml` includes disabled adapter entries for
`anysearch.web_research` and `codegraph.repo_index`. These are external
providers, not core AgentLab dependencies. Usage is recorded in
`skill_usage_ledger.yml`, and repeated successful usage may propose internal
checklist or strategy candidates without copying third-party source code.
