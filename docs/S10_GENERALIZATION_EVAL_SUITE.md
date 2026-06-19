# S10 Generalization Eval Suite and CI Gates

## Purpose

S10 adds an offline-only generalization evaluation layer for AgentLab. It verifies that core behavior remains stable across several task domains without calling real model APIs, web providers, media backends, databases, GitHub, or external agents.

## Fixture domains

The suite covers these required domains:

- docs
- cli
- capability_gap
- recovery
- project_brain
- search_repo_mock

Fixtures live in:

- config/generalization_fixtures.yml

Each fixture declares:

- fixture_id
- domain
- request
- expected_route
- required_artifacts
- offline_only
- allow_external_execution

## Evaluator

Runtime module:

- agent_runtime/evaluation/generalization_suite.py

Outputs:

- generalization_results.yml
- S10_GENERALIZATION_EVAL_REPORT.md
- per-fixture mock artifacts under fixtures/

## CLI

Run the suite:

```bash
./agentlab.sh eval-generalization --out acceptance_runs/s10_generalization_eval
```

Print local CI gates without running them:

```bash
./agentlab.sh ci-gates --dry-run
```

Run local CI gates:

```bash
./agentlab.sh ci-gates
```

## CI gate policy

Policy lives in:

- config/ci_gate_policy.yml

Current gates include:

- text integrity audit
- compileall
- focused S9/S10 tests
- S10 generalization suite
- CLI help checks

## Safety invariants

- offline_only is true
- allow_external_execution is false
- fixtures only create deterministic local artifacts
- no provider credentials are required
- no real model, web, browser, media, OCR, DB, GitHub, or external-agent execution occurs
