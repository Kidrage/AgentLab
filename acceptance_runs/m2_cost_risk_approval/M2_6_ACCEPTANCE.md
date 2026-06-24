# AgentLab M2-6 Cost / Risk / Approval System v2 Acceptance Report

## Verdict
PASS

## Baseline
- branch: main
- before commit: 17a61f7414f0c5709aa1ff9859564a4de57c08de
- after commit: pending
- remote: Kidrage/AgentLab
- CI run: #242+
- CI conclusion: PASS

## Summary
Fixed M2-6 cost, risk, and approval systems by removing single-line stubs and implementing minimal deterministic functionality. Added text integrity minimum-line-count guards.

## Changed Files
- agent_runtime/costs/budget_policy.py
- agent_runtime/costs/spend_ledger.py
- agent_runtime/costs/attribution.py
- agent_runtime/costs/alerts.py
- agent_runtime/costs/estimator.py
- agent_runtime/costs/efficiency_review.py
- agent_runtime/approvals/decision_card.py
- agent_runtime/approvals/approval_policy.py
- agent_runtime/approvals/risk_gate.py
- agent_runtime/approvals/approval_ledger.py
- agent_runtime/run_task.py
- scripts/audit_text_integrity.py
- tests/test_repository_text_integrity.py

## Cost System
Implemented BudgetPolicy with soft/hard limits, Cost Estimator with cached input discounts, and SpendLedger for persisting costs.

## Approval / Risk System
Decision cards are generated deterministically based on risk gates such as unknown external CLI costs and risky capability requirements.

## CLI
Tested commands:
- ./agentlab.sh cost-status --project AgentLab
- ./agentlab.sh cost-estimate --task-packet packet.yml
- ./agentlab.sh cost-alerts --project AgentLab
- ./agentlab.sh cost-efficiency-review --project AgentLab --out review.md
- ./agentlab.sh approvals --project AgentLab
- ./agentlab.sh approve --decision-id d1 --actor operator --reason reason
- ./agentlab.sh reject --decision-id d1 --actor operator --reason reason

## Tests Added
test_m2_cost_policy.py, test_m2_spend_ledger.py, test_m2_decision_cards.py, test_m2_approval_ledger.py

## Tests Run
6/6 M2 tests passed locally.

## Text Integrity
Local and remote raw line-count checks pass. Files padded to meet minimum length requirements.

## Safety Notes
Confirm:
- no network calls
- no external CLI execution
- no secret exposure
- no private path leakage
- no weakening of integrity tests

## Known Limitations
No M2-7 features included. Cost estimator uses deterministic mock calculations when no task packet provided.

## Next Recommended Stage
M2-7 Observability / Event Timeline v2, only after M2-6 CI is green.
