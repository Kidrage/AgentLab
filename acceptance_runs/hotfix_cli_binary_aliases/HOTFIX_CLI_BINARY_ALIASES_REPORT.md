# Hotfix CLI Binary Aliases — Acceptance Report

**Date**: 2026-06-26
**Branch**: `main`
**Schema version**: 4.0

---

## Problem

Machines without a local `ccs` alias caused AgentLab to treat Claude Code CLI
as unavailable, even when the official `claude` binary was installed. The
`cli_command` templates used `ccs` as the binary, and the executor only checked
`argv[0]` without a candidate fallback mechanism.

Additionally, `resolve_cli_profile()` only supported schema v3 (`profiles` key)
while the active config uses schema v4 (`modes`/`tiers`), meaning CLI agent
dispatch was silently broken for all agents.

---

## Changes

### 1. `agent_runtime/cli_executor.py`

- **`resolve_cli_profile`**: Updated signature to `(agent_model_profiles, agent_role, budget_mode)`. Added schema v4 support (`modes` → `default_mode` → `tiers` → `tier` → `role`). Backward-compatible with schema v3.
- **`_resolve_binary_candidate`**: New helper — returns the first available binary from a candidate list via `shutil.which()`.
- **`run_cli_agent`**: Added `binary_candidates` resolution block between template rendering and binary availability check. Falls back to existing `_binary_available` check when no candidates are configured.
- **`raw_usage`**: Now includes `binary` (actual executed binary) and `binary_candidate_used` (when a candidate was resolved).

### 2. `agent_runtime/agent_runner.py`

- **`resolve_cli_profile` call** (line 234): Fixed from `resolve_cli_profile(agent_model_profiles, budget_mode, agent_role_key)` to `resolve_cli_profile(agent_model_profiles, agent_role_key, budget_mode=budget_mode)`.
- **PromptEngineer mapping** (line 228): Fixed from `"promptengineer": "execution_prompt_engineer"` to `"promptengineer": "prompt_engineer"` to match schema v4 config keys.

### 3. `config/agent_model_profiles.yml`

- All 5 `claude_code` roles now have `binary_candidates: [claude, ccs]`.
- Command templates already used `claude` as the primary binary (was already correct).

### 4. `scripts/check_cli_binary_aliases.py` (new)

- Validates all `cli_agent` roles for binary consistency.
- Known mappings: claude_code→claude (ccs legacy), hermes→hermes, agy→agy, codex→codex, openclaw→openclaw.
- Exit nonzero on: missing `binary_candidates` for claude_code, ccs-only configs, empty commands, parse failures, unknown agents without explicit candidates.

### 5. Tests

- **`test_cli_executor.py`**: 28 tests (was 15). Added: schema v4 resolution, binary_candidates resolution (canonical first, legacy fallback, none available, no candidates), `_resolve_binary_candidate` unit tests, hermes/agy unaffected.
- **`test_agent_runner_cli_integration.py`**: 20 tests (was 16). Added: PromptEngineer mapping verification, resolve_cli_profile call signature tests for Coder and Supervisor routes.

### 6. Documentation

- `docs/CLI_BINARY_ALIASES.md` — Full reference for cli_agent, cli_command, binary_candidates, known mappings, resolution logic.
- `acceptance_runs/hotfix_cli_binary_aliases/CLI_COMMAND_INVENTORY.md` — Complete role inventory.
- `acceptance_runs/hotfix_cli_binary_aliases/HOTFIX_CLI_BINARY_ALIASES_REPORT.md` — This report.

---

## Test Results

```
tests/test_cli_executor.py ............................... 28 passed
tests/test_agent_runner_cli_integration.py .............. 20 passed
Total: 48 passed in 0.32s
```

---

## Validation Script Output

```
python scripts/check_cli_binary_aliases.py
======================================================================
Config: .../config/agent_model_profiles.yml
Schema version: 4.0
Modes found: ['full_cli', 'full_api', 'hybrid_ide']
======================================================================
  ... (24 CLI agent roles inspected) ...

Total CLI agent roles: 24
Errors: 0

✅ All CLI binary alias checks passed.
```

---

## Known Limitations

1. **Schema v4 dispatch only recently re-enabled**: `resolve_cli_profile` was
   previously unable to find any CLI profiles in schema v4 configs, so ALL
   agent calls fell through to the direct API path. This hotfix restores CLI
   dispatch for the `full_cli` mode, but hasn't been tested with real hermes/agy
   binaries in this session (requires those binaries on PATH).

2. **No trusted headless profile in current config**: The config does not contain
   a `--allow-dangerously-skip-permissions` variant. If one is added later, it
   should follow the same `binary_candidates` pattern.

3. **CI does not require external CLI binaries**: The validation script and
   tests only check config shape. Actual CLI binary availability must be
   verified in the deployment environment.

4. **No `codex` or `openclaw` entries exist**: The known mappings table includes
   them for future use, but no roles currently use these agents.
