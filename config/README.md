# AgentLab Config

This folder is the control panel for your local AgentLab workflow.

Edit these files first when you want to change how agents behave:

- `agent_registry.yml`: agent capabilities, permissions, templates, and required outputs.
- `model_providers.yml`: provider API keys, base URLs, and provider facts.
- `model_catalog.yml`: model facts, catalog provider labels, capabilities, and pricing notes.
- `agent_model_profiles.yml`: canonical agent backend mode and tier selection policy.
- `execution_modes.yml`: workflow driver mode selection; maps active AgentLab drivers to backend modes and retires unsafe legacy aliases.
- `worker_invocation_contracts.yml`: canonical CLI worker command templates.
- `routing_rules.yml`: when each agent route is selected.
- `budget_profiles.yml`: token budgets, warning thresholds, and stop rules.
- `brain_governance.yml`: token governance, traversal approvals, loop detection, and yes/no decision rules.
- `execution_policy.yml`: shared execution, provider-failure, and approval boundaries.
- `harness_policy.yml`: repo-local maps, feedback loops, mechanical gates, observability, and guidance garbage collection.
- `validation_gates.yml`: required evidence before a task can be accepted.
- `memory_policy.yml`: local-first storage, task records, project memory, and drift controls.
- `skill_evolution_policy.yml`: local skill lifecycle, adoption request, risk scan, and learning-cost policy.
- `skill_injection_policy.yml`: active skill retrieval, injection limits, risk approval, and usage ledger policy.
- `feedback_policy.yml`: feedback scaffold for task event logs, notification levels, decision cards, and watchdog policy.
- `watchdog_policy.yml`: stale running/event/approval/lock thresholds and recovery decision-card options.
- `webhook_policy.yml`: optional outbound webhook endpoints, retry policy, signing, and redaction controls.
- `mcp_policy.yml`: optional external-agent tool controls for task creation, approvals, and stop-task operations.

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

For agent backend mode switching:

- Use `AGENTLAB_MODE=full_cli` for local CLI-backed agents.
- `full_cli` is the only configured agent backend mode. Unknown or retired
  `AGENTLAB_MODE` values do not resolve a role profile and must stop.
- The default backend tier is `alter`: Hermes with Codex OAuth for supervision,
  native Codex for code/text artifacts, Agy Gemini 3.6 plus Exa for sourced
  research, Claude Code + DeepSeek V4 Pro for sealed long-form Writer packets,
  and Hermes + DeepSeek V4 Flash for bounded support/audit roles. Performance
  and low Writer tiers use Claude Code + DeepSeek V4 Flash.
  Grok routes are historical-only and cannot be selected by an active tier.
- Use `AGENTLAB_BUDGET_MODE=alter|max_quality|balanced|frugal` to select the
  `alter|full|performance|low` tier. A task line containing exactly `alter` or
  `budget_mode: alter` also selects it.
- Read the canonical `alter` role allocation from `agent_model_profiles.yml`
  and its governed capacity/fallback routes from `model_capacity.yml`; this
  overview intentionally does not duplicate that volatile matrix.

General policy:

- Workflow drivers do not select per-role models.
- Route config does not override invocation contracts.
- Worker/model/provider changes must come from the canonical profile, catalog,
  provider, and capacity authorities above.
- Provider failures block or request a decision unless a declared capacity route
  authorizes a same-role fallback.
- External IDE handoff is explicit and scoped to its assigned role.
