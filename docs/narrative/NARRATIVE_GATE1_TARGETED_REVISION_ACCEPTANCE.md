# Gate 1 Targeted Revision Acceptance

Status: `accepted_local_pending_commit_ci`

This unit closes the provider gate between a failed v2 candidate audit and one
new candidate-only Writer attempt. It does not claim literary uplift, select a
revised chapter, advance Ch26/Ch27, or modify Production.

## Public seam

`preflight_live_writer_revision(spec_path, repository_root=...)` publishes one
new, exact-plan Writer attempt. The spec is compiled once into:

- `job_kind: narrative_revision`
- `run_mode: targeted_rewrite`
- `candidate_set_id`
- `source_job_id`
- `source_run_id`
- `triggered_by_audit_id`
- `attempt_id`
- `lease_token`
- `lease_expires_at`
- authoritative `automatic_rewrite_count`
- `automatic_rewrite_number`
- `fencing_token`
- immutable `attempt_receipt`

The attempt inherits its generation context from the SHA256-bound, activated
source Writer request. Natural-language findings never determine its job kind.

## Enforced invariants

- The source run and revision run are distinct.
- The triggering audit has its own run named by `triggered_by_audit_id`; it is
  never added to the immutable source-generation run.
- The source request must still match its active workflow plan.
- The source candidate must match its AgentLab output contract.
- The triggering deterministic audit must still be actionable and must carry
  the exact audited candidate SHA256.
- The revision contract is chapter-bound and hash-bound to both the source
  candidate and triggering audit.
- Only the source candidate and executable revision contract are added to the
  Writer packet. The raw audit is deliberately excluded.
- Cross-project, wrong-chapter, stale-hash and symlinked evidence fail before a
  new run is published.
- Rewrite count comes from an append-only, exclusively reserved two-slot
  attempt ledger anchored to the immutable `source_run_id`, not a caller-chosen
  candidate set. The first reservation binds `candidate_set_id`; caller-reset
  counts or candidate-set aliases fail closed and a third distinct attempt
  cannot be reserved.
- An exact preflight replay is idempotent and reuses the same receipt, fence and
  activation. A gapped/corrupt ledger never takes the idempotent shortcut.
- A third attempt request creates no `attempt-03`; it persists
  `decision_required.yml` with `automatic_rewrite_exhausted: true` and
  `reason: insufficient_revision_uplift`.
- An expired lease blocks both pre-provider session preparation and a delayed
  Worker return.
- Reserving a newer attempt immediately fences an older Worker. Once one valid
  result has succeeded in a run, delayed or expired work cannot replace or
  delete it.
- A required monotonic fence head records the issued count, latest receipt hash
  and token. Deleting a newer receipt cannot revive an older Worker; deleting
  an earlier receipt makes the lineage invalid. An old idempotent replay cannot
  move the head backward.
- Final revision delivery and reservation share the same source-ledger lock, so
  a new fence cannot be inserted between final validation and prose materialization.
- The revised prose can materialize only in the new run and remains subject to
  the original SHA256-bound 4,500–5,500 Han-character contract.
- Activation binds the source request, candidate, triggering audit, revision
  contract, attempt receipt and Production digest. A mutation during or after
  publication makes the plan unloadable.
- Preflight calls no provider and verifies both the source run and Production
  tree remain unchanged before returning success.

## Module boundaries

- `agent_runtime/narrative/production/live_revision.py` owns revision lineage,
  evidence, contract and lease validation.
- `agent_runtime/narrative/production/live_revision_preflight.py` owns
  provider-free exact-plan publication and activation.
- `agent_runtime/narrative/production/revision_attempts.py` owns the append-only
  two-attempt ledger, exclusive reservations and fencing validation.
- `agent_runtime/narrative/production/live_writer.py` contains only the Writer
  integration: revision references, specialized prose instruction, receipt
  identity, first-success preservation, and delayed-return lease/fence checks.

No Crown-specific rule was added to the live revision core. No background queue,
central runner, code-task route or Production promotion interface changed.

## Local evidence

- Targeted live Writer and revision set: `34 passed`.
- Narrative semantics/audit/quality/efficiency domain set: `195 passed`.
- Crown v2 deterministic audit set: `7 passed`.
- Independent Standards review: `PASS`.
- Independent Spec review: `PASS`.
- Authoritative full repository: `3,046 passed, 2 skipped, 11 warnings`.
- Ruff, compileall and `git diff --check`: pass.
- Provider calls during this unit: `0`.
- Production writes during this unit: `0`.

Commit/CI and knowledge rebuild remain required before the real Ch25 revision
preflight or any external model call.

## Rollback

Revert the eventual targeted-revision unit commit. The original Ch25 run remains
immutable and failed on length, so rollback does not require restoring any
candidate or Production prose.
