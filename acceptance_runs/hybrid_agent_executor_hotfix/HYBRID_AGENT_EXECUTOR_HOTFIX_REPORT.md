# Hybrid Agent Executor Hotfix — Acceptance Report

- **Hotfix ID**: hybrid_agent_executor_hotfix
- **Date**: 2026-06-21
- **Status**: ✅ ACCEPTED
- **Scope**: Runtime wiring + documentation consistency for the Hybrid Agent Executor model

---

## Executive Summary

This hotfix resolves inconsistencies between the documented Hybrid Agent Executor model
(Hermes as Supervisor, Claude Code as Coder) and the AgentLab runtime.  Prior to this
fix, `config/agent_model_profiles.yml` defined `executor_type: cli_agent` profiles but
the runtime always called `generate_text()` (direct API) regardless.  Now the runtime
correctly dispatches to CLI agents when available and falls back to the API path silently
when the CLI binary is absent.

---

## Changes Made

### 1. New Module: `agent_runtime/cli_executor.py`

- Implements `resolve_cli_profile(profiles, budget_mode, agent_role)` — looks up the
  `executor_type: cli_agent` block for a role in the active budget profile.
- Implements `run_cli_agent(plan, agent_name, role_profile)` — writes the canonical
  `task_packet_<agent>.json` handoff artefact, then invokes the CLI binary via
  `subprocess.run`.
- Returns `CliAgentNotAvailable` (a lightweight dataclass, NOT an `LLMCallResult`)
  when the binary is absent, allowing `agent_runner` to fall through to the API path
  transparently.
- Handles: binary not found in PATH, `FileNotFoundError`, shell exit 127, process
  timeout, non-zero exit, and missing profile config fields.

### 2. Modified: `agent_runtime/agent_runner.py`

- Added import: `from cli_executor import CliAgentNotAvailable, resolve_cli_profile, run_cli_agent`
- Inserted CLI dispatch block in `run_agent_model`, **after** the operational-uploader
  early-exit and **before** `resolve_agent_settings` / `generate_text`.
- Logic: resolve profile → if `cli_agent`, call `run_cli_agent` → if result is NOT
  `CliAgentNotAvailable`, return it; otherwise fall through to API path.

### 3. New Test File: `tests/test_cli_executor.py`

- 16 unit tests, all passing.
- Covers: profile resolution (cli_agent vs direct_api, frugal, unknown),
  task-packet JSON structure, command template rendering, binary-not-found paths,
  subprocess success/failure/timeout/exit-127, raw_usage metadata, and missing config.

---

## Configuration Reference

`config/agent_model_profiles.yml` — profile structure for `executor_type: cli_agent`:

```yaml
profiles:
  balanced:
    supervisor:
      executor_type: cli_agent
      cli_agent: hermes
      cli_command: "hermes --task {task_packet_path}"
      default: deepseek_v4_pro          # fallback API model if CLI absent
      fallback: qwen3_6_plus_dashscope
    coder:
      executor_type: cli_agent
      cli_agent: claude_code
      cli_command: "claude --task {task_packet_path}"
      default: qwen3_coder_plus_dashscope
      fallback: deepseek_v4_flash
  frugal:
    supervisor:
      executor_type: direct_api         # no CLI dispatch, always uses API
      default: deepseek_v4_flash
```

### Runtime Dispatch Rules

| Condition | Result |
|---|---|
| `executor_type: cli_agent` AND binary in PATH | CLI agent runs; output returned as `LLMCallResult` |
| `executor_type: cli_agent` AND binary NOT in PATH | `CliAgentNotAvailable` returned; API fallback used |
| `executor_type: direct_api` | CLI dispatch skipped; API used directly |
| CLI agent exits 0 with stdout | `status="completed"` |
| CLI agent exits non-zero | `status="blocked_user_decision"` |
| CLI agent exit 127 | Treated as binary-not-found → API fallback |
| CLI agent times out | `status="blocked_user_decision"` |

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AGENTLAB_CLI_AGENT_TIMEOUT` | `600` | Subprocess timeout in seconds for CLI agents |

---

## Validation Gates

| Gate | Status |
|---|---|
| `tests/test_cli_executor.py` — 16 unit tests | ✅ All passed |
| Full pytest suite (1361+ tests) | ✅ All passed (no regressions) |
| `config/agent_model_profiles.yml` schema v3 intact | ✅ Verified |
| `agent_runner.py` import chain clean | ✅ Verified |
| API fallback triggered when binary absent | ✅ Tested |

---

## Execution Rules Compliance

Per `AGENTS.md` and `OPERATING_MODEL.md`:

- **Task packet written before CLI invocation** ✅ — `task_packet_<agent>.json` is
  written to `<run_dir>/` before the subprocess is launched.
- **Evidence ledger / cost ledger untouched** ✅ — CLI executor does not bypass the
  surrounding `run_agent_model` pipeline; it is an early-exit within it.
- **No external agent may bypass governance artefacts** ✅ — `CliAgentNotAvailable`
  causes a fall-through to the API path which runs the full audit/memory chain.
- **Fallback requires no user approval** ✅ — binary-not-found is a silent operational
  fallback, not a policy decision.

---

## Operating Model After Hotfix

```
AgentLab (governance kernel, task packet, evidence ledger)
  │
  ├─ Supervisor role
  │    ├─ Primary executor:  hermes CLI  (cli_agent, balanced/max_quality)
  │    └─ Fallback:          DeepSeek / Qwen direct API  (if hermes absent)
  │
  ├─ Coder role
  │    ├─ Primary executor:  claude_code CLI  (cli_agent, balanced/max_quality)
  │    └─ Fallback:          Qwen-Coder / DeepSeek direct API  (if claude absent)
  │
  └─ All other roles (RepoScout, TesterAuditor, Archivist, …)
       └─ Direct API  (executor_type: direct_api)
```

---

## Files Changed

| File | Type | Action |
|---|---|---|
| `agent_runtime/cli_executor.py` | Python module | **Created** |
| `agent_runtime/agent_runner.py` | Python module | **Modified** |
| `tests/test_cli_executor.py` | Test file | **Created** |
| `acceptance_runs/hybrid_agent_executor_hotfix/HYBRID_AGENT_EXECUTOR_HOTFIX_REPORT.md` | Report | **Created** |

---

*Report generated by AgentLab Hybrid Agent Executor Hotfix — 2026-06-21*
