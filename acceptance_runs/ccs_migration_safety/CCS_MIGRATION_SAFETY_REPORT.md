# AgentLab CCS Migration Safety Repair Report

## Verdict
PASS

## Baseline
- Branch: main
- Before commit: 493e746880f235fb62431828bddb14813beae857
- Repair commit: 4e2b03f688d7f2141d8cd491ef5af63b2bead935
- Remote: origin/main
- CI run URL: https://github.com/Kidrage/AgentLab/actions/runs/28164346033
- CI job URL: https://github.com/Kidrage/AgentLab/actions/runs/28164346033/job/83411487467
- CI conclusion: success

## Summary
CCS support is preserved, default execution is safe again, and the CI pytest failure is resolved.

## Failure Fixed
- Failed test: `tests/test_m2_12_operator_demo.py::test_m2_operator_demo_cli_strict_flag_is_exposed`
- Root cause: ANSI escape codes emitted by Rich/Typer in CI break contiguous flag strings like `--strict-migration`, causing substring assertions to fail even though the flag is correctly defined.
- Fix: Strip ANSI escape sequences from `CliRunner` output before substring assertions, making the test robust across terminal/no-terminal environments.

## Safety Fixes
- Claude Code remains high-risk and approval-gated.
- Claude Code is not default-enabled.
- `ccs` is preferred and legacy `claude` fallback is supported.
- Default profiles do not contain `--allow-dangerously-skip-permissions`.
- Dangerous headless CCS mode is isolated under `trusted_headless_cli`.
- Dangerous headless CCS mode requires `AGENTLAB_ALLOW_DANGEROUS_CCS=1`.
- Dangerous headless CCS mode requires human approval and is never default.
- CCS tests do not execute real external CLI binaries.

## Tests Run
- `python -m compileall agent_runtime agentlab_app.py`: PASS
- `python -m pytest -q`: PASS (1724 passed, 2 skipped)
- `./agentlab.sh --help`: PASS
- `./agentlab.sh run-pipeline --help`: PASS
- focused CCS safety tests (17 tests): PASS

## Acceptance Notes
1. `ccs` support works by configuration.
2. legacy `claude` fallback works by detection.
3. high-risk workers are not default-enabled.
4. dangerous permission skip is absent from default profiles.
5. dangerous permission skip is only present in explicit trusted profile.
6. no tests execute real external Claude/CCS binaries.
7. remote GitHub Actions is green.
