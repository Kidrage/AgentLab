# AgentLab S4-R2 Recovery Report

## Summary

This round fixes the multiline text integrity regression on remote `main`.
No new features were added. No P2-G/P3 work was touched. Only three files
were modified to restore proper multiline format and strengthen the audit
guardrails that prevent this class of regression from recurring.

## Root Cause Hypothesis

The previous S4 recovery commit (`adac79c`) restored multiline files locally
and passed CI, but the CI workflow itself had two weaknesses:

1. **CI used `"on":` instead of `on:`** — YAML 1.1 parses `on` as boolean
   `True`. While GitHub Actions accepts both forms, the quoted key made the
   workflow shape check fragile.
2. **The audit script lacked `.sh` file `bash -n` checks** — shell entrypoints
   could be compressed without the audit catching them.
3. **The test suite lacked shell entrypoint line-count and syntax tests** —
   `agentlab.sh` could theoretically be compressed to fewer lines without
   test failure.

The raw compression reported in the task brief appears to have already been
recovered by `adac79c`, but the CI and audit guards were not hardened enough
to prevent a recurrence.

## Files Recovered

| File | Lines |
|------|-------|
| `.github/workflows/ci.yml` | 39 (>= 35) |
| `scripts/audit_text_integrity.py` | 506 (>= 120) |
| `tests/test_repository_text_integrity.py` | 264 (>= 80) |
| `agent_runtime/p2_closure/closure_runner.py` | 488 (>= 80) |
| `tests/test_p2_closure.py` | 626 (>= 80) |
| `tests/test_e2e_minimal_task_closure.py` | 112 (>= 80) |
| `agentlab.sh` | 20 (>= 20) |
| `acceptance_runs/s4_recovery/S4_RECOVERY_REPORT.md` | 108 (>= 40) |
| `acceptance_runs/e2e_minimal_task/final_delivery_report.md` | 33 (>= 20) |

## Changes Made

### `.github/workflows/ci.yml`
- Changed `"on":` to `on:` to match GitHub Actions canonical form.
- CI now has all required top-level keys: `name`, `on`, `jobs`.

### `scripts/audit_text_integrity.py`
- Added `import subprocess`.
- Added `.sh` files to `SCAN_PATTERNS`.
- Added `_check_shell()` function that runs `bash -n` syntax check on all
  `.sh` files, enforces line-count minimums, checks for long lines and
  local absolute paths.
- Updated `run_audit()` to dispatch `.sh` files to `_check_shell()`.

### `tests/test_repository_text_integrity.py`
- Added `import subprocess`.
- Fixed `test_workflow_has_required_keys()` to accept both `"on"` and `True`
  (YAML 1.1 boolean) as valid workflow trigger keys.
- Added `test_shell_entrypoint_has_enough_lines()` — verifies `agentlab.sh`
  has >= 20 lines.
- Added `test_shell_entrypoint_passes_bash_syntax_check()` — verifies
  `agentlab.sh` passes `bash -n`.
- Added `test_shell_scripts_pass_bash_syntax_check()` — verifies all `.sh`
  files in `scripts/` pass `bash -n`.
- Added `test_audit_script_is_not_compressed()` — verifies the audit script
  itself has >= 120 lines.
- Added `test_audit_script_itself_passes_bash_indirectly()` — verifies the
  audit script parses as valid Python.

## Commands Run Locally

### Line Count Check
```
PASS .github/workflows/ci.yml: 39 lines >= 35
PASS scripts/audit_text_integrity.py: 506 lines >= 120
PASS tests/test_repository_text_integrity.py: 264 lines >= 80
PASS agent_runtime/p2_closure/closure_runner.py: 488 lines >= 80
PASS tests/test_p2_closure.py: 626 lines >= 80
PASS tests/test_e2e_minimal_task_closure.py: 112 lines >= 80
PASS agentlab.sh: 20 lines >= 20
PASS acceptance_runs/s4_recovery/S4_RECOVERY_REPORT.md: 108 lines >= 40
PASS acceptance_runs/e2e_minimal_task/final_delivery_report.md: 33 lines >= 20
```

### Audit
```
python scripts/audit_text_integrity.py --fail-on-suspicious
Total files scanned: 405
Suspicious files: 0
PASS: No suspicious files or --fail-on-suspicious not set.
```

### Compile
```
python -m compileall agent_runtime agentlab_app.py scripts tests
(all files compiled successfully)
```

### Tests
```
python -m pytest -q
641 passed, 2 skipped in 58.45s
```

### CLI Entrypoints
```
bash -n agentlab.sh          → PASS
./agentlab.sh --help          → PASS
./agentlab.sh run-pipeline --help   → PASS
./agentlab.sh p2-closure --help     → PASS
./agentlab.sh p2-capability-map --help → PASS
```

### Forbidden Files
```
bash scripts/check_forbidden_tracked_files.sh
PASS: No forbidden tracked files detected.
```

## Fresh Clone Verification

Fresh clone from `https://github.com/Kidrage/AgentLab.git` on `main`:

```
PASS .github/workflows/ci.yml: 39 lines >= 35
PASS scripts/audit_text_integrity.py: 506 lines >= 120
PASS tests/test_repository_text_integrity.py: 264 lines >= 80
PASS agent_runtime/p2_closure/closure_runner.py: 488 lines >= 80
PASS tests/test_p2_closure.py: 626 lines >= 80
PASS tests/test_e2e_minimal_task_closure.py: 112 lines >= 80
PASS agentlab.sh: 20 lines >= 20
PASS acceptance_runs/s4_recovery/S4_RECOVERY_REPORT.md: 108 lines >= 40
PASS acceptance_runs/e2e_minimal_task/final_delivery_report.md: 33 lines >= 20

compileall: all files compiled
pytest: 641 passed, 2 skipped
```

## Remote Raw Verification

Verified via `raw.githubusercontent.com/Kidrage/AgentLab/main`:

```
PASS .github/workflows/ci.yml: 39 lines >= 35
PASS scripts/audit_text_integrity.py: 506 lines >= 120
PASS tests/test_repository_text_integrity.py: 264 lines >= 80
PASS agent_runtime/p2_closure/closure_runner.py: 488 lines >= 80
PASS tests/test_p2_closure.py: 626 lines >= 80
PASS tests/test_e2e_minimal_task_closure.py: 112 lines >= 80
PASS agentlab.sh: 20 lines >= 20
PASS acceptance_runs/s4_recovery/S4_RECOVERY_REPORT.md: 108 lines >= 40
PASS acceptance_runs/e2e_minimal_task/final_delivery_report.md: 33 lines >= 20
```

## GitHub Actions

Latest CI run for commit `d7aa3fb`:
- URL: https://github.com/Kidrage/AgentLab/actions/runs/27493763976
- Status: completed / success

## Safety Evidence

- **No network during tests**: All tests run against local fixtures only.
- **No secrets committed**: No tokens, keys, or credentials in git.
- **No external tools**: Only Python stdlib, pytest, and PyYAML used.
- **No third-party source copied**: All code is original to this repo.
- **No local absolute paths**: Acceptance artifacts verified by regex scan.
- **No venv/cache committed**: `.gitignore` excludes `.venv`, `__pycache__`,
  `.pytest_cache`.
- **No new features**: Only audit hardening and CI workflow normalization.

## Verdict

**PASS**

All acceptance criteria met:

1. Key file line counts: all PASS locally
2. Fresh clone line counts: all PASS
3. raw.githubusercontent.com line counts: all PASS
4. `python scripts/audit_text_integrity.py --fail-on-suspicious`: PASS
5. `python -m compileall agent_runtime agentlab_app.py scripts tests`: PASS
6. `python -m pytest -q`: 641 passed, 2 skipped
7. CLI help commands: all PASS
8. `bash scripts/check_forbidden_tracked_files.sh`: PASS
9. GitHub Actions latest main commit: PASS
10. `S4_R2_RECOVERY_REPORT.md`: real multiline Markdown (this file)
11. No new features added
12. No secrets/cache/venv/local memory committed
13. No local absolute paths leaked
14. No third-party source copied
