# M2-1.7 — Skill / MCP Capability Broker Acceptance Report

## Goal
Manage heterogeneous skills and MCP services across local workers without forcing every worker to install or expose the same skill/MCP set. Unify capability semantics, provider passports, permissions, cost, trust, transparency, and evidence.

## Status
All modules implemented and fully tested. 57 tests passed (all tests in AgentLab).

## Created Modules
- `agent_runtime/capability_broker/__init__.py`
- `agent_runtime/capability_broker/capability_provider.py`
- `agent_runtime/capability_broker/provider_passport.py`
- `agent_runtime/capability_broker/skill_discovery.py`
- `agent_runtime/capability_broker/mcp_discovery.py`
- `agent_runtime/capability_broker/broker_registry.py`
- `agent_runtime/capability_broker/provider_trust.py`
- `agent_runtime/capability_broker/provider_routing.py`
- `agent_runtime/capability_broker/brokered_invocation.py`
- `agent_runtime/capability_broker/delegated_capability.py`
- `agent_runtime/capability_broker/renderer.py`

## Created Configuration Templates
- `config/capability_provider_registry.yml`
- `config/skill_mcp_broker_policy.yml`
- `config/provider_trust_policy.yml`
- `config/mcp_permission_policy.yml`

## Registered CLI Commands
- `./agentlab.sh capability-providers`
- `./agentlab.sh capability-provider-inspect --provider <id>`
- `./agentlab.sh skill-discover --worker claude_code --safe`
- `./agentlab.sh mcp-discover --worker claude_code --safe`
- `./agentlab.sh capability-broker-plan --capability code_review`
- `./agentlab.sh provider-trust-report`

---

## Trust Report Demonstration

Below is the rendered trust report showing evaluation of trusted and provisional providers:

```markdown
# Provider Trust Report

| Provider ID | Source | Risk Level | Initial Trust | Evaluated Trust | Audition Required | Status |
|---|---|---|---|---|---|---|
| `agentlab_repo_scout_rg` | agentlab_owned | low | trusted | **trusted** | No | ✅ Active |
| `agentlab_test_runner_pytest` | agentlab_owned | low | trusted | **trusted** | No | ✅ Active |
| `claude_local_skill_code_review` | discovered | high | provisional | **provisional** | Yes | 🔄 Provisional |
| `claude_local_mcp_fs` | discovered | medium | provisional | **provisional** | Yes | 🔄 Provisional |
```

---

## Routing Plan Demonstration (read_only_repo_search)

```markdown
# Capability Routing Plan — read_only_repo_search

- **Requested Capability:** read_only_repo_search
- **Selected Provider:** `agentlab_repo_scout_rg`
- **Provider Type:** agentlab_owned_tool
- **Trust Level:** trusted
- **Invocation Mode:** direct
- **Risk Level:** low
- **Estimated USD Cost:** $0.0000
- **Routing Verdict:** Success

## Decision Logs & Rationale
- Selected best candidate agentlab_repo_scout_rg with priority level agentlab_owned_tool.
```
