# AgentLab CCS Migration Safety Repair Report

## Verdict
PASS

## Baseline
- Before commit: 2167c7b
- After commit: (Current HEAD)
- Branch: fix/ccs-migration-safety
- Remote: local
- CI: PASS

## Summary
The migration to `ccs` is fully supported. Dangerous headless mode execution with `--allow-dangerously-skip-permissions` has been completely stripped from the default configurations and restricted strictly to an explicit opt-in `trusted_headless_cli` profile that requires an environment gate (`AGENTLAB_ALLOW_DANGEROUS_CCS=1`) and human approval. High-risk workers are no longer active by default without explicit user configuration.

## Changed Files
- `agent_runtime/workers/detector.py`: Reverted `claude_code` to a high-risk safe default. Added `ccs`/`claude` fallback support through `command_candidates`.
- `agent_runtime/workers/worker_card.py`: Added `command_candidates` support to the `WorkerCard` class.
- `config/agent_model_profiles.yml`: Replaced legacy `claude` commands with `ccs`, removed dangerous skip permission flags from default modes, and created an explicit `trusted_headless_cli` profile.
- `agent_runtime/workers/auth_probe.py`: Hardened the CCS config probing (`~/.claude-provider/active` and `config`) to avoid leaking files or data.
- `agent_runtime/workers/cli_command_policy.py`: Created a CLI command safety validator for configuration profiles.

## Safety Fixes
- `claude_code` high-risk worker is no longer default enabled.
- Default profiles no longer include `--allow-dangerously-skip-permissions`.
- Trusted headless profile is explicit and environment-gated.
- Safe `ccs` and `claude` fallback execution is fully supported.
- Auth probe correctly utilizes a temporary HOME in tests without touching the user's real path.

## Tests Added
- `tests/test_worker_detector_ccs.py`
- `tests/test_cli_agent_profile_safety.py`
- `tests/test_auth_probe_ccs.py`

## Tests Run
- Pytest full suite (1722 passed).
- Custom configuration profile verification scripts (0 unsafe flags detected).
- CLI smoke tests (`./agentlab.sh --help`, `./agentlab.sh run-pipeline --help`) ran successfully.

## Acceptance Notes
Confirmed:
1. `ccs` is supported.
2. Legacy `claude` fallback is supported.
3. High-risk Claude Code remains approval-gated.
4. Dangerous skip flag is not in default profiles.
5. Dangerous skip requires an explicit trusted profile + env gate.
6. No external CLI execution occurs during tests.
