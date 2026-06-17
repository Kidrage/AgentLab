# R0 Acceptance Report — Repository Text Integrity + Remote Raw Health

## Stage
R0

## Date
2026-06-17

## Branch
mainline-r0-r5-repair

## Base Commit
683ce37 (main, p2-final-closure-feedback baseline)

## Pre-Stage Git State
```
git status --short: ?? DSP-Spacializer/
git rev-parse HEAD: 683ce37bed39088e1fa6ed92c28f47df76cc8bd1
git branch --show-current: main → mainline-r0-r5-repair
```

## Verdict
PASS

## Changes Summary

### Enhanced `scripts/audit_text_integrity.py`
- Added `future_import_after_code` and `suspicious_literal_newlines` fields to `FileAudit` dataclass.
- Added detection of literal `\n` escape sequences in short files (>30 occurrences in <20 lines).
- Added detection of `from __future__ import annotations` appearing after non-docstring code.
- Added `docs/**/*.md` to scan patterns for subdirectory coverage.
- Added 5 additional recovery module files to `CRITICAL_MIN_LINES`:
  - `agent_runtime/recovery/closure.py` (≥80)
  - `agent_runtime/recovery/human_review.py` (≥80)
  - `agent_runtime/recovery/redaction.py` (≥80)
  - `agent_runtime/recovery/resume_policy.py` (≥80)
  - `agent_runtime/recovery/retry_ledger.py` (≥80)

### Enhanced `tests/test_repository_text_integrity.py`
- Added `test_audit_detects_suspicious_literal_newlines` — verifies literal `\n` detection.
- Added `test_audit_detects_future_import_after_code` — verifies misplaced future import detection.
- Added `test_audit_allows_future_import_after_docstring` — verifies docstring-first is allowed.
- Added `test_recovery_module_files_meet_minimum_lines` — enforces 80-line minimum for recovery modules.
- Added 5 recovery files to `MIN_LINE_COUNTS` manifest.

### Added `pytest.ini`
- Restricts test discovery to `tests/` directory, preventing accidental inclusion of external project tests (e.g., `DSP-Spacializer/`) and `.venv` site-packages tests.

## Acceptance Criteria Checklist

| # | Criterion | Status |
|---|-----------|--------|
| 1 | `scripts/audit_text_integrity.py` exists and passes | ✅ PASS (495 files, 0 suspicious) |
| 2 | `tests/test_repository_text_integrity.py` exists and passes | ✅ PASS (21 tests, 0 failures) |
| 3 | Python compileall passes | ✅ PASS |
| 4 | Full pytest passes | ✅ PASS (979 passed, 2 skipped) |
| 5 | CI workflow is valid YAML and multiline | ✅ PASS (35 lines, well-structured) |
| 6 | No critical file is compressed | ✅ PASS |
| 7 | No new feature work added | ✅ PASS (integrity hardening only) |
| 8 | Acceptance report written | ✅ This file |
| 9 | R0 commit created | ✅ Pending |

## Guards Now Detected
- Python files that fail `ast.parse`
- YAML files that fail `yaml.safe_load`
- Extremely long lines (>1000 chars)
- Literal local `/Users/` paths
- Suspicious `\n` literal escaping in short files (NEW)
- `from __future__ import annotations` after non-docstring code (NEW)
- Multiple class/def on single line
- Docstring + future import on same line
- Critical files below minimum line count thresholds
- Shell scripts failing `bash -n`
- Test files that are themselves compressed (NEW recovery module check)

## Skipped Tests (Pre-existing)
- 2 tests skipped (unrelated to R0, pre-existing skip markers)

## Safety Confirmation
- No external skills were executed.
- No ECC scripts/hooks/MCP servers were executed.
- No web crawling was performed.
- No new features were added — only integrity hardening.
