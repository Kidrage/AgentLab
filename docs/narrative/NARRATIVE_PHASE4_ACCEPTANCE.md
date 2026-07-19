# Narrative Phase 4 Acceptance

## Verdict

Phase 4 Candidate Set and promotion safety mechanisms are complete. Real
promotion remains blocked because the upstream live and literary-quality gates
have not passed. All promotion tests used isolated temporary projects;
Production was not modified.

## Baseline

The prior product state could be inferred from historical runs and promotion
logic assumed existing current artifacts. Candidate chapters, audits, approvals,
and promotion were not bound through one immutable set hash.

## Root Causes

- Candidate collections were mutable after audit.
- Approval could become stale after正文 changes.
- First publication was conflated with replacement of an existing current item.
- A multi-file promotion failure could leave partially staged Production state.

## Confirmed Issues

- Candidate Set manifests include exact chapter artifacts, hashes, lineage,
  model tier, context hash, predecessor hash, audit and cost receipts.
- Freeze recomputes hashes; later artifact mutation marks the set and audits
  stale.
- Promotion validates frozen/current hashes, zero blocking, final model tier,
  exact user acceptance, and receipt binding.
- Empty Production supports first publication.
- Uniqueness is evaluated by release slot, chapter, and edition.
- Edition contents are staged and verified before the artifact index pointer is
  atomically changed; a simulated index interruption rolls the edition back.

## Rejected Hypotheses

- A project does not need one pre-existing current artifact for first release.
- Historical `runs/*` are not used as the current product database.

## Changed Modules

- `agent_runtime/narrative/candidates/manifest.py`
- `agent_runtime/narrative/candidates/promotion.py`
- consolidated delivery coverage in `tests/test_narrative_delivery.py`

No central runtime module was expanded in Phase 4.

## State-Machine Changes

`draft Candidate Set → hash-valid freeze → audit-bound frozen set → exact user acceptance → staged edition → atomic index switch`.

Any hash drift returns `stale`; any validation or write failure leaves the prior
formal index and current Production content unchanged.

## Efficiency Before/After

Not an optimization phase. Promotion performs one bounded hash verification and
one staged copy per chapter.

## Quality Before/After

No literary claim. Phase 4 preserves the Phase 3 gate and refuses promotion when
literary evidence is missing, stale, blocking, or not bound to the same set.

## Test Results

- Focused and affected delivery/promotion regression: `71 passed`.
- Ruff on new Candidate Set modules: pass.
- Test file lint with its pre-existing E402 compatibility pattern ignored: pass.
- `git diff --check`: pass.

## Live Trial Results

No real candidate was accepted or promoted. `production_modified: false`.

## Remaining Risks

- A real multi-chapter Candidate Set has not completed the Phase 3 quality gate.
- The 3-chapter provider-backed Gate 1 trial remains unapproved.
- Phase 5 is explicitly prohibited until Phases 0–4 pass.

## Rollback Instructions

Revert the dedicated Phase 4 commit. No real Candidate Set or Production
migration was performed.

## Next Recommended Gate

Do not start Phase 5 yet. Obtain external-context approval for the three-chapter
trial, provide 3–5 positive samples, and complete ten human blind comparisons at
70% or better. Re-evaluate the Phase 5 gate from formal receipts after those
conditions pass.
