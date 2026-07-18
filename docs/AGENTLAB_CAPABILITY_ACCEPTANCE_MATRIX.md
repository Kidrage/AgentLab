# AgentLab Capability Acceptance Map

This document maps capability areas to evidence owners. It does not mirror live
status, counts, provider blockers, or selected commands.

## Canonical Status

Read current status from:

`acceptance_runs/agentlab_capability_acceptance/current.yml`

Follow the evidence paths recorded by each capability item. Supporting YAML and
receipts are authoritative only for the acceptance run that produced them.
`external_acceptance_readiness.yml` is a compatibility projection;
`internal_live_readiness.yml` is its canonical readiness source where referenced
by `current.yml`.

## Capability Areas

| Area | Primary authority | Minimum evidence |
|---|---|---|
| Mission and routing | mission contract, routing rules | route decision and deterministic route tests |
| Role execution | resolved workflow profiles, role receipts | declared worker/model/contract and exit receipt |
| Lifecycle closure | lifecycle/state/event files | required nodes terminal with matching receipts |
| Code production | candidate diff/artifacts | focused tests, independent validation, no undeclared write |
| Narrative production | draft, continuity, state proposal | packet fulfillment and memory closure |
| Narrative audit | review/failure/rewrite proposals | bounded source manifest and blocking verdict |
| Media production | generation ledger and asset hashes | independent observation/review plus structural verification |
| Artifact promotion | lineage, promotion plan, archive receipt | approved targets and updated artifact index |
| Background recovery | progress/events/decision cards | heartbeat, durable status, recoverable transition evidence |
| Repository governance | handoff and hygiene reports | canonical handoff, clean placement, no credential leak |
| Self-evolution | scoped component proposal | ownership, bridges, tests, rollback, approval |

## Interpretation Rules

- `pass` means the declared evidence and acceptance checks passed for that item.
- `partial` means useful evidence exists but at least one declared gate is open.
- `blocked` means a concrete external, approval, or runtime condition prevents
  completion; it is not proof that unrelated capabilities failed.
- Dry-run, fixture, and static-contract evidence cannot be reported as live
  provider execution.
- Candidate acceptance cannot be reported as production promotion.
- A worker summary is not evidence unless the expected files and receipts exist.
- Historical snapshots under `docs/archive/` and old handoff aliases are not
  current acceptance sources.

## Private And Live Boundaries

Private context, provider-backed execution, and live media generation require
their declared approval and outbound-context gates. Approval does not relax
candidate-only paths, secret redaction, fallback policy, or promotion controls.
The trusted runner collector accepts returned artifacts only after validating
their declared source, hashes, and role-session receipts.

## Maintenance

Acceptance generators update machine-readable evidence. Architecture docs should
change only when the contract changes, not whenever a status count or provider
session changes. Tests therefore validate source links and invariants rather than
copying every volatile field into prose.

The former snapshot-style matrix is retained at
`docs/archive/acceptance_docs_legacy_20260718/AGENTLAB_CAPABILITY_ACCEPTANCE_MATRIX.md`.
