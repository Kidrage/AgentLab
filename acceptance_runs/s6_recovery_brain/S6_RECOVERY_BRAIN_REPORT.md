# S6 Recovery Brain Report

## Verdict

PASS.

## Scope

S6 adds deterministic alternative route planning on top of existing P2 recovery
artifacts. It does not execute routes, install skills, call providers, enable
network access, or dispatch external agents.

## Added

- `agent_runtime/recovery/failure_taxonomy.py`
- `agent_runtime/recovery/strategy_search.py`
- `agent_runtime/recovery/alternative_route_planner.py`
- `agent_runtime/recovery/capability_gap_resolver.py`
- `agent_runtime/recovery/escalation_policy.py`
- `agent_runtime/recovery/fake_evidence_detector.py`
- `./agentlab.sh recovery-brain-plan`
- `config/recovery_strategy_policy.yml`
- `config/failure_taxonomy.yml`
- `config/evidence_integrity_policy.yml`
- `docs/S6_RECOVERY_BRAIN.md`
- `tests/test_s6_recovery_brain.py`

## Acceptance Evidence

- `recovery_strategy_plan.yml` records `failure_type: evidence_missing`,
  `next_action: stop_safely`, `max_attempts: 0`, and `auto_execute: false`.
- `alternative_route_plan.yml` records `no_infinite_retry: true` and ledger
  writing enabled.
- `capability_gap_decision_card.yml` records the mission capabilities and keeps
  install/external execution approval-gated.
- `fake_evidence_report.yml` enforces source hashes and line references for
  factual-claim readiness.
- `phase_acceptance_evidence.yml` records generated S6 artifacts, no infinite
  retry, and ledger evidence.

## Verification

```bash
./agentlab.sh recovery-brain-plan \
  --failure-type evidence_missing \
  --mission-contract examples/mission_contracts/research_company.yml \
  --evidence-ledger acceptance_runs/s5_evidence_recovery_intelligence/evidence_ledger.yml \
  --out acceptance_runs/s6_recovery_brain
# ok: failure_type=evidence_missing; next_action=stop_safely; evidence_verdict=pass

python -m compileall agent_runtime/recovery agent_runtime/run_task.py
# pass

python -m pytest -q tests/test_s6_recovery_brain.py tests/test_cli_contract.py
# 48 passed

python -m pytest -q tests/test_s6_recovery_brain.py tests/test_cli_contract.py tests/test_p2_i_recovery.py tests/test_s5_evidence_recovery_planning.py
# 83 passed

python scripts/audit_text_integrity.py --fail-on-suspicious
# suspicious_count: 0; verdict: PASS

./agentlab.sh repo-hygiene-check
# status: fail; existing blocker is root-level handoff file
# "# AgentLab S0-S12 Mainline Repair Handof.md" outside repository constitution.
```

## Boundary

S6 remains planning-only. It does not execute recovery routes, install skills,
enable live web access, call providers, or dispatch external agents.

## Known Hygiene Blocker

`repo-hygiene-check` is still blocked by the root-level handoff file used to
drive this repair session. The file is untracked and was not moved or deleted to
avoid losing user-provided handoff context.