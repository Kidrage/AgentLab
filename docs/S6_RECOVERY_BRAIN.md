# S6 Recovery Brain / Alternative Route Planner

S6 extends the older P2 recovery loop from retry diagnostics into deterministic
route planning. It does not execute the selected route. It writes artifacts that
tell the user or supervisor what should happen next and which approval gate is
required.

## Boundary

- no automatic external agent dispatch;
- no skill installation or execution;
- no live web/network enablement;
- no infinite retry;
- missing or fake evidence is a hard fail for factual claims.

## CLI

```bash
./agentlab.sh recovery-brain-plan \
  --failure-type evidence_missing \
  --mission-contract examples/mission_contracts/research_company.yml \
  --evidence-ledger acceptance_runs/s5_evidence_recovery_intelligence/evidence_ledger.yml \
  --out acceptance_runs/s6_recovery_brain
```

## Outputs

`recovery-brain-plan` writes:

- `recovery_strategy_plan.yml`;
- `alternative_route_plan.yml`;
- `capability_gap_decision_card.yml`;
- `fake_evidence_report.yml`;
- `phase_acceptance_evidence.yml`;
- `recovery_strategy_ledger.yml`.

## Failure taxonomy

S6 recognizes:

- `tool_unavailable`;
- `network_blocked`;
- `provider_failed`;
- `skill_missing`;
- `skill_failed`;
- `artifact_failed_validation`;
- `quality_failed`;
- `agent_hallucinated`;
- `evidence_missing`;
- `permission_missing`;
- `context_insufficient`;
- `budget_exceeded`;
- `capability_gap`;
- `unknown`.

## Acceptance

S6 is acceptable when:

- `evidence_missing` and ungrounded factual claims produce a hard fail;
- missing skills recommend skill discovery, not direct execution;
- missing vision/audio/web/shell/external-executor capability produces a human
  decision card;
- provider failures recommend an approved alternate or a safe stop;
- budget failures recommend a smaller/degraded route;
- every route plan writes a ledger entry;
- no route allows unbounded retries.