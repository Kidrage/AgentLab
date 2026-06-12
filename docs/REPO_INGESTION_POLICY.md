# Repository Ingestion Policy

## P0.1 Default

For GitHub URL repository analysis tasks, AgentLab uses API-first
`repo_profile` mode by default:

- `clone_allowed: false`
- `full_clone_allowed: false`
- `build_allowed: false`
- `clone_performed: false`

The pipeline extracts `github.com/<owner>/<repo>` URLs, including `tree/<ref>`
and `blob/<ref>/<path>` forms, and builds a `RepoManifest` using GitHub API tree
metadata plus targeted key-file reads.

## Strict Sparse Clone Policy

`repo_patch` mode only auto-allows a strict sparse clone command that includes:

- shallow depth (`--depth=1` or equivalent `--depth N`),
- `--filter=blob:none`, and
- `--sparse`.

Examples not considered sparse enough:

- `git clone --depth=1 <repo>`
- `git clone --single-branch <repo>`
- `git clone --filter=blob:none <repo>`

Clone-after sparse-checkout session tracking is not implemented in P0.1; use the
single-command strict sparse form instead.

## Evidence Requirements

Reports that claim repository analysis must have `repo_manifest.json` evidence.
Reports that claim file reads must match `repo_manifest.files_read` or
`files_skipped_by_policy`. Clone claims must match `resource_ledger.yml`, and
build/test/command claims must match `execution_log.yml`.