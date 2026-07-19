# Narrative Phase 2 Acceptance

## Verdict

Phase 2 deterministic efficiency mechanisms are complete. The real background
audit path now builds one immutable context bundle, runs deterministic checks
before model work, persists the authoritative incremental audit window, sends
ordinary chapters to one primary Judge, and adds a second Judge only for the
high-risk subset. Scribe and Verifier are durable node-local actions, so a
Verifier failure does not rerun Writer, Reviewer, or Scribe.

The live efficiency gate is blocked. No provider-backed before/after trial was
authorized, so wall-time, token, and cost improvements are not claimed.
Production was not modified.

## Baseline

The frozen Phase 0 baseline records 36.45% repeated source bytes in the Ch21–30
heavy audit and four provider roles in the prior post-repair audit. Existing
recovery evidence showed some node-local retry behavior; Phase 2 extends it to
the new audit-support actions without replacing the generic retry core.

## Root Causes

- Final narrative payloads had no reusable context identity.
- Ordinary and high-risk chapters shared the same expensive audit path.
- Cheap structural checks were mixed into model work.
- Revision review had no authoritative impact-window contract.
- Audit-support work was not represented as separately receipted controller
  actions.

## Confirmed Issues

- Background audit preparation is content-addressed and runs deterministic
  candidate/hash/version/POV/timeline/repetition checks before any Judge.
- The actual audit window is persisted and is authoritative for precheck,
  scorecard coverage, and subsequent heavy audit.
- Mixed-risk batches use one primary Reviewer plus a second Reviewer only for
  high-risk chapters; conflicts fail closed.
- Scorecards and tiered receipts must cover every required chapter in the actual
  window. Missing chapters fail closed.
- Scribe and Verifier have independent attempts, leases, deadlines, and receipts.
  Retrying Verifier does not replay successful upstream nodes.

## Rejected Hypotheses

- Whole-pipeline retry was not the only root cause; existing node-local recovery
  already worked in parts of the controller.
- Every audit role did not read the full manuscript; the measured waste was
  concentrated in shared and derived context duplication.
- Timeline validation could not be a single English timestamp regex: Crown uses
  structured IDs and legacy Chinese descriptions that require explicit support.

## Changed Modules

- `agent_runtime/narrative/efficiency/context_bundle.py`
- `agent_runtime/narrative/efficiency/planning.py`
- `agent_runtime/narrative/audit/background.py`
- `agent_runtime/narrative/audit/precheck.py`
- `agent_runtime/narrative/audit/execution.py`
- `agent_runtime/narrative/audit/runtime.py`
- thin adapters in `background_job_controller.py`, `background_job_worker.py`,
  `narrative_heavy_audit.py`, and `cli/background_jobs.py`

The central modules contain adapters and action dispatch; narrative policy stays
inside `agent_runtime/narrative/`.

## State-Machine Changes

The real audit path is now:

`prepare bundle → deterministic precheck → primary Reviewer → risk-only second Reviewer → conflict decision → optional Scribe → independent Verifier → seal/decision_required`.

Every action persists its own receipt and fencing identity. The required chapter
set comes from the persisted impact window, not from a later text inference.

## Efficiency Before/After

On the deterministic frozen-fixture contract:

- ordinary clean audit model roles: 4 → 1 primary Reviewer (75% reduction);
- ordinary single-Judge cross-role context duplication: historical 36.45% → 0%
  by construction for that path;
- one changed chapter in a 10-chapter fixture: 10 reviewed → 5 after neighbor and
  declared fact-impact expansion;
- failed Verifier: successful Reviewer and Scribe executions repeated 1 → 0.

These are state-machine/fixture measurements, not live provider measurements.

## Quality Before/After

The seal and literary gates are not relaxed. The optimization fails closed on
missing per-chapter evidence or Judge conflict. No prose-quality improvement is
claimed.

## Test Results

- Final consolidated narrative/controller/CLI regression: `211 passed`.
- Primary coverage: `tests/test_narrative_efficiency.py`.
- Closure/retry compatibility: `tests/test_narrative_audit_closure.py`,
  `tests/test_background_job_controller.py`, and
  `tests/test_background_job_worker.py`.
- Ruff, compile, and `git diff --check`: pass.

## Live Trial Results

Not run. Provider calls: 0. `candidate_only: true`;
`production_modified: false`.

## Remaining Risks

- Provider wall time, token savings, and model independence remain unmeasured.
- Gate 1 still needs the governed Ch25–27 trial.
- User-positive calibration samples remain missing.

## Rollback Instructions

Revert hardening commit `09bb2bb`, then Phase 2 commit `38be986` after reverting
dependent Phase 4 and Phase 3 commits if those are also present. No Production
artifact or runtime-state migration is required.

## Next Recommended Gate

Run the governed three-chapter trial only after external-context disclosure is
approved. Do not advance to Phase 5 from deterministic evidence alone.
