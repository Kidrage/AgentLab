# AgentLab Config

This folder is the control panel for your local AgentLab workflow.

Edit these files first when you want to change how agents behave:

- `agent_registry.yml`: agent capabilities, permissions, templates, and required outputs.
- `model_providers.yml`: provider API keys, base URLs, and default model env mappings.
- `model_profiles.yml`: model profile names, temperatures, and output limits.
- `routing_rules.yml`: when each agent route is selected.
- `budget_profiles.yml`: token budgets, warning thresholds, and stop rules.
- `brain_governance.yml`: token governance, traversal approvals, loop detection, and yes/no decision rules.
- `execution_policy.yml`: hard split between DeepSeek brain work and Codex coding work.
- `harness_policy.yml`: repo-local maps, feedback loops, mechanical gates, observability, and guidance garbage collection.
- `validation_gates.yml`: required evidence before a task can be accepted.
- `memory_policy.yml`: local-first storage, task records, project memory, and drift controls.

Use `agent_templates/*.md` for role prompts and report formats. Use `config/*.yml`
for policy, routing, model, budget, and permission changes.

For model switching:

- Change provider defaults in `model_providers.yml`.
- Change per-agent profile behavior in `model_profiles.yml`.
- Override one run from the CLI with `--provider` or `--model`.

Current policy:

- DeepSeek is the default low-cost reasoning provider.
- DeepSeek is required for AgentLab brain planning/review even for simulations and small tasks.
- `Coder` uses `codex_plus_manual` and should not consume DeepSeek tokens for real source edits.
- DeepSeek failures block and ask the user; Codex must not silently simulate the brain layer.
- If Codex quota is exhausted, AgentLab asks the user whether to pause for quota refresh or switch to DeepSeek brain + Qwen Coder API fallback.
- Qwen is registered as an optional OpenAI-compatible provider. Set `QWEN_API_KEY`, `QWEN_BASE_URL`, and model env vars in `agent_runtime/.env`, then select Qwen with a profile change or `run-agent --provider qwen --model ...`.
