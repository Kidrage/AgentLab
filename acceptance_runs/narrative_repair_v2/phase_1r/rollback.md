# Phase 1R rollback

Phase 1R is delivered as one independent commit after the accepted Phase 0R
baseline (`1dd5008`). Roll it back with `git revert <phase1r-commit>` after
checking that no later phase depends on it.

The revert removes the narrative production package, thin delivery/evaluation
adapters, Writer v2 materialization contract, consolidated tests, phase plans,
and Phase 1R evidence. It does not touch Crown or NovelGen Production,
provider state, release objects, or the three unrelated local Gate 1 candidate
directories.

If Phase 2R has started, revert dependent phase commits newest-to-oldest before
reverting Phase 1R. Do not use a destructive worktree reset.
