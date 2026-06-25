# M2 Operator OS Execution Economy Report

created_at: 2026-06-25T03:38:33.267726+00:00
project: AgentLab
status: pass

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
