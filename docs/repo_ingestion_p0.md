# Repo Ingestion P0

AgentLab repository analysis now starts with API-only manifest generation.

- Use `ingestion.github_reader.build_repo_manifest()` for RepoScout and Researcher profile work.
- Use `ingestion.github_reader.write_repo_ingestion_artifacts()` to write `repo_manifest.json` and `resource_ledger.yml` together.
- Run proposed clone, dependency install, build, or test commands through `ingestion.clone_guard.evaluate_command()` before they reach execution policy.
- Keep `repo_profile` API-only. `repo_patch` may request sparse clone only. `repo_build_test` may request full clone/build, but the decision should be surfaced as pending approval before execution.

The clone guard is intentionally separate from `command_runner.py`: it is a higher-level repo-ingestion policy check, while `command_runner.py` remains the local validation command allowlist.
