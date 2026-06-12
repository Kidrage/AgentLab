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
