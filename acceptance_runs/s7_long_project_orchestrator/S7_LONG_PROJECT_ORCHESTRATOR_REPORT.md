# AgentLab S7 Long Project Orchestrator Report

## Verdict
PASS.

## Summary
S7 adds deterministic long-project state: project brief, roadmap, milestone graph, phase plans, next actions, phase acceptance, compact summaries, and snapshots.

## Goals Achieved
- Long prompts are converted into roadmap/phase artifacts instead of direct execution.
- Each phase has explicit outputs, evidence requirements, acceptance criteria, risks, and human decision points.
- Project brain can resume from acceptance history and compute the next phase.
- Context compression writes summaries/snapshots rather than preserving raw history in prompt context.

## Safety
- No LLM calls.
- No network access.
- No external executor dispatch.
- Phase close requires evidence.

## Verification
Actual verification passed:

```bash
python -m compileall agent_runtime/program_manager agent_runtime/executors agent_runtime/run_task.py tests/test_s7_long_project_orchestrator.py tests/test_s8_executor_connector.py
python -m pytest -q tests/test_s7_long_project_orchestrator.py tests/test_s8_executor_connector.py  # 10 passed
python -m pytest -q tests/test_s7_long_project_orchestrator.py tests/test_s8_executor_connector.py tests/test_s6_recovery_brain.py tests/test_p2_executor_result_ingestion.py tests/test_cli_contract.py  # 62 passed
python scripts/audit_text_integrity.py --fail-on-suspicious  # suspicious files: 0
./agentlab.sh --help
./agentlab.sh run-pipeline --help
```

Target commands:

```bash
python -m pytest -q tests/test_s7_long_project_orchestrator.py
./agentlab.sh project-brain-init --help
./agentlab.sh project-plan --help
./agentlab.sh project-next --help
./agentlab.sh phase-accept --help
```

## Smoke Evidence
- S7→S8 smoke generated project brain, phase plan, and phase summary under `/tmp/agentlab_s7s8_smoke`.
