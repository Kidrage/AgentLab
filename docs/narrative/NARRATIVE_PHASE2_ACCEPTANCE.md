# Narrative Phase 2 Acceptance

## Verdict

Phase 2 mechanisms are complete and deterministic acceptance passes. Ordinary
chapters now carry one-candidate/one-Judge plans; risk signals explicitly enable
the higher-cost path. Heavy-audit preparation creates a content-addressed,
immutable context bundle, deterministic checks run before literary judges, and
revision impact windows can be bounded to changed chapters, immediate neighbors,
and declared fact dependencies.

This verdict does not claim provider-backed wall-time/token savings or literary
uplift. No live manuscript/model trial was authorized and Production was not
modified.

## Baseline

The frozen Phase 0 baseline records 36.45% repeated source bytes in the Ch21–30
heavy audit and four provider roles for the post-repair audit. Existing evidence
also proves node-local retry already worked, so Phase 2 preserved that behavior
instead of replacing it.

## Root Causes

- Final narrative payloads had no reusable context identity.
- Ordinary and high-risk chapters shared the same expensive audit path.
- Cheap structural checks were mixed into model work.
- Revision review had no explicit impact-window contract.

## Confirmed Issues

- Heavy-audit context is now bound to `context_bundle_id`, canon snapshot hash,
  chapter window, shared files, role-specific files, and manifest hash.
- Background attempts persist a structured chapter risk plan; they do not infer
  risk from generated prose.
- Ordinary background audit dispatches the single-Judge adapter instead of the
  four-role full pipeline.
- High-risk execution requires two independent Judge receipts and arbitration on
  conflict at the tiered-audit seam.

## Rejected Hypotheses

- Whole-pipeline retry was not a root cause; existing node-local retry remains.
- Every audit role did not read the full manuscript; the repair targets measured
  shared/derived context duplication instead.

## Changed Modules

- `agent_runtime/narrative/efficiency/context_bundle.py`
- `agent_runtime/narrative/efficiency/planning.py`
- `agent_runtime/narrative/audit/precheck.py`
- `agent_runtime/narrative/audit/execution.py`
- `agent_runtime/narrative/audit/runtime.py`
- thin adapters in `background_job_controller.py`, `background_job_worker.py`,
  and `narrative_heavy_audit.py`

The Phase 2 controller delta is +21/-1 lines and the worker delta is +30/-8;
neither central module approaches the 150-net-line stop threshold.

## State-Machine Changes

Job creation persists `narrative_execution_plan`. Each attempt receives only its
batch slice. Ordinary heavy audit runs deterministic preparation then one
Reviewer. Risk plans retain the high-cost route. Existing attempt leases,
idempotency keys, receipt consumption, retry waits, and expired-worker fencing
remain unchanged.

## Efficiency Before/After

On the deterministic frozen-fixture execution contract:

- ordinary audit roles: 4 → 1 (75% fewer role calls);
- ordinary cross-role context duplication: historical 36.45% → 0% by construction
  for the single-Judge path;
- one changed chapter in a 10-chapter fixture: 10 reviewed → 5 reviewed after
  neighbor and fact-impact expansion.

Provider wall time, tokens, and monetary cost remain `unavailable`; they were not
estimated as observed facts.

## Quality Before/After

The seal gate and deterministic quality boundary are unchanged. Phase 2 adds no
quality-score inflation and makes no prose-quality claim. Risk-triggered second
judging and conflict arbitration prevent the efficiency path from silently
removing scrutiny from high-risk chapters.

## Test Results

- Phase 2 focused and narrative-domain regression: `87 passed`.
- Ruff on changed runtime/tests: pass.
- `git diff --check`: pass.

Primary coverage remains consolidated in `test_narrative_efficiency.py`, with
compatibility checks in the existing background and heavy-audit suites.

## Live Trial Results

Not run. Provider calls: 0. `candidate_only: true`;
`production_modified: false`.

## Remaining Risks

- High-risk provider/model independence still needs the Phase 3 calibrated Judge
  and anonymous A/B receipt implementation.
- Live before/after efficiency needs the governed three-chapter trial.
- User-positive calibration samples are still missing.

## Rollback Instructions

Revert the dedicated Phase 2 commit. No Production artifact or runtime job state
migration is required.

## Next Recommended Gate

Proceed to Phase 3 mechanisms, but keep literary-uplift status blocked until the
user supplies 3–5 accepted positive samples and ten human blind comparisons pass.
