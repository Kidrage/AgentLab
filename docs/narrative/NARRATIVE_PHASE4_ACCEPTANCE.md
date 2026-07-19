# Narrative Phase 4 Acceptance

## Verdict

Phase 4 deterministic Candidate Set and promotion-safety mechanisms are complete.
Real promotion remains blocked by upstream live and literary-quality gates. All
tests used isolated temporary projects; Production was not modified.

## Baseline

The prior product state could be inferred from historical runs and promotion
logic assumed existing current artifacts. Candidate chapters, audits, approvals,
and promotion were not bound through one immutable set hash.

## Root Causes

- Candidate collections were mutable after audit.
- Approval identity did not bind the exact receipt contents.
- First publication was conflated with replacement of an existing current item.
- Path/symlink escape and interrupted promotion needed fail-closed treatment.
- A multi-file promotion failure could expose partial formal state.

## Confirmed Issues

- Candidate manifests bind chapter artifacts, hashes, lineage, model tier,
  context hash, predecessor hash, audits, and cost receipts.
- Freeze recomputes hashes; later artifact mutation makes the set/audits stale.
- User approval binds the exact evidence bundle content hash; mutating a receipt
  after approval invalidates promotion.
- Candidate/release IDs and resolved paths must remain inside their configured
  roots, including symlink resolution.
- First publication is supported; uniqueness uses release slot, chapter, and
  edition.
- Promotion creates an immutable release object, verifies it, then atomically
  switches `project_artifact_index.yml`. An interruption may leave an unreferenced
  object, but formal current Production stays unchanged; identical retry resumes
  idempotently.

## Rejected Hypotheses

- A project does not need one pre-existing current artifact for first release.
- Historical `runs/*` are not the current product database.
- Deleting a staged object is not required to preserve formal atomicity; an
  unreferenced immutable object is recoverable lineage, not current Production.

## Changed Modules

- `agent_runtime/narrative/candidates/manifest.py`
- `agent_runtime/narrative/candidates/promotion.py`
- consolidated coverage in `tests/test_narrative_delivery.py`

No generic queue or release core received Crown-specific policy.

## State-Machine Changes

`draft Candidate Set → hash-valid freeze → audit-bound frozen set → content-bound user acceptance → immutable release object → atomic artifact-index switch`.

Hash drift, stale/missing evidence, unsafe paths, or write failure leaves the
prior formal index and current Production unchanged.

## Efficiency Before/After

Not an optimization phase. Promotion performs bounded hash verification and one
copy per chapter; idempotent retry reuses the identical release transaction.

## Quality Before/After

No literary claim. Promotion refuses missing, stale, blocking, or mismatched
literary evidence and cannot bypass the Phase 3 gate.

## Test Results

- Final consolidated narrative/controller/CLI regression: `211 passed`.
- Primary coverage: `tests/test_narrative_delivery.py`.
- Receipt mutation, symlink escape, first publication, idempotent retry, stale
  audits, and interrupted index switch are covered.
- Ruff, compile, and `git diff --check`: pass.

## Live Trial Results

No real candidate was accepted or promoted. `production_modified: false`.

## Remaining Risks

- A real multi-chapter Candidate Set has not passed the Phase 3 quality gate.
- The provider-backed three-chapter Gate 1 trial remains unapproved.
- Phase 5 is prohibited until the Phase 0 and Phase 3 live gates pass.

## Rollback Instructions

Revert hardening commit `09bb2bb`, then Phase 4 commit `14e620d`. Formal
Production was not changed, so no content rollback is required.

## Next Recommended Gate

Do not start Phase 5. Complete Gate 1, provide 3–5 positive samples, and finish
ten human blind comparisons at 70% or better, then re-evaluate from formal
receipts.
