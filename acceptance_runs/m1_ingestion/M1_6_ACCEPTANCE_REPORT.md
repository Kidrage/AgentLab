# M1-6 Document / Code / Media Ingestion v1 — Acceptance Report

Date: 2026-06-20

## Verdict
PASS

## Baseline
- branch: main
- before commit: 17ed37e
- after commit: (to be committed)
- remote: origin/main
- CI: N/A (local verification)

## Summary
Added deterministic mock-based ingestion contracts for document, code, and media artifacts. All providers are mock-only — no external tools are executed. Ingestion outputs enter evidence ledger via structured YAML results with quality reports.

## Changed Files
- `agent_runtime/ingestion/__init__.py` — added M1-6 exports, guarded legacy imports against missing transitive deps
- `agent_runtime/ingestion/ingestion_contract.py` — core dataclasses (IngestionContract, IngestionResult, QualityReport)
- `agent_runtime/ingestion/document_ingestion.py` — MarkItDown/MinerU mock document ingestion
- `agent_runtime/ingestion/code_ingestion.py` — codebase-memory/Graphify mock code ingestion
- `agent_runtime/ingestion/media_ingestion.py` — Supervision mock media ingestion
- `agent_runtime/run_task.py` — added `ingest-artifact` and `ingest-repo-memory` CLI commands
- `acceptance_runs/m1_executor_connector_loop/M1_5_ACCEPTANCE_REPORT.md` — fixed local absolute path leak

## New Configs
- `config/ingestion_providers.yml` — 5 provider registries (markitdown, mineru, codebase_memory, graphify, supervision)
- `config/document_ingestion_policy.yml` — document ingestion policy (extensions, size limits, quality checks)
- `config/media_ingestion_policy.yml` — media ingestion policy (extensions, size limits, quality checks)

## New CLI
- `./agentlab.sh ingest-artifact --project <name> --path <file> --provider <provider>`
- `./agentlab.sh ingest-repo-memory --project <name> --repo <path> --provider <provider>`

## Artifacts Produced
- `{artifact_id}_ingestion_result.yml` — structured ingestion result with quality, provenance, warnings

## Tests Added
- `tests/test_m1_ingestion_contracts.py` — 7 tests: contract validation, result serialization, provider enumeration
- `tests/test_m1_document_ingestion_mock.py` — 8 tests: markitdown mock, mineru mock, missing file, unsupported provider, quality pass/fail, real tempfile
- `tests/test_m1_code_ingestion_mock.py` — 7 tests: codebase-memory mock, graphify mock, missing path, unsupported provider, no-python warning, quality pass/fail
- `tests/test_m1_media_ingestion_mock.py` — 10 tests: image/video/audio mock, missing file, unsupported provider, empty file, large file warning, quality pass/fail, real tempfile

## Tests Run
```
tests/test_m1_ingestion_contracts.py ...................          [ 21%]
tests/test_m1_document_ingestion_mock.py ...................... [ 46%]
tests/test_m1_code_ingestion_mock.py .......................     [ 68%]
tests/test_m1_media_ingestion_mock.py .........................  [100%]

32 passed in 1.19s
```

## Safety Notes
- No external project code is executed
- All providers are mock-only
- MinerU requires explicit approval (policy flag)
- No network, shell, or MCP launch
- No secrets or private paths in output
- Legacy ingestion imports guarded with try/except

## Known Limitations
- Mock providers produce deterministic but fake output — real providers need adapter approval gates
- Code ingestion symbol scanning is file-count based, not AST-aware
- Media ingestion does not run actual ML models
- Quality assessment uses simple heuristics

## Next Recommended Stage
M1-7: Phase Acceptance v1 (phase-level governance checkpoints with accept/retry/redesign/split/rollback/ask_user)
