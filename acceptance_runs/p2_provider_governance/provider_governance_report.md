# AgentLab Provider Performance & Cost Governance Report

## Summary
Processed 1 provider profile(s) and generated recommendation-only routing feedback.

## Input Artifacts
- execution_ledgers: 14
- retry_attempt_ledgers: 3
- provider_scorecards: 3
- final_receipts: 3

## Provider Performance
- agentlab.mock_patch: attempts=5, acceptance_rate=0.4, retry_rate=0.6, blocked_rate=0.0, average_quality_score=0.61, trend=stable

## Cost Governance
- agentlab.mock_patch: cost_mode=none, risk=low, manual_approval=False

## Governance Decisions
- agentlab.mock_patch: WATCHLIST (acceptance rate below watchlist threshold)

## Watchlist
- agentlab.mock_patch: acceptance rate below watchlist threshold

## Quarantine Recommendations
- None

## Routing Recommendations
- agentlab.mock_patch: watchlist; apply_automatically=False

## Safety Notes
- Governance reads local artifacts only.
- It does not call Codex, Cline, ECC, API models, MCP servers, or network resources.
- It never modifies executor_router.yml automatically.
- Mock provider metrics are test signals, not real external provider capability claims.

## Known Limitations
- No real provider API cost query yet.
- No real external execution is performed.
- Recommendations are deterministic and artifact-based.
- Router policy changes remain a human review step.
