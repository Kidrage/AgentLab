# Narrative Phase 3 Acceptance

## Verdict

Phase 3 contract and state-machine wiring is complete, but provider-backed
revision and live quality acceptance are blocked. Per-chapter scorecards,
scene-level revision contracts, independent re-audit, anonymous A/B selection,
and regression-aware retention are implemented and tested. The background
revision action deliberately returns `decision_required` until executable
contracts and the live calibration gate are accepted.

This is not evidence that prose is now more intelligent or entertaining.

## Baseline

Ch26 and Ch30 remain immutable user-reported negative samples. The prior system
could detect and rewrite issues but lacked mandatory per-chapter evidence,
scene-local preservation boundaries, anonymous old/new preference, and accepted
improvement receipts.

## Root Causes

- Findings were abstract rather than executable scene constraints.
- Batch-level or averaged scores could hide a bad chapter.
- Literary blocking could be obscured by incomplete evidence.
- Reviewers could know which draft was revised.
- A revision could replace a candidate without proving a blind win and no new
  regression.

## Confirmed Issues

- `narrative_quality_scorecard.yml` is per chapter and requires all six dimensions,
  score 1–5, derived severity, exact evidence, reason, and revision target.
- Scores 1–2 block; causal reasoning, strategic competence, and character agency
  are veto dimensions.
- Verifier proposals require scene-level preservation, causal, knowledge, cost,
  information, freedom, and regression fields.
- The background revision action consumes the persisted Verifier output rather
  than rebuilding a request from prose.
- Deterministic checks and independent re-audit precede anonymous A/B selection;
  a losing or regressing revision replaces nothing.
- At most two automatic attempts remain authoritative; insufficient uplift
  becomes `decision_required`.

## Rejected Hypotheses

- A stronger Writer model alone is not uplift evidence.
- Schema validity and continuity are not reader-quality proof.
- Missing positive samples cannot be replaced with random chapters.
- A legacy single-root scorecard cannot prove coverage for a multi-chapter batch.

## Changed Modules

- `agent_runtime/narrative/quality/scorecard.py`
- `agent_runtime/narrative/quality/revision.py`
- `agent_runtime/narrative/quality/blind_review.py`
- `agent_runtime/narrative/quality/uplift.py`
- `agent_runtime/narrative/quality/calibration.py`
- `agent_runtime/narrative/quality/workflow.py`
- `agent_runtime/narrative/quality/background.py`
- thin enforcement in narrative audit materialization, job defaults, CLI
  structured output, controller dispatch, and the canonical seal gate

## State-Machine Changes

The revision contract is:

`finding → scene contract → bounded Writer revision → deterministic check → independent re-audit → anonymous A/B → retain or replace`.

The background action currently stops at `decision_required` when the provider
revision gate or executable scene contracts are missing. It does not fabricate a
quality win.

## Efficiency Before/After

Phase 3 adds no unconditional multi-model work. Blind A/B and independent second
judging are revision/risk triggered. Provider time and tokens were not measured.

## Quality Before/After

The system can record dimension deltas, resolved/unresolved/new blocking, blind
preference, and cost/time per accepted improvement. Actual literary uplift is
`unavailable`: positive samples 0/3–5, human blind pairs 0/10, live provider
revisions 0.

## Test Results

- Final consolidated narrative/controller/CLI regression: `211 passed`.
- Primary coverage: `tests/test_narrative_quality_gate.py` and
  `tests/test_narrative_audit_closure.py`.
- Ch26/Ch30 identities and hashes remain frozen.
- The calibration claim gate blocks with zero positives and zero human pairs.

## Live Trial Results

Not run. Provider calls: 0. Human blind pairs: 0/10. Production unchanged.

## Remaining Risks

- The user must provide 3–5 accepted positive chapters.
- At least ten human blind pairs must reach a 70% new-system win rate.
- Provider-backed Writer/Judge behavior and actual prose uplift are unverified.

## Rollback Instructions

Revert hardening commit `09bb2bb`, then Phase 3 commit `d892e62` after reverting
Phase 4 if present. Candidate and Production artifacts require no migration.

## Next Recommended Gate

Supply the positive calibration set, authorize the isolated three-chapter trial,
and perform ten human blind comparisons. Keep Phase 5 blocked until those formal
receipts pass.
