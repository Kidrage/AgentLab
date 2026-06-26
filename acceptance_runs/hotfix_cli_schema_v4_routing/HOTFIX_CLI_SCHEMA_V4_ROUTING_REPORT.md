# Hotfix CLI Schema v4 Routing — Acceptance Report

## Metadata

| Field | Value |
|-------|-------|
| **Branch** | `main` |
| **Commit** | `37f28cd` |
| **Date** | 2026-06-26 |
| **Schema version** | 4.0 |
| **Default mode** | `full_cli` |

## Changed Files

| File | Change |
|------|--------|
| `agent_runtime/cli_executor.py` | Rewrote `resolve_cli_profile()` to support schema v4 `modes` layout with legacy `profiles` fallback |
| `agent_runtime/agent_runner.py` | Updated CLI dispatch to pass mode/tier context; added audit annotation helpers; fixed `promptengineer` role key mapping |
| `tests/test_cli_executor.py` | Updated call signatures; added `TestResolveCliProfileSchemaV4` class (7 new tests) |
| `tests/test_agent_runner_cli_integration.py` | Added `TestAgentRunnerSchemaV4Dispatch` class (2 new tests) |
| `scripts/check_cli_schema_v4_routing.py` | New acceptance check script |
| `docs/CLI_AGENT_ROUTING_SCHEMA_V4.md` | New documentation |
| `acceptance_runs/hotfix_cli_schema_v4_routing/HOTFIX_CLI_SCHEMA_V4_ROUTING_REPORT.md` | This report |

## Preflight Findings

- Config at `config/agent_model_profiles.yml` uses schema v4: `schema_version: 4.0`, `default_mode: full_cli`
- Config has `modes` key, no `profiles` key
- Modes found: `full_cli`, `full_api`, `hybrid_ide`, `trusted_headless_cli`
- `full_cli` tiers: `full`, `performance`, `low`
- `full_cli/full/supervisor`: executor_type=cli_agent, cli_agent=hermes, default=deepseek_v4_pro
- `resolve_cli_profile()` was using old `profiles` key (line 88) — ignoring `modes`
- `model_resolver.py:226` already supported `modes` — mismatch between resolver and CLI dispatch

## Root Cause

`cli_executor.py:resolve_cli_profile()` only looked at `agent_model_profiles.get("profiles", {})`. Since the actual config has `modes` (not `profiles`), the function always returned `None`, causing `agent_runner` to silently skip CLI dispatch and fall through to direct API.

## Fix Summary

1. **`resolve_cli_profile`** now detects schema v4 (`modes` key) and traverses `modes[mode].tiers[tier][role]`. Resolves mode from explicit arg → `AGENTLAB_MODE` env → `default_mode` → `"full_cli"`. Resolves tier via `budget_mode_to_tier()`.

2. **`agent_runner`** now passes `agent_role`, `budget_mode`, and `mode` as keyword args. Records audit metadata on every result: `usage_source`, `executor_type`, `api_fallback_used`, `fallback_reason`, `resolved_schema`.

3. **Audit helpers** (`_audit_annotate_cli_result`, `_audit_annotate_api_fallback_result`, `_audit_annotate_api_result_source`) annotate `LLMCallResult.raw_usage` with execution provenance.

4. **`promptengineer`** role key mapping fixed: was `execution_prompt_engineer`, now `prompt_engineer` (matches config).

## Tests Run

```
42 passed in 1.27s
```

### Test Coverage

| # | Test | File | Status |
|---|------|------|--------|
| 1 | Schema v4 full_cli/full/supervisor resolves CLI | test_cli_executor.py | ✓ |
| 2 | Performance tier resolves from correct tier | test_cli_executor.py | ✓ |
| 3 | Low tier skip returns None | test_cli_executor.py | ✓ |
| 4 | Direct API role does not become CLI | test_cli_executor.py | ✓ |
| 5 | Legacy profiles still work | test_cli_executor.py | ✓ |
| 6 | No auto model injection into CLI command | test_cli_executor.py | ✓ |
| 7 | Budget mode frugal maps to low tier | test_cli_executor.py | ✓ |
| 8 | CLI attempted before API for schema v4 | test_agent_runner_cli_integration.py | ✓ |
| 9 | CLI unavailable produces API fallback with metadata | test_agent_runner_cli_integration.py | ✓ |
| + | All 24 pre-existing tests still pass | — | ✓ |

## Acceptance Script Output

```
check_cli_schema_v4_routing — acceptance check
schema_version: 4.0
default_mode: full_cli
has_modes: True
has_profiles: False
Modes found: ['full_api', 'full_cli', 'hybrid_ide', 'trusted_headless_cli']

Role                 Mode                 Tier            Resolved   Source
--------------------------------------------------------------------------------
supervisor           full_cli             full            CLI        modes_v4 → hermes
supervisor           full_cli             performance     CLI        modes_v4 → hermes
supervisor           full_cli             low             CLI        modes_v4 → hermes
coder                full_cli             full            CLI        modes_v4 → claude_code
coder                full_cli             performance     CLI        modes_v4 → claude_code
supervisor           full_api             full            —          direct_api
coder                hybrid_ide           full            —          special
interface_mapper     full_cli             low             —          skip
coder                full_api             performance     —          direct_api

✓ full_cli/full/supervisor → CLI (hermes)
PASS: All schema v4 routing checks passed.
```

## Known Limitations

1. `run_agent_model` in `agent_runner.py` calls `load_agentlab_configs` twice (once for CLI config, once in `resolve_agent_settings`). A future optimization could consolidate these.
2. Legacy profiles without `modes` use profile_name → tier normalization. Budget-mode names like `"max_quality"` are mapped to legacy names. If a legacy config uses non-standard profile names, they must be passed via `profile_name` kwarg.
3. The `trusted_headless_cli` safety gate is implemented but not covered by integration tests (requires env variable setup).
4. Existing text-integrity checks (`scripts/audit_text_integrity.py`, `scripts/check_remote_raw_integrity.py`) do not exist in this repo — noted per instructions.

## Verification Commands

```bash
python -m compileall agent_runtime scripts tests   # ✓ clean
python -m pytest -q                                  # ✓ 42 passed
python scripts/check_cli_schema_v4_routing.py        # ✓ PASS
./agentlab.sh --help                                 # ✓
./agentlab.sh run-pipeline --help                    # ✓
```
