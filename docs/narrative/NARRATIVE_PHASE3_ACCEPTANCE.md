# Narrative Phase 3 Acceptance

## Verdict

Phase 3 quality and revision mechanisms are complete. Live quality acceptance is
blocked, as required, because the calibration set has no user-approved positive
samples and no ten-pair human blind-review result. The implementation therefore
does not claim that prose is now more intelligent or entertaining.

## Baseline

Ch26 and Ch30 remain immutable user-reported negative samples. The prior system
could detect issues and rewrite, but had no mandatory six-dimension evidence
contract, scene-local preservation boundary, anonymous old/new preference, or
accepted-improvement cost receipt.

## Root Causes

- Abstract findings were not compiled into executable scene constraints.
- Literary blocking could be hidden by incomplete or averaged scoring.
- Reviewers could know which draft was revised.
- A revision could replace a candidate without proving a blind win and no new
  regression.

## Confirmed Issues

- Reviewer structured output now requires `narrative_quality_scorecard.yml`.
- All six dimensions require score 1–5, derived severity, exact chapter/scene/
  locator evidence, reason, and revision target.
- Scores 1–2 block. Causal reasoning, strategic competence, and character agency
  remain explicit veto dimensions.
- Scene-level revision closure passes only the bounded contract to Writer, keeps
  unaffected scenes unchanged, runs deterministic validation and independent
  re-audit, then submits anonymous A/B candidates.
- A revised candidate replaces nothing if it loses, retains blocking, or creates
  a regression.

## Rejected Hypotheses

- A stronger Writer model alone is not treated as uplift evidence.
- Schema validity and continuity are not treated as reader-quality proof.
- Missing positive samples are not replaced with randomly selected chapters.

## Changed Modules

- `agent_runtime/narrative/quality/scorecard.py`
- `agent_runtime/narrative/quality/revision.py`
- `agent_runtime/narrative/quality/blind_review.py`
- `agent_runtime/narrative/quality/uplift.py`
- `agent_runtime/narrative/quality/calibration.py`
- `agent_runtime/narrative/quality/workflow.py`
- thin scorecard enforcement in narrative audit materialization, CLI structured
  output, job defaults, and the canonical seal gate.

## State-Machine Changes

The revision closure is now:

`finding → scene contract → local Writer revision → deterministic check → independent re-audit → anonymous A/B → retain or replace`.

The existing maximum of two automatic rewrite attempts remains authoritative;
insufficient uplift still becomes `decision_required`.

## Efficiency Before/After

Phase 3 adds no unconditional multi-model work. Blind A/B and independent second
judging remain risk/revision triggered. Provider time and token differences were
not measured because no live provider call was authorized.

## Quality Before/After

Mechanically, the system can now calculate per-dimension deltas, resolved,
unresolved and new blocking, blind preference, cost per accepted improvement,
and time per accepted improvement. Actual literary uplift remains unproved.

## Test Results

- Focused and affected narrative/controller/CLI regression: `158 passed`.
- Ch26/Ch30 calibration identities and hashes are frozen.
- Calibration claim gate correctly blocks with zero positives and zero human
  pairs.

## Live Trial Results

Not run. Provider calls: 0. Human blind pairs: 0/10. Production unchanged.

## Remaining Risks

- The user must provide 3–5 positive chapters.
- At least ten human blind pairs must reach a 70% new-system win rate.
- Provider-backed Judge independence and prose uplift remain unverified.

## Rollback Instructions

Revert the dedicated Phase 3 commit. Candidate and Production artifacts require
no migration.

## Next Recommended Gate

Implement Phase 4 immutable Candidate Set and promotion safety mechanisms, but
keep every real promotion blocked until this Phase 3 quality gate passes.
