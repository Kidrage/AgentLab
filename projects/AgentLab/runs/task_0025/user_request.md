# User Request

## Original Request
Fix AgentLab lifecycle closure and artifact completeness. Raise overall evaluation from 65% to ≥85%.

## Problem
- Task Lifecycle: 0/20 — no lifecycle state machine exists
- Artifact Completeness: 0/15 — no rigorous artifact contract enforcement
- Overall: 65/100 → target: ≥85/100

## Required Deliverables
1. agent_runtime/lifecycle_graph.py — lifecycle state machine
2. agent_runtime/artifact_contract.py — rigorous artifact validation
3. agent_runtime/fake_provider.py — deterministic dry-run outputs
4. agent_runtime/pipeline_runner.py — dry-run pipeline executor
5. CLI commands: run-next, run-pipeline, lifecycle-status, artifact-check
6. Update evaluation to properly score lifecycle and artifacts
7. Run full dry-run lifecycle proving closure
8. Final evaluation ≥85/100

## Constraints
- No real LLM API calls in tests
- No LangGraph migration
- Local-first, CLI-first
- All artifacts must be produced or explicitly skipped