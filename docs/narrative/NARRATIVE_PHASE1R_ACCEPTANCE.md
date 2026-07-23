# Narrative Production Repair — Phase 1R Acceptance

## Verdict

**Accepted for structural contracts only.** The new path makes AgentLab the
owner of the creative brief, output validation, receipt, state projection and
retry boundary while the Writer model owns prose. No live provider run or
literary-quality uplift is claimed.

## What is now closed

- Creative-brief sources must be canonical, existing regular files whose raw
  bytes match the recorded SHA256.
- Writer v2 accepts prose only at the exact
  `runs/<task_id>/fiction_draft.md` target.
- Provider, model and call ID are observed, nonblank values; blocked attempts
  cannot create a success receipt.
- Validation, persistence and receipt hashing share one canonical prose byte
  representation.
- State projection runs only after prose selection. Projector and verifier
  failures remain node-local and preserve the selected prose without rerunning
  Writer.
- Legacy v1 outputs remain readable.

## Verification

- Focused contract suite: **155 passed, 0 failed**.
- Narrative-domain suite: **202 passed, 0 failed**.
- Compile and patch checks passed.
- Generic background engine, config, manuscripts, Production and release
  objects were not changed.
- Central adapter additions are 40, 23 and 138 lines, all within the 150-line
  phase limit.

The first full-repository run produced 2,884 passes and two failures. The
Phase 1R Writer-template regression was fixed and its direct replay passes. The
remaining failure is a local absolute path already present in accepted Phase 0R
evidence at base commit `1dd5008`; it must be repaired separately with its
evidence pointer rehashed before Phase 2R dispatch. That separate repair was
then completed: the pointer hash was recomputed and the post-hygiene full suite
passed with **2,886 passed, 2 skipped, 0 failed**.

## Execution reliability finding

AgentLab did not complete this phase unattended. Correction 3 and its
node-local resume each timed out at 600 seconds after leaving useful partial
changes. Codex intervened only on the frozen public-contract failures, then ran
independent Standards and Spec reviews. Those reviews exposed and drove fixes
for live-file hash validation, empty task IDs, stale output cleanup, canonical
Engine bytes, injectable projector behavior and arbitrary projector failures.

## Remaining gates

- `positive_calibration_status: missing_user_samples`
- Live Writer/provider calls: 0
- Human blind-review pairs: 0/10
- Gate 1 literary uplift: not evaluated
- Production writes: 0

Phase 2R may be dispatched only after a direct local smoke of the registered
`claude_code / deepseek-v4-pro` combination compares startup, heartbeat,
deadline, exit and receipt behavior with the AgentLab wrapper. Phase 3R quality
claims, Gate 2, Phase 5 and Production promotion remain blocked by their
original gates.

## Rollback

Use the independent Phase 1R commit revert described in
`acceptance_runs/narrative_repair_v2/phase_1r/rollback.md`.
