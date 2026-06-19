# S10 Generalization Eval Report

## Verdict: PASS

## Baseline

S10 is additive on top of S9 Capability Fabric. The suite is offline-only and uses static fixtures from config/generalization_fixtures.yml.

## Summary

- Total fixtures: 6
- Passed: 6
- Failed: 0
- Offline only: true
- External execution: blocked

## New Runtime and Config

- agent_runtime/evaluation/generalization_suite.py
- config/generalization_fixtures.yml
- config/ci_gate_policy.yml
- docs/S10_GENERALIZATION_EVAL_SUITE.md
- tests/test_s10_generalization_eval.py

## CLI

- ./agentlab.sh eval-generalization --out acceptance_runs/s10_generalization_eval
- ./agentlab.sh ci-gates --dry-run
- ./agentlab.sh ci-gates

## Fixture Results

### capability_gap_image

- Domain: capability_gap
- Expected route: evaluation_task
- Score: 1.0
- Pass: True

### cli_help_regression

- Domain: cli
- Expected route: small_task
- Score: 1.0
- Pass: True

### docs_only_release_note

- Domain: docs
- Expected route: small_task
- Score: 1.0
- Pass: True

### project_brain_status

- Domain: project_brain
- Expected route: evaluation_task
- Score: 1.0
- Pass: True

### recovery_plan_probe

- Domain: recovery
- Expected route: large_or_risky_task
- Score: 1.0
- Pass: True

### search_repo_mock

- Domain: search_repo_mock
- Expected route: research_sensitive_task
- Score: 1.0
- Pass: True

## Safety Notes

No fixture calls real web, real model APIs, real vision/audio backends, or external agents.
