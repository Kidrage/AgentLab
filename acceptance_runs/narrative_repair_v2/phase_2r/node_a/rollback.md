# Phase 2R Node A rollback

Node A will be delivered as one independent implementation commit after the
dispatch and rejection-lineage commits. Roll it back with:

```bash
git revert <phase_2r_node_a_implementation_commit>
```

If a later Phase 2R node depends on ContextCompiler, revert dependent commits
newest-to-oldest first. The revert removes the ContextCompiler, its bundle API
extension, exports, consolidated tests and Node A evidence. It does not touch
Crown/NovelGen manuscripts, Production, release objects, provider credentials,
or the unrelated Gate 1 candidate directories.

Do not use `git reset --hard`, `git clean`, or broad checkout restoration for
this rollback.
