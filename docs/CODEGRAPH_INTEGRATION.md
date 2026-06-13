# CodeGraph Integration

CodeGraph is an optional local repo indexer adapter. It is disabled by default
in `config/repo_indexing.yml` and is not installed or started by AgentLab.

Safety rules:

- remote GitHub URLs and git refs are rejected
- AgentLab never clones repos for CodeGraph
- `repo_profile` mode denies indexing
- status and dry-run are available without execution
- real indexing requires a local checkout, installed CLI, enabled config, and
  explicit `--approve-indexing`

Evidence artifacts are written under a task run's `artifacts/repo_index/`
directory or `artifacts/repo_index/` for standalone CLI use:

- `repo_index_ledger.yml`
- `codegraph_status.json`
- `repo_semantic_library.json`
- `skill_usage_ledger.yml`

Unknown token visibility remains `unknown`; API cost is `null` because CodeGraph
is treated as a local-resource provider.

