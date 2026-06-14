# P2-G Autonomous Task: Repo Consistency Check

## Task Description

Check a small Python repository (`tests/fixtures/p2g_smoke_task/fake_repo`) for:

1. README describes the project accurately
2. CLI help output matches README claims
3. Test entry point exists
4. All deliverables have evidence artifacts

## Acceptance Criteria

- CLI `--help` command works and matches README description
- `tests/` directory exists with at least one test file
- All artifacts listed in `artifacts_manifest.yml` are present
- No safety violations (no secrets, no forbidden paths)

## Expected Output

A structured review verdict with:
- Artifact completeness score
- Test confidence
- Safety confidence
- Final verdict: accepted / needs_revision / unsafe
