# P2 Provider Performance & Cost Governance

## Positioning

P2-D aggregates execution, retry, and review artifacts into provider performance and cost governance. It does not execute providers. It does not modify router policy automatically. It generates recommendations for human review.

## Inputs

- `execution_ledger.yml`
- `retry_attempt_ledger.yml`
- `provider_scorecard.yml`
- `final_acceptance_receipt.yml`
- `final_rejection_receipt.yml`

## Outputs

- `provider_performance_profiles.yml`
- `provider_governance_decisions.yml`
- `cost_governance_report.yml`
- `cost_governance_report.md`
- `routing_recommendations.yml`
- `routing_recommendations.md`
- `provider_governance_report.md`

## Metrics

- `acceptance_rate`: accepted outcomes divided by attempts. If final receipts are not provider-specific, pass and pass-with-warnings verdicts are used as accepted outcomes.
- `retry_rate`: retry decisions or failed reviewed attempts divided by attempts.
- `blocked_rate`: blocked verdicts divided by attempts.
- `average_quality_score`: deterministic verdict score average where PASS is 1.0, PASS_WITH_WARNINGS is 0.75, NEEDS_REVISION is 0.35, FAIL is 0.1, and BLOCKED is 0.0.

## Decisions

- `HEALTHY`: enough data and no quality, retry, blocked, or cost findings.
- `WATCHLIST`: low acceptance or high retry rate.
- `DOWNGRADED`: average quality score below policy threshold.
- `QUARANTINE_RECOMMENDED`: repeated blocked outcomes or very low acceptance with enough data.
- `MANUAL_APPROVAL_REQUIRED`: unknown cost mode with policy requiring manual approval.
- `INSUFFICIENT_DATA`: fewer attempts than the scoring minimum.

## Safety Boundaries

- No real provider calls.
- No API key reads.
- No network.
- No external script execution.
- No router policy auto-write.
- Recommendation only.
- Mock provider metrics are test signals, not real external provider performance.

## CLI

```bash
python scripts/p2_provider_governance_check.py \
  --input-root . \
  --output governance_runs/p2_provider_governance_demo \
  --allow-quarantine-recommendations
```
