# Phase 2R Node A — ContextCompiler acceptance candidate

## Verdict

**Accepted for Node A only.** This node does not
complete Phase 2R and makes no 25% context-reduction or literary-uplift claim.

The production ContextCompiler now validates the current CreativeBrief and its
source hashes, includes the canonical brief content and SHA256 in the bundle
identity, binds an explicit immediate-predecessor ID and optional receipt hash,
loads required canon/hard state, promotes cross-role duplicates to shared
context, and blocks pattern signals that attempt to carry acceptance,
literary-pass, seal or promotion authority.

## Independent verification

- Efficiency tests: 41 passed, 0 failed.
- Narrative-domain tests: 219 passed, 0 failed.
- Full repository: 2,903 passed, 2 skipped, 0 failed.
- Original combined false-green replay now blocks invalid authority and emits
  one shared copy with no private duplicate.
- Compile and patch checks pass.
- Generic background engine, central runtime entrypoints, config, manuscripts,
  Production and later Phase 2 nodes are untouched.

## AgentLab execution finding

The initial Coder node completed in 293.6 seconds and its correction in 533.6
seconds. Together they reported 8,314,441 tokens and cost about $6.39. The
correction finished only 66.4 seconds before the 600-second deadline. AgentLab
also failed to append the required root handoff progress row and its first two
self-test sets missed public false-greens. Codex therefore intervened only on
the frozen remaining seams.

This node improves the runtime context contract, but the construction pipeline
itself remains too context-heavy. That overhead is a Phase 2R blocking metric,
not a reason to claim success.

## Remaining in Phase 2R

- Run frozen before/after context measurement; the 25% target is not evaluated.
- Add the remaining risk-tier, incremental review and node-retry wiring as
  separately accepted nodes.
- Reduce AgentLab Coder packet/context overhead before another large repair task.

## Rollback

Revert the independent node implementation commit. Do not reset the
worktree or remove the unrelated Gate 1 candidate directories.
