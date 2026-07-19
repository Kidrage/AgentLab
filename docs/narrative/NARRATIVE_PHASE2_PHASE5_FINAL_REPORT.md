# Narrative Phase 2–5 Final Report

## Verdict

Phase 2 and Phase 4 deterministic mechanisms are complete. Phase 3 has complete
contract and state-machine wiring, but its provider-backed rewrite and literary
uplift gates are blocked. Phase 5 was correctly not started because the plan
permits it only after Phases 0–4 pass their live acceptance gates.

AgentLab therefore cannot yet be declared capable of stably finishing every
novel task in the background. It has a substantially safer candidate-only
production/audit/promotion foundation, but there is no 3-chapter live Gate 1,
three consecutive 10-chapter Gate 2 runs, or 200-chapter Gate 3 completion
receipt. No Production content was changed.

## Baseline

- Crown 200-chapter work remained blocked in early batch processing with zero
  sealed batches and no completion receipt.
- Phase 0 measured 36.45% duplicated source bytes in the frozen Ch21–30 heavy
  audit context.
- Ordinary and high-risk work did not have a fully wired cost-tier distinction.
- Findings could be abstract; revised prose had no mandatory blind-win proof.
- Candidate, audit, approval, and current release state were not joined by one
  immutable hash chain.
- Positive calibration status was and remains `missing_user_samples`.

Canonical baseline: `acceptance_runs/narrative_efficiency/baseline_metrics.json`.

## Root Causes

1. Background audit semantics and evidence coverage were not carried through an
   authoritative structured execution window.
2. Deterministic checks and model judgment were mixed, while ordinary and
   high-risk chapters shared too much orchestration.
3. Audit-support roles were not consistently represented as independently
   receipted, retryable nodes.
4. Quality findings lacked an executable, scene-bounded revision contract and
   blind old/new retention rule.
5. Approval identity did not cryptographically bind every accepted evidence
   receipt, and promotion needed stronger path and interruption safety.
6. Live literary and efficiency calibration evidence does not exist yet; code
   cannot substitute for reader evidence.

## Confirmed Issues

### Phase 2 deterministic audit execution

- Fix: deterministic precheck precedes Judges; the persisted incremental window
  is authoritative; ordinary chapters use one primary Judge and high-risk
  chapters alone receive a second Judge; per-chapter evidence coverage fails
  closed; Scribe/Verifier retry locally.
- Code: `agent_runtime/narrative/audit/background.py`, `precheck.py`,
  `runtime.py`, `background_job_controller.py`, `background_job_worker.py`.
- Tests: `tests/test_narrative_efficiency.py`,
  `tests/test_narrative_audit_closure.py`, controller/worker owner suites.
- Evidence: 211-test consolidated narrative/controller/CLI regression passed.
- Metric: ordinary clean primary model roles 4 → 1; a 10-chapter frozen
  single-change review window 10 → 5; upstream nodes repeated after Verifier
  failure → 0.
- Non-narrative impact: generic lease/retry semantics were preserved; narrative
  policy lives under `agent_runtime/narrative/` with thin dispatch adapters.
- Rollback: revert `09bb2bb`, then `38be986` after dependent phases.

### Phase 3 quality contract and revision state

- Fix: per-chapter six-dimension evidence scorecards, three veto dimensions,
  scene-level revision contracts, independent re-audit, anonymous A/B selection,
  regression-aware retention, and a two-attempt stop.
- Code: `agent_runtime/narrative/quality/scorecard.py`, `revision.py`,
  `blind_review.py`, `uplift.py`, `workflow.py`, and `background.py`.
- Tests: `tests/test_narrative_quality_gate.py` and
  `tests/test_narrative_audit_closure.py`.
- Evidence: schema/coverage/veto/replacement/decision-required replays passed in
  the 211-test consolidated run; Ch26/Ch30 identities remain frozen.
- Metric: positive samples 0/3–5; human blind reviews 0/10; provider revisions 0.
  Actual quality delta is unavailable and no uplift is claimed.
- Non-narrative impact: shared CLI/output-schema owner tests were updated, while
  runtime activation remains narrative-job gated.
- Rollback: revert `09bb2bb`, then `d892e62` after Phase 4.

### Phase 4 Candidate Set and promotion safety

- Fix: immutable Candidate Sets, stale-audit invalidation, approval bound to the
  exact evidence-bundle content hash, symlink-safe root containment, first
  publication, immutable release objects, atomic index switching, and idempotent
  interrupted retry.
- Code: `agent_runtime/narrative/candidates/manifest.py` and `promotion.py`.
- Tests: `tests/test_narrative_delivery.py`.
- Evidence: hash drift, receipt mutation, symlink escape, first publication,
  retry, and interrupted index scenarios passed in the 211-test run.
- Metric: real promotions 0; formal Production writes 0.
- Non-narrative impact: no generic queue/release core received Crown policy.
- Rollback: revert `09bb2bb`, then `14e620d`.

## Rejected Hypotheses

- More Agents do not inherently produce independent or higher-quality review.
- Whole-pipeline retry was not the only retry behavior; existing node-local
  recovery was already present and was extended rather than replaced.
- Every role did not read the entire manuscript; duplication was concentrated in
  shared/derived sources.
- A stronger Writer model, valid schema, or continuity pass cannot prove reader
  quality.
- First release does not require a pre-existing current Production artifact.
- Phase 5 cannot be made safe merely by implementing more infrastructure while
  Phase 0 and Phase 3 live gates are absent.

## Changed Modules

- Phase 2: `agent_runtime/narrative/efficiency/`,
  `agent_runtime/narrative/audit/`, and thin background/CLI adapters.
- Phase 3: `agent_runtime/narrative/quality/`, narrative scorecard materialization,
  gate enforcement, and thin background/CLI adapters.
- Phase 4: `agent_runtime/narrative/candidates/`.
- Tests remain concentrated in domain/owner suites; no fragmented one-test files
  were introduced.
- Phase commits: `38be986` (Phase 2), `d892e62` (Phase 3), `14e620d` (Phase 4),
  `09bb2bb` (cross-phase runtime hardening and wiring).

## State-Machine Changes

Audit:

`bundle → deterministic precheck → primary Judge → risk-only second Judge → conflict decision → optional Scribe → independent Verifier → seal/decision_required`.

Revision:

`finding → scene contract → bounded rewrite → deterministic check → independent re-audit → anonymous A/B → retain/replace`, with a maximum of two automatic attempts.

Promotion:

`draft set → freeze/hash verify → bound audits → content-bound acceptance → immutable release object → atomic artifact-index switch`.

Phase 5 remains `blocked_not_started`; no generic global queue, workbench, reader,
or release-package implementation was started under this authorization.

## Efficiency Before/After

Deterministic fixture results:

- ordinary clean audit primary roles: 4 → 1 (75% reduction);
- historical duplicate context: 36.45%; ordinary single-Judge cross-role
  duplication after: 0% by construction;
- single-change 10-chapter fixture: 10 → 5 audited chapters;
- successful upstream nodes replayed after Verifier failure: 1+ → 0.

Live provider wall time, model-active time, input/output/cache tokens, monetary
cost, and cost per accepted improvement remain unavailable. They were not
estimated or relabeled as measured data.

## Quality Before/After

Before, findings could be generic and revised text could replace an original
without anonymous proof of improvement. After, the deterministic contract can
block incomplete evidence, compile scene-bounded work, preserve both drafts, and
refuse a losing or regressing revision.

Actual prose quality before/after is unproved: no positive calibration chapters,
no live rewrite, no completed human A/B pair, and no 70% win-rate result exist.

## Test Results

- Consolidated narrative/controller/CLI suite: `211 passed`.
- Independent specification review: no unresolved hard findings.
- Independent standards review: no unresolved hard findings.
- Ruff on changed runtime/tests, compile, and `git diff --check`: pass.
- Full repository: `2814 passed, 2 skipped, 11 warnings` in 223.37 seconds.
- Repository hygiene: pass, 0 hard violations, 0 warnings.
- Model doctor: pass, 0 issues across 135 resolved profiles.
- GitHub CI: implementation run `29682754295`, report run `29682973102`, and
  handoff run `29682986671` all passed.
- Machine-readable result:
  `acceptance_runs/narrative_phase2_phase5/final_acceptance.json`.

No test assertion or schema was relaxed to obtain green results.

## Live Trial Results

- Provider calls: 0.
- Human blind pairs: 0/10.
- User-positive samples: 0/3–5.
- Real Candidate Set promotions: 0.
- Production modified: false.
- Gate 1, Gate 2, and Gate 3: not run.
- 200-chapter completion receipt: absent.

## Remaining Risks

- Provider-backed latency, token, cost, retry, and model-independence behavior is
  unverified.
- The quality loop has deterministic safety but no reader-validated uplift.
- Crown Ch25–27 context disclosure still requires explicit approval.
- Workbench/release-package productization and generic background-core extraction
  remain Phase 5 work and have not begun.
- A 200-chapter soak would be unsafe and contrary to the gate contract now.

## Rollback Instructions

Rollback in reverse dependency order:

1. `git revert 09bb2bb`
2. `git revert 14e620d`
3. `git revert d892e62`
4. `git revert 38be986`

Do not revert an earlier phase while dependent later commits remain. No real
Production artifact requires content restoration.

## Next Recommended Gate

1. Obtain explicit approval for the isolated Ch25–27 external-context trial.
2. Supply 3–5 user-approved positive calibration chapters.
3. Run Gate 1 candidate-only and capture real wall/token/cost/uplift receipts.
4. Complete at least ten human blind comparisons with a ≥70% new-system win rate.
5. Run three consecutive recoverable 10-chapter Gate 2 batches.
6. Only then authorize Phase 5; Gate 3 200-chapter soak follows Phase 5 and Gates
   1–2, never precedes them.
