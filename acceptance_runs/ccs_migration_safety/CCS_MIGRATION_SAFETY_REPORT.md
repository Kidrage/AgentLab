# AgentLab CCS Migration Safety Repair Report

## Verdict
PASS

## Baseline
- Branch: fix/ccs-migration-safety
- Before commit: 880714f
- After commit: (Current HEAD)
- Remote: local
- CI: PASS

## Summary
CCS support is preserved, but default execution is safe again.

## Changed Files
- `agent_runtime/workers/cli_command_policy.py`: Refactored ProfileSafetyFinding dataclass to match new validation schema.
- `tests/test_cli_agent_profile_safety.py`: Added explicit tests for profile safety validator.
- `docs/CCS_CLAUDE_CODE_SWITCH.md`: Added concise documentation for CCS and legacy fallback safety guarantees.
- `acceptance_runs/ccs_migration_safety/CCS_MIGRATION_SAFETY_REPORT.md`: Updated to match strictly the new format requirements.

## Safety Fixes
- Claude Code remains high-risk and approval-gated.
- Claude Code is not default-enabled.
- Default profiles no longer contain `--allow-dangerously-skip-permissions`.
- Dangerous headless CCS mode is isolated under `trusted_headless_cli`.
- Dangerous headless CCS mode requires an environment gate.
- `ccs` is preferred, legacy `claude` fallback is supported.
- CCS auth probe is tested with temporary HOME.

## Tests Added
- `tests/test_worker_detector_ccs.py` (5 fallback logic & default safety tests)
- `tests/test_cli_agent_profile_safety.py` (5 profile validation tests)
- `tests/test_auth_probe_ccs.py` (5 safe-probing integration tests)

## Tests Run
- Pytest suite `python -m pytest -q` passed with all tests green.
- Config center YAML parser load logic passed.
- CLI execution and profiling validator scripts successfully verified isolation of dangerous flags.

## Acceptance Notes
Confirm:
1. `ccs` support works by configuration.
2. legacy `claude` fallback works by detection.
3. high-risk workers are not default-enabled.
4. dangerous permission skip is absent from default profiles.
5. dangerous permission skip is only present in explicit trusted profile.
6. no tests execute real external Claude/CCS binaries.
