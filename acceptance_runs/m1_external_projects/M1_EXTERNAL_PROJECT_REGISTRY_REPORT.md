# M1-1 External Project Registry Report

## Verdict

PASS

## Baseline

- Repository: `<repo-root>`
- Branch: `main`
- M0 commit before M1-1 edits: `9ce123e`
- Pre-M-series backup tag: `m-series-pre-m0-backup`

## Summary

Implemented the M1-1 External Project Registry + Capability Mapping slice as a
deterministic, registry-only capability reference system.

This stage records external open-source projects as possible capability
providers or reference implementations. It does not clone, vendor, install,
import, launch, or execute external project code.

## Changed Files

- `agent_runtime/external_projects/*`: registry models, loader, validation,
  capability mapping, adapter contract checks, and report rendering.
- `config/external_project_registry.yml`: 10 required external project records.
- `config/external_project_risk_policy.yml`: safe defaults and blocked actions.
- `config/external_project_capability_map.yml`: capability-to-provider map.
- `agent_runtime/run_task.py`: `external-projects` CLI group.
- `tests/test_m1_external_project_registry.py`: focused M1-1 coverage.
- `acceptance_runs/m1_external_projects/*`: risk report and this acceptance report.

## Registered Projects

- MinerU
- MarkItDown
- Codebase-Memory-MCP
- Graphify
- Supervision
- mattpocock/skills
- Ponytail
- Agent-Reach
- BabyAGI
- AiToEarn

## CLI Added

```bash
./agentlab.sh external-projects list
./agentlab.sh external-projects inspect --project mineru
./agentlab.sh external-projects capability-map --capability complex_document_ingestion
./agentlab.sh external-projects risk-report --out acceptance_runs/m1_external_projects
```

## Artifacts Produced

- `acceptance_runs/m1_external_projects/external_project_risk_report.yml`
- `acceptance_runs/m1_external_projects/external_project_risk_report.md`

## Tests Added

- `tests/test_m1_external_project_registry.py`

Coverage includes:

- deterministic registry loading
- duplicate `project_id` rejection
- default disabled enforcement
- registry-only integration enforcement
- high-risk approval enforcement
- no shell/network permission defaults
- capability lookup
- config parse and map consistency
- CLI list/inspect/capability-map/risk-report

## Tests Run

```bash
python -m pytest -q tests/test_m1_external_project_registry.py
```

Result:

```text
7 passed in 0.67s
```

```bash
python -m pytest -q tests/test_m1_external_project_registry.py tests/test_s9_capability_fabric.py
```

Result:

```text
16 passed in 0.88s
```

```bash
python -m pytest -q
```

Result:

```text
1209 passed, 2 skipped, 11 warnings in 117.47s
```

```bash
python -m compileall agent_runtime agentlab_app.py
./agentlab.sh external-projects list
./agentlab.sh external-projects capability-map --capability complex_document_ingestion
./agentlab.sh external-projects risk-report --out acceptance_runs/m1_external_projects
./agentlab.sh --help
./agentlab.sh run-pipeline --help
python scripts/audit_text_integrity.py --fail-on-suspicious
git diff --check
```

Result: PASS.

## Safety Notes

- All registered projects have `default_enabled: false`.
- All registered projects have `integration_stage: registry_only`.
- All registered projects have `network: false` and `shell: false`.
- High-risk projects require approval.
- External project code is not cloned, vendored, imported, installed, launched, or executed.
- The risk report explicitly records `no_external_code_execution`, `no_clone`, and `no_install`.

## Known Limitations

- M1-1 only provides the registry and mapping layer.
- No real adapters are implemented.
- No external project execution is permitted.
- Capability mappings are static config entries and should be reviewed as real adapters are later proposed.

## Next Recommended Stage

Proceed to M1-2 Mission Compiler v2.

M1-2 should compile rough project prompts into mission contracts with project
type, scale, capabilities, artifacts, acceptance gates, risk flags, approval
points, and external executor needs.
