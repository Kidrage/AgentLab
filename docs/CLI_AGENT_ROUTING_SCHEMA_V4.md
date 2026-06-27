# CLI Agent Routing — Schema v4

## Overview

`config/agent_model_profiles.yml` schema v4 uses `modes` → `tiers` → `role`
layout. Each mode (e.g. `full_cli`, `full_api`, `hybrid_ide`) defines three
tiers (`full`, `performance`, `low`), and each tier maps agent roles to their
executor configuration.

## Key Concepts

- **`cli_agent`** means AgentLab invokes a local CLI worker selected by
  `config/agent_model_profiles.yml`.
- **`invocation_contract`** points to the command template in
  `config/worker_invocation_contracts.yml`.
- Runtime role profiles may reference only contracts renderable from a task
  packet: `{task_packet_path}` and, when needed, `{workspace_path}`. Frontdesk
  session contracts are not valid role-runner contracts.
- **`default`** / **`fallback`** model fields are API fallback/default metadata.
  They are NOT automatically injected into CLI commands as `-m` or `--model`
  flags.
- **AgentLab must not silently claim CLI usage when it fell back to API.**
  Transparent fallback recording is mandatory.
- **Codex / Hermes / Claude Code** shell commands and their API model
  configurations are separate concepts. The CLI executor runs the command; the
  API resolver calls model providers directly.

## Resolution Chain

```
schema v4 config
→ mode = AGENTLAB_MODE or default_mode or "full_cli"
→ tier = budget_mode_to_tier(AGENTLAB_BUDGET_MODE or plan.budget_mode)
→ role_cfg = modes[mode].tiers[tier][role]
→ if executor_type == "cli_agent":
    → create task packet
    → resolve invocation_contract from worker_invocation_contracts.yml
    → run configured worker command template
    → return provider/model source as CLI executor result
→ if CLI binary unavailable or CLI execution explicitly fails:
    → record transparent fallback reason
    → fall through to direct API
→ if executor_type == "direct_api":
    → direct API resolver handles it
→ if executor_type == "special" or role config is "skip":
    → do not invoke CLI
```

## Execution Source Auditability

Results and reports must distinguish:

| Case | usage_source | executor_type | Notes |
|------|-------------|---------------|-------|
| CLI executed successfully | `cli_agent` | `cli_agent` | `api_fallback_used: false` |
| CLI configured but binary unavailable | `api_usage` | `cli_agent_fallback` | `fallback_reason` recorded |
| Direct API selected by config | `api_usage` | `direct_api` | `api_fallback_used: false` |
| Role skipped | `skipped` | `skip` | No execution occurred |

## Budget Mode → Tier Mapping

- `full`, `max_quality` → `full`
- `performance`, `balanced`, `brain_allocated` → `performance`
- `low`, `frugal`, `low_cost` → `low`

## Legacy Profiles Support

Configs using the old `profiles` key (without `modes`) are still supported.
When `modes` is present, schema v4 resolution takes priority. Legacy profiles
are resolved via the `profile_name` kwarg using normalized name mapping.

## Safety Gate: `trusted_headless_cli`

The `trusted_headless_cli` mode requires:
- `AGENTLAB_ALLOW_DANGEROUS_CCS=1` environment variable set
- Explicit opt-in (never activated by default or env fallback)
