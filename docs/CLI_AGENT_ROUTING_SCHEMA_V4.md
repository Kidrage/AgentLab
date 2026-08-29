# CLI Agent Routing — Schema v4

## Overview

`config/agent_model_profiles.yml` schema v4 uses `modes` → `tiers` → `role`
layout. `full_cli` is the only configured mode. It defines four tiers
(`alter`, `full`, `performance`, `low`), and each tier maps agent roles to their
executor configuration.

## Key Concepts

- **`cli_agent`** means AgentLab invokes a local CLI worker selected by
  `config/agent_model_profiles.yml`.
- **`invocation_contract`** points to the command template in
  `config/worker_invocation_contracts.yml`.
- Runtime role profiles may reference only contracts renderable from a task
  packet: `{task_packet_path}` and, when needed, `{workspace_path}`. Frontdesk
  session contracts are not valid role-runner contracts.
- **`default`** is the selected model catalog key for that role, mode, and tier.
  CLI command rendering is still owned by `worker_invocation_contracts.yml`.
- Profile-local fallback fields are forbidden. Automatic fallback is allowed
  only through an explicit route in `model_capacity.yml`.
- **AgentLab must not silently claim CLI usage when it fell back to API.**
  Transparent fallback recording is mandatory.
- **Codex / Hermes / Claude Code** shell commands and model-provider facts are
  separate concepts. The CLI executor runs the configured worker contract.

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
    → stop and report, or use an explicitly approved same-role capacity route
→ if executor_type == "special" or role config is "skip":
    → do not invoke CLI
```

Unknown or retired `AGENTLAB_MODE` values have no role matrix and therefore
must resolve as unavailable rather than switching executor or provider.

## Execution Source Auditability

Results and reports must distinguish:

| Case | usage_source | executor_type | Notes |
|------|-------------|---------------|-------|
| CLI executed successfully | `cli_agent` | `cli_agent` | `api_fallback_used: false` |
| CLI configured but binary unavailable | `api_usage` | `cli_agent_fallback` | `fallback_reason` recorded |
| Role skipped | `skipped` | `skip` | No execution occurred |

## Budget Mode → Tier Mapping

- `alter`, `altered` → `alter` (default subscription-first tier)
- `full`, `max_quality` → `full`
- `performance`, `balanced`, `brain_allocated` → `performance`
- `low`, `frugal`, `low_cost` → `low`
