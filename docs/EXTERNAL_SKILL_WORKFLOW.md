# External Skill Workflow

P1-A.1 closes the External Skill Registry workflow as a lightweight,
archivable, and testable loop. It does not add external execution.

## Current Support

- static ECC inventory
- external skill registry
- dry-run import
- disabled-by-default import
- skill usage ledger
- internal skill candidate proposal
- read-only MCP inspection

## Current Non-Support

- ECC execution
- AnySearch execution
- CodeGraph indexing
- external IDE handoff
- automatic internal skill generation
- source code copying
- license bypass

## Recommended Flow

```bash
./agentlab.sh external-skills scan-ecc
./agentlab.sh external-skills import-ecc --dry-run
./agentlab.sh external-skills import-ecc
./agentlab.sh external-skills list
./agentlab.sh external-skills incubate --task-id task_xxx
```

Equivalent module CLI:

```bash
python -m agent_runtime.external_skills_cli list
python -m agent_runtime.external_skills_cli scan-ecc
python -m agent_runtime.external_skills_cli import-ecc --dry-run
python -m agent_runtime.external_skills_cli incubate --task-id task_xxx
```

## Artifact Paths

Real runtime outputs are ignored by git:

```text
artifacts/external_skill_inventory.json
projects/AgentLab/runs/<task_id>/artifacts/internal_skill_candidates.yml
projects/AgentLab/runs/<task_id>/artifacts/skill_incubation_report.md
```

Tracked example inventory:

```text
examples/external_skill_inventory.example.json
```

## Safety Closure

- `scan-ecc` performs static file reads only.
- missing ECC path writes `found=false` plus warnings and does not crash.
- `import-ecc --dry-run` never modifies the registry.
- imported external skills remain disabled and `inventory_only`.
- unknown license requires review.
- incubation writes candidate/report artifacts only; it does not create real
  internal skill files and does not copy third-party source code.

## MCP Read-Only Inspection

`agentlab_get_skill_incubation_candidates` first reads a task artifact if it
exists, otherwise computes candidates in memory from registry + usage ledger. It
does not write files, modify registry state, or execute external tools. Absolute
local paths are redacted to repository-relative paths or basenames.