# P2-C Acceptance-to-Retry Loop

## Position

P2-C connects P2-B routing and P2-A review into an acceptance-to-retry loop.
It does not execute real external tools.
It plans retry attempts, generates retry handoffs, tracks provider quality, and prevents unreviewed acceptance.

## Supported Modes

- dry-run
- mock-pass-first
- mock-fail-then-pass
- mock-fail-until-max
- manual-handoff

## Stop Conditions

- accepted after P2-A PASS / PASS_WITH_WARNINGS
- max attempts reached
- budget exceeded
- safety blocked
- no provider available
- manual approval required

## Safety Boundaries

- no real Codex/Cline/ECC/API execution
- no network
- no remote clone
- no shell execution
- no MCP startup
- no secret recording
- no unreviewed accepted result

## Artifacts

Each loop writes `retry_loop_state.yml`, `retry_attempt_ledger.yml`, `provider_scorecard.yml`, and `retry_loop_report.md`.
Accepted loops write `final_acceptance_receipt.yml`.
Rejected or stopped loops write `final_rejection_receipt.yml`.
