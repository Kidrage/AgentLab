# P1-C/D Bug Summary

## Syntax / Import Bugs
- bug: `python -m agent_runtime.search_cli --help` failed because legacy runtime modules expect `agent_runtime/` on `sys.path`.
- file: `agent_runtime/search_cli.py`
- fix: inserted the runtime directory into `sys.path` before importing adapter modules.
- status: fixed

- bug: `python -m agent_runtime.repo_index_cli --help` failed for the same package-versus-runtime import path reason.
- file: `agent_runtime/repo_index_cli.py`
- fix: inserted the runtime directory into `sys.path` before importing repo indexer modules.
- status: fixed

## Runtime / CLI Bugs
- bug: smoke commands initially placed global `--output-dir` after the subcommand, which argparse rejects.
- command: `python -m agent_runtime.search_cli search-web "AgentLab smoke test" --mock --output-dir /private/tmp/agentlab-search-smoke`
- fix: reran with global arguments before the subcommand and kept CLI help explicit.
- status: fixed

- bug: repo index smoke showed an empty repo display name for `--repo-path .`.
- command: `python -m agent_runtime.repo_index_cli --output-dir /private/tmp/agentlab-repo-index-status status --repo-path .`
- fix: normalized local repo display paths to the resolved basename.
- status: fixed

## Test Failures
- test: `tests/test_search_cli.py::{test_search_cli_help_works,test_search_cli_mock_writes_artifacts}`
- failure: module import failed before CLI help/rendering.
- root cause: runtime modules use top-level imports when invoked inside AgentLab.
- fix: added runtime directory to `sys.path` in the new CLI entrypoint.
- status: fixed

- test: `tests/test_repo_index_cli.py::{test_repo_index_cli_help_works,test_repo_index_status_writes_artifacts}`
- failure: module import failed before CLI help/rendering.
- root cause: same runtime import-path compatibility issue.
- fix: added runtime directory to `sys.path` in the new CLI entrypoint.
- status: fixed

## Contract / Safety Bugs
- issue: dry-run indexing could have been hard to reason about when approval flags were also present.
- risk: accidental execution if future logic changed around pending approval.
- fix: returned immediately for `dry_run=True` before considering approval.
- status: fixed

## Remaining Known Limitations
- AnySearch real API execution remains adapter-only and untested by design.
- CodeGraph real indexing requires the local CLI, enabled config, and explicit approval.
- MCP tools are documented as TODO for this round; no external MCP server is started.
