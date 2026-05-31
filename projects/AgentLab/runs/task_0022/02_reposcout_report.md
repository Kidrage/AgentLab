# RepoScout Report

## Repository Map

| Directory | Purpose |
|---|---|
| agent_runtime/ | Core AgentLab Python runtime — CLI entrypoint, agent runner, state store, config loader |
| config/ | All AgentLab YAML configuration files (agent registry, models, routing, etc.) |
| agent_templates/ | Agent role prompt templates (supervisor, coder, etc.) |
| projects/ | Per-project working directories with runs/ and agent_docs/ |
| scripts/ | Utility shell scripts |
| web_ui/ | AgentLab Dash-based web UI |
| docs/ | Documentation (currently empty — target for new spec doc) |

## Relevant Files

| File | Why relevant | Read status |
|---|---|---|
| agentlab.sh | CLI entry point — needs new codex-* command wrappers | Full |
| DRIVER_PROTOCOL.md | Defines Codex modes — needs codex_full_driver addition | Full |
| config/execution_policy.yml | Execution policy — reference for creating execution_modes.yml | Full |
| agent_runtime/run_task.py | CLI commands implementation — pattern reference for new commands | Full |
| agent_runtime/state_store.py | State management — reference for handoff | Full |
| agent_templates/supervisor.md | Existing template format — reference for new templates | Not read yet |
| agent_templates/coder.md | Existing template format — reference for new templates | Not read yet |
| config/agent_registry.yml | Agent registry — reference for possible updates | Not read yet |

## Existing Runtime Entry Points
- agentlab.sh → agent_runtime/run_task.py (typer CLI)

## Existing Config Files
- config/execution_policy.yml — execution tier, coder strategies
- config/brain_governance.yml — brain token/traversal governance
- config/agent_registry.yml — agent model profiles
- config/validation_gates.yml — validation gate config

## Existing Agent Templates
- agent_templates/supervisor.md
- agent_templates/reposcout.md
- agent_templates/researcher.md
- agent_templates/interface_mapper.md
- agent_templates/coder.md
- agent_templates/tester_auditor.md
- agent_templates/archivist.md
- agent_templates/verifier.md

## Known Constraints from Repo
1. agentlab.sh is a thin wrapper that delegates to Python — new CLI commands should follow same pattern
2. run_task.py uses typer for CLI — new commands must integrate with existing typer app
3. agent_docs/ has required file structure (07_DEVELOPMENT_LOG.md, 08_CODEX_DIALOGUE_LOG.md, 09_COST_LEDGER.yml)
4. Execution policy uses T1-T5 tier system — new execution_modes.yml should complement not conflict

## Minimal Context for Coder
Coder needs: agentlab.sh pattern, typer command pattern from run_task.py, existing agent template format from agent_templates/

## Files Not Inspected
- config/model_catalog.yml (not needed)
- web_ui/ (out of scope)
- scripts/ (out of scope)

## Next Agent
Researcher