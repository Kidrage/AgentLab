# AgentLab Config

This folder is the control panel for your local AgentLab workflow.

Edit these files first when you want to change how agents behave:

- `agent_registry.yml`: agent capabilities, permissions, templates, and required outputs.
- `model_providers.yml`: provider API keys, base URLs, and provider facts.
- `model_catalog.yml`: model facts, catalog provider labels, capabilities, and pricing notes.
- `agent_model_profiles.yml`: canonical agent backend mode and tier selection policy.
- `execution_modes.yml`: workflow driver mode selection; maps driver modes to agent backend modes.
- `worker_invocation_contracts.yml`: canonical CLI worker command templates.
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
- `mcp_policy.yml`: optional external-agent tool controls for task creation, approvals, and stop-task operations.
- `language_policy.yml`: operator-facing language preference for English/Chinese output.

Use `agent_templates/*.md` for role prompts and report formats. Use `config/*.yml`
for policy, routing, model, budget, and permission changes.

For model switching:

- Change agent backend defaults in `agent_model_profiles.yml`.
- Change model facts in `model_catalog.yml`.
- Change provider facts in `model_providers.yml`.
- Change CLI worker commands in `worker_invocation_contracts.yml`.
- Keep normal CLI role contracts renderable from `{task_packet_path}` and
  optional `{workspace_path}`; frontdesk session contracts are not role profiles.
- Override one run from the CLI with `--provider` or `--model`.
- Run `./agentlab.sh model-doctor` after model changes.

For agent execution mode switching:

- Use `AGENTLAB_MODE=full_cli` for local CLI-backed agents.
- Use `AGENTLAB_MODE=qwen_token_plan_cli` to use the preserved pre-2026-07-02
  full CLI role allocation with Qwen defaults routed through
  `QWEN_TOKEN_PLAN_API_KEY` / `QWEN_TOKEN_PLAN_BASE_URL`.
- Use `AGENTLAB_MODE=full_api` for direct API-backed agents.
- Use `AGENTLAB_MODE=hybrid_ide` when AgentLab plans/reviews and external IDE AI handles Coder.
- Use `AGENTLAB_BUDGET_MODE=max_quality|balanced|frugal` to select the `full|performance|low` tier.
- `trusted_headless_cli` is never default and requires its explicit env gate and human approval.

For language switching:

- Set `default_language` in `language_policy.yml` to `en-US` or `zh-CN`.
- Override per deployment with `AGENTLAB_LANGUAGE=en-US` or `AGENTLAB_LANGUAGE=zh-CN`.
- Keep command names, event names, JSON keys, and YAML keys in English for stable automation.

Current policy:

- AgentLab should self-drive through configured model APIs whenever possible.
- External IDE AI dispatches tasks, verifies artifacts, and fills gaps only when explicitly authorized.
- DeepSeek official API is available for high-quality brain/review work when configured.
- Qwen models must use DashScope (`DASHSCOPE_API_KEY`) by default. OpenRouter is not assumed.
- Qwen Token Plan is available only through explicit `qwen_token_plan_cli`
  mode and requires user-provided token plan API credentials.
- `Coder` defaults to `qwen-coder`/DashScope in API mode; `external_ide_ai` is a deliberate handoff/fallback, not the default.
- In `full_cli` mode, `Coder` is CLI-backed through the configured worker contract.
- Provider failures block or request user decision; external IDE AI must not silently simulate API agents.
