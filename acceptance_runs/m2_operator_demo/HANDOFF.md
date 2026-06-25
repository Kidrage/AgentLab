# M2-12 Operator Demo Handoff

## Status

M2-12 Operator Acceptance Demo is implemented and accepted locally.

- CLI: `./agentlab.sh m2-operator-demo --out acceptance_runs/m2_operator_demo --project AgentLab`
- Report: `acceptance_runs/m2_operator_demo/M2_OPERATOR_OS_EXECUTION_ECONOMY_REPORT.md`
- Summary: `acceptance_runs/m2_operator_demo/m2_operator_demo_summary.yml`
- Result: `pass`

## Migration Readiness

`migration-doctor` now passes with the current local-first setup:

- GitHub source remote uses SSH, so `GITHUB_TOKEN` is not required.
- Project GitHub backup is disabled, so guarded GitHub backup token is not blocking.
- `OPENAI_API_KEY` is optional; Codex CLI/OAuth style worker usage is the intended local path when no OpenAI API key is configured.
- TrueNAS SSH status passes with write probe.
- WebUI local access token is configured through `agent_runtime/.env` and is not committed.

## Included Evidence

This directory includes deterministic, local-only evidence for:

- runtime hygiene summary
- migration doctor summary
- worker registry summary
- 9-role requirement matrix summary
- mock worker audition scorecard
- route decision example
- approval decision card
- cost estimate and ledger example
- timeline excerpt
- TUI/WebUI smoke evidence
- mock executor result
- phase acceptance result
- assistant explanation examples

## Verification Commands

```bash
pytest -q tests/test_m2_12_operator_demo.py tests/test_migration_backup.py tests/test_truenas_sync.py
./agentlab.sh migration-doctor --project AgentLab --json-output --no-write-probe
./agentlab.sh truenas-status --project AgentLab --json-output
./agentlab.sh m2-operator-demo --out acceptance_runs/m2_operator_demo --project AgentLab
```

Observed verification before handoff:

- focused M2-12/migration tests: `34 passed in 6.28s`
- migration-doctor: `pass`, `19 pass / 0 warn / 0 fail`
- TrueNAS write probe: `pass`
- M2-12 demo: `pass`

## Next Stage

Proceed to M2-12.5 Goal / Mainline Command Bridge.

Scope reminder:

- implement deterministic `/goal` grammar and Chinese aliases
- compile goal contracts into mainline project artifacts
- integrate CLI, Assistant, TUI, WebUI, MCP/frontdesk action schema
- keep M3 business/revenue features future-reserved and non-blocking
- do not introduce real external executor dispatch, network model calls, unsafe shell automation, or automatic skill installation

## Closure Fix Validation

Full pytest after CI-safe closure fix: `1707 passed, 2 skipped, 11 warnings in 222.83s`.

CI URL remains pending until the pushed repair commit completes on GitHub Actions.
