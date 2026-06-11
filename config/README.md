# AgentLab Config

This folder is the control panel for your local AgentLab workflow.

Edit these files first when you want to change how agents behave:

- `agent_registry.yml`: agent capabilities, permissions, templates, and required outputs.
- `model_providers.yml`: provider API keys, base URLs, and default model env mappings.
- `model_catalog.yml`: model facts, catalog provider labels, capabilities, and pricing notes.
- `agent_model_profiles.yml`: budget/size/risk model selection policy.
- `routing_rules.yml`: when each agent route is selected.
- `budget_profiles.yml`: token budgets, warning thresholds, and stop rules.
- `brain_governance.yml`: token governance, traversal approvals, loop detection, and yes/no decision rules.
- `execution_policy.yml`: hard split between DeepSeek brain work and Codex coding work.
- `harness_policy.yml`: repo-local maps, feedback loops, mechanical gates, observability, and guidance garbage collection.
- `validation_gates.yml`: required evidence before a task can be accepted.
- `memory_policy.yml`: local-first storage, task records, project memory, and drift controls.
- `skill_evolution_policy.yml`: local skill lifecycle, adoption request, risk scan, and learning-cost policy.
- `skill_injection_policy.yml`: active skill retrieval, injection limits, risk approval, and usage ledger policy.
- `feedback_policy.yml`: feedback scaffold for task event logs, notification levels, decision cards, and watchdog policy.
- `watchdog_policy.yml`: stale running/event/approval/lock thresholds and recovery decision-card options.
- `webhook_policy.yml`: optional outbound webhook endpoints, retry policy, signing, and redaction controls.

Use `agent_templates/*.md` for role prompts and report formats. Use `config/*.yml`
for policy, routing, model, budget, and permission changes.

For model switching:

- Change provider defaults in `model_providers.yml`.
- Change model facts in `model_catalog.yml`.
- Change per-agent route/profile references in `agent_registry.yml`.
- Override one run from the CLI with `--provider` or `--model`.
- Run `./agentlab.sh model-doctor` after model changes.

Current policy:

- AgentLab should self-drive through configured model APIs whenever possible.
- External IDE AI dispatches tasks, verifies artifacts, and fills gaps only when explicitly authorized.
- DeepSeek official API is available for high-quality brain/review work when configured.
- Qwen models must use DashScope (`DASHSCOPE_API_KEY`) by default. OpenRouter is not assumed.
- `Coder` defaults to `qwen-coder`/DashScope in API mode; `external_ide_ai` is a deliberate handoff/fallback, not the default.
- Provider failures block or request user decision; external IDE AI must not silently simulate API agents.
