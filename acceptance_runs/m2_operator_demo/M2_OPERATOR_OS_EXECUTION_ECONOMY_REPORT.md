# M2 Operator OS Execution Economy Report

created_at: 2026-06-25T04:05:37.568523+00:00
project: AgentLab
status: pass

## CI Evidence

implementation commit: 2167c7b2953b6a689058330abba33c7b43a3709d
closure fix commit: pending
CI run URL: pending
CI conclusion: pending
full pytest: 1707 passed, 2 skipped, 11 warnings in 222.83s
focused M2-12 pytest: 34 passed in 6.28s
compileall: PASS
text integrity: PASS
CLI smoke: PASS

## Summary

- migration status: pass
- worker count: 21 total, 13 installed
- role matrix: 9 roles
- route decision: claude_code for Coder
- approval example: approved_for_demo_only
- cost estimate: $0.0000

## Evidence Artifacts

- runtime_hygiene_summary: `runtime_hygiene_summary.yml`
- migration_doctor_summary: `migration_doctor_summary.yml`
- worker_registry_summary: `worker_registry_summary.yml`
- role_requirement_matrix_summary: `role_requirement_matrix_summary.yml`
- worker_audition_scorecard: `worker_audition_scorecard.yml`
- route_decision_example: `route_decision.yml`
- approval_decision_card: `approval_decision_card.yml`
- cost_estimate_and_ledger: `cost_estimate_and_ledger.yml`
- mock_executor_result: `mock_executor_result.yml`
- phase_acceptance: `phase_acceptance.yml`
- timeline_excerpt: `timeline_excerpt.yml`
- ui_smoke: `ui_smoke.yml`
- assistant_explanations: `assistant_explanations.md`
- report: `M2_OPERATOR_OS_EXECUTION_ECONOMY_REPORT.md`

## Migration Readiness vs Demo Acceptance

M2-12 operator demo is CI-safe and local-only.
Private infrastructure checks are recorded but do not block the demo unless `--strict-migration` is enabled.

- strict_migration: false
- demo_blocking_failures: 0
- private_infra_deferred_items: 0
- migration_readiness_warnings: 0

Deferred private infrastructure:
- TrueNAS/SSH/SMB
- WebUI auth token
- model API keys
- GitHub backup token when backup is disabled / source remote is SSH

- none

## Acceptance Checklist

- PASS: runtime hygiene passes without demo blocking failures
- PASS: worker registry summary exists
- PASS: all 9 roles have capability requirements
- PASS: mock worker audition scorecard exists
- PASS: route decision is explainable
- PASS: approval decision card exists
- PASS: cost ledger example exists
- PASS: timeline excerpts exist
- PASS: TUI smoke evidence exists
- PASS: WebUI smoke evidence exists
- PASS: mock executor result ingested
- PASS: phase acceptance passes
- PASS: no real external execution required

## Safety Notes

- This demo uses mock executor results only.
- No external agent dispatch, network model call, platform posting, or skill installation is performed.
- WebUI/TUI checks are smoke evidence, not mutation routes.

## Known Limitations

- WebUI approval mutation remains deferred from M2-11.
- GitHub backup token is optional for this project because project GitHub backup is disabled.
- M2-12.5 /goal command bridge is not implemented by this demo.
