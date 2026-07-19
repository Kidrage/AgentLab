# Narrative Phase 1 Acceptance

## Verdict

Phase 1 implementation is complete on `feature/narrative-production-closure` and passes deterministic acceptance. Narrative audit, generation, revision, and independent re-audit attempts now carry explicit structured identities; candidate sealing is fail-closed and hash-bound; audit-only jobs complete without entering rewrite; and automatic rewrite attempts stop after two failures per batch.

This verdict does not authorize Phase 2, a live manuscript/model trial, Production promotion, or a 200-chapter soak.

## Baseline

Phase 0 at `69b3a2a` preserved two confirmed defects: a heavy-audit request containing rewrite-proposal language could be classified as rewrite, and a blocked fiction review could be sealed when continuity passed. The old controller could also seal after deterministic re-audit without an independent audit and had no attempt deadline or per-batch rewrite ceiling.

## Root Causes

- Task meaning was repeatedly represented by prose instead of a durable identity contract.
- Heavy-audit closure only consumed continuity status and trusted a worker summary.
- Deterministic checks and rechecks could directly seal a batch.
- Attempts had idempotency keys but no deadline-bearing lease.
- Rewrite counters and audit findings were not modeled as batch-scoped state.

## Confirmed Issues

- Full heavy-audit intake containing `revision_or_rewrite_proposal` now compiles to `narrative_audit / audit_only`.
- Rewrite and independent re-audit child attempts now carry `narrative_revision / targeted_rewrite` and `narrative_audit / independent_reaudit` with source lineage.
- Fiction, continuity, or required literary blocking vetoes sealing.
- Missing audit evidence, missing/mismatched candidate hashes, changed source artifacts, missing independent re-audit, stale/missing approval during promotion evaluation, token mismatch, and expired leases fail closed.
- Audit-only jobs process every planned batch and terminate as `completed_clean` or `completed_with_findings`; warning findings are aggregated rather than mislabeled clean.
- Each batch receives at most two automatic rewrite attempts, after which state becomes `decision_required` with `insufficient_revision_uplift`.

## Rejected Hypotheses

- More routing keywords are not the durable fix. Natural-language parsing remains intake-only; background requests copy validated structured identity.
- Continuity pass is not sufficient evidence for seal.
- A request flag alone is not independent re-audit evidence. The receipt must identify a distinct audit task, source audit task, independent context, and matching candidate hash.

## Changed Modules

- `agent_runtime/narrative/jobs/identity.py`: identity schema, attempt identity, lease deadline helper.
- `agent_runtime/narrative/jobs/lifecycle.py`: audit closure and rewrite ceiling.
- `agent_runtime/narrative/jobs/background.py`: private generic audit-state persistence.
- `agent_runtime/narrative/jobs/crown_adapter.py`: Crown mission-contract adapter and legacy migration.
- `agent_runtime/narrative/audit/gate.py`: canonical fail-closed seal decision.
- `agent_runtime/narrative/audit/integrity.py`: source-manifest hash verification.
- `agent_runtime/brain/mission_contract.py`: one-time identity compilation.
- `agent_runtime/background_job_controller.py`: thin scheduling/reducer integration; net `+149` lines, below the phase threshold.
- `agent_runtime/background_job_worker.py`: structured evidence collection and hash-bound audit receipt.
- `agent_runtime/cli/background_jobs.py`: `create-crown-audit --mission-contract` entry.

No Production manuscript or project artifact index was modified. Non-narrative workflows do not receive a narrative identity. The existing Crown background receipt schema advances from 1 to 2; structured legacy Crown state is migrated only through the Crown adapter.

## State-Machine Changes

```text
audit_only
  -> heavy_audit(batch N)
  -> completed_clean | completed_with_findings
  -> next audit batch or terminal completion

generation/revision
  -> deterministic_check
  -> heavy_audit
  -> seal | targeted_rewrite | blocked
  -> deterministic_reaudit
  -> independent_reaudit
  -> seal | targeted_rewrite | decision_required
```

Deterministic checks no longer seal. A post-rewrite batch cannot seal without a distinct hash-bound independent re-audit.

## Efficiency Before/After

Not evaluated in Phase 1. No provider/model calls or live manuscript runs were made. Phase 2 remains responsible for context deduplication, tiered production/audit, incremental re-audit, and measured before/after efficiency.

## Quality Before/After

Phase 1 proves gate correctness, not literary uplift. It prevents known false-green outcomes and stops unproductive rewrite loops, but does not claim that prose became more intelligent or entertaining. That claim remains gated on Phase 3 calibration, blind A/B review, positive user samples, and the required human win rate.

## Test Results

- Focused Phase 1 suite: `169 passed`.
- Full repository suite: `2773 passed, 2 skipped, 11 warnings` in `214.63s`.
- Ruff on changed Phase 1 runtime/test modules: pass.
- `git diff --check`: pass.
- Python compile check: pass.
- Independent Standards review: clear, no unresolved hard findings.
- Independent Spec review: clear, no unresolved blocker/high findings.

Primary tests:

- `tests/test_narrative_job_semantics.py`
- `tests/test_narrative_audit_closure.py`
- `tests/test_narrative_quality_gate.py`
- `tests/test_narrative_background_recovery.py`
- existing compatibility coverage in `tests/test_background_job_controller.py` and `tests/test_background_job_worker.py`

## Live Trial Results

Not run. This phase was deliberately candidate-only and provider-free. `production_modified: false`; no live chapters, external manuscript disclosure, promotion, or soak was authorized.

## Remaining Risks

- The current Crown rewrite worker remains a fail-closed handoff; it does not yet perform validated scene-level rewriting.
- Literary scorecard production and calibrated judge independence belong to Phase 3.
- Candidate-set immutability, acceptance receipts, atomic promotion, and release manifests belong to Phase 4.
- Generic queue/lease supervision beyond the existing narrative controller belongs to Phase 5.
- Positive calibration samples are still missing, so no literary-quality improvement may be claimed.

## Rollback Instructions

Revert the Phase 1 implementation as one unit with `git revert 2d504f9`. The change does not migrate or modify Production. Existing schema-1 Crown job files remain recoverable because migration is applied from structured `job_type` in the Crown adapter; reverting restores the previous reader and worker behavior.

## Next Recommended Gate

Stop here and request explicit Phase 2 authorization. Before Phase 2, preserve the Phase 0 frozen baseline and use the same 3-chapter/10-chapter fixtures; do not start the 200-chapter soak.
