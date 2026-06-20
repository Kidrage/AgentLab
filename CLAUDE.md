# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

AgentLab is a local-first, semi-managed development workflow for agentic software work. It uses a 5-tier multi-model brain to plan, execute, audit, and archive coding tasks. External IDE AIs (Codex Plus, Claude, Cline) serve as the dispatch and acceptance layer — they write task requests and run CLI commands, while AgentLab's internal agents do the planning, implementation, audit, and archival work.

See `OPERATING_MODEL.md` for the full division of responsibilities between external IDE AI and AgentLab internal agents. See `DRIVER_PROTOCOL.md` for the step-by-step external-driver protocol.

## Common Commands

### Core CLI (via `./agentlab.sh`)

```bash
# Prepare a task plan (writes workflow_plan.yml + supervisor_plan.md)
./agentlab.sh prepare --project <ProjectName> --task-id <task_xxxx> --write-plan

# Task/project ops
./agentlab.sh project-init --project <ProjectName>
./agentlab.sh project-status --project <ProjectName>
./agentlab.sh brain-status --project <ProjectName> --task-id <task_xxxx>
./agentlab.sh harness-status --project <ProjectName> --task-id <task_xxxx>
./agentlab.sh policy-status --project <ProjectName>
./agentlab.sh log-event --project <ProjectName> --task-id <task_xxxx> --agent Coder --summary "..."

# Agent execution via API (requires --execute flag explicitly)
./agentlab.sh run-agent <AgentName> --project <ProjectName> --task-id <task_xxxx> --execute

# Hygiene checks
./agentlab.sh repo-hygiene-check --project <ProjectName>
```

The `agentlab.sh` shell script routes to either `agent_runtime/project_ops/cli.py` (for project-ops commands) or `agent_runtime/run_task.py` (for everything else). The main CLI is built with Typer and Rich.

### Running Tests

```bash
# All tests
pytest tests/

# Single test file
pytest tests/test_cli_contract.py

# Single test function
pytest tests/test_cli_contract.py::test_cli_prepare_outputs_plan

# With verbose output
pytest tests/ -v

# Integration/E2E tests only
pytest tests/ -k "e2e"
```

### Desktop App / Web UI

```bash
# Launch desktop app (requires pywebview)
python agentlab_app.py

# Run web UI server standalone (Python stdlib, port 8765)
python web_ui/server.py
```

## Architecture

### Five-Tier Brain Model

```
T1 Brain    Supervisor              → DeepSeek V4 Pro (planning, routing, decisions)
T2 Percept  RepoScout, Researcher,  → Qwen3.6-Plus / Qwen3.7-Max
            InterfaceMapper
T3 Execute  Coder, PromptEngineer   → Qwen3-Coder-Next (or DeepSeek API fallback)
T4 Audit    TesterAuditor, Verifier → Qwen3.6-Flash/Plus
T5 Archive  Archivist               → Qwen3.6-Plus / Qwen3.7-Max
```

Three budget modes select model tier per task: `brain_allocated` (default, cost-optimized), `max_quality` (best models), `frugal` (lightweight, supports local LLMs).

### Core Runtime (`agent_runtime/`)

- **`run_task.py`** — Main Typer CLI entrypoint (~210k, the largest file). Registers subcommands, handles task preparation, agent execution, brain governance checks, and lifecycle management. Has sub-typers for `external-skills`, `search`, and `repo-index`.

- **`lifecycle_graph.py`** — Canonical 17-node state machine (`INIT_TASK` → … → `FINALIZE`). Each node has required output artifacts; the pipeline runner steps through nodes one at a time, caller is responsible for iteration.

- **`pipeline_runner.py`** — Single-step node executor. Reads lifecycle state, runs one node, writes artifacts, returns next action. Supports quota simulation and resume.

- **`brain_governor.py`** — Token budget monitoring, harness status checks, traversal decision requests. Writes `USER_DECISION_REQUIRED.md` when the brain can't resolve ambiguity.

- **`task_router.py`** — Determines which agents are needed for a task based on routing policy config.

- **`llm_provider.py`** — Multi-provider abstraction: DeepSeek official API, DashScope (for Qwen profiles). Provider failover logic.

- **`model_resolver.py`** — Resolves `(budget_mode, project_size)` → specific model profile from `config/model_profiles.yml` and `config/model_catalog.yml`.

- **`workflow_plan.py`** — Builds `workflow_plan.yml` from task request, routing decisions, and budget.

- **`mcp_server.py`** — AgentLab as an MCP server for integration with external tools.

- **`skill_evolution.py`** / **`skill_distiller.py`** / **`skill_vault.py`** — Full skill lifecycle: discovery, distillation from task artifacts, vault storage, injection into agent prompts.

- **`workspace_scanner.py`** — Scans project repos to build context for agents.

- **`patch_applicator.py`** — Applies structured patch proposals from Coder agents to the working tree.

- **`artifact_contract.py`** — Validates that agent output artifacts meet content requirements (no placeholders, required sections present).

- **`cost_tracker.py`** / **`costing/`** — Token usage accounting across API providers.

**Key subdirectories under `agent_runtime/`:**
- `project_ops/` — CLI for project-level operations (init, hygiene, routing, compaction)
- `executors/` — Coder execution backends (API, external IDE handoff, mock)
- `recovery/` — Failure classification, retry logic, escalation, alternative route planning
- `governance/` — Cost governance, performance tracking, routing feedback
- `context_governance/` — Context window budgeting, compression, information profiling
- `intelligence/` — Web research pipeline (fetch → rank → extract → cite)
- `skills/` — Skill registry, discovery, incubation, usage tracking
- `local_search/` — Local codebase search and indexing
- `review/` — Review verdict collection and routing feedback
- `ingestion/` — GitHub repo reading and manifest building

### Agent Templates (`agent_templates/`)

Markdown role prompts for 9 agents: supervisor, reposcout, researcher, interface_mapper, coder, prompt_engineer, tester_auditor, verifier, archivist. Plus `codex_full_driver/` containing the full Codex IDE driver prompt templates.

### Configuration (`config/`)

~70 YAML files controlling every aspect of the system. Key ones:
- `agent_registry.yml` — Agent-to-model-profile bindings with budget mode variants
- `model_catalog.yml` — Model capabilities, pricing, provider assignments (schema v3.1)
- `model_profiles.yml` — Named profiles that combine model + parameters
- `validation_gates.yml` — Pre/post-execution gates with required evidence
- `routing_policy.yml` / `routing_rules.yml` — Task-to-agent routing logic
- `execution_policy.yml` — Coder execution mode controls
- `budget_policy.yml` — Token budget thresholds and limits
- `skill_vault.yml` — Central skill registry
- `external_skill_registry.yml` — Imported external skills

### Project Memory Model (`projects/`)

Each workspace project lives under `projects/<ProjectName>/` with:
- `agent_docs/` — Project-level memory files (development log, dialogue log, cost ledger)
- `runs/<task_id>/` — Per-task state: user_request.md, workflow_plan.yml, agent reports, brain decisions, artifacts
- `project_config.yml` — Project-specific policy overrides

AgentLab self-tracks using `projects/AgentLab/` — it's its own first user.

### Web UI (`web_ui/`)

Python stdlib HTTP server (`server.py`) + vanilla JS SPA (`app.js`, `index.html`). REST API that reads task state from the filesystem and triggers agent execution via CLI subprocess.

## Key Design Rules

- **External AI is not the brain.** Claude/Codex/other external AIs default to dispatch and acceptance — they must NOT perform planning, code review, or implementation unless the user explicitly authorizes manual rescue. See `OPERATING_MODEL.md` and `DRIVER_PROTOCOL.md`.

- **DeepSeek owns the brain layer.** Supervisor, planning, review, routing, and policy decisions use DeepSeek V4 Pro unless the user explicitly changes `config/execution_policy.yml`.

- **Local-first, file-based state.** Everything is stored as YAML/MD/JSON files under `projects/<ProjectName>/runs/<task_id>/`. There is no database — the filesystem is the state store.

- **Atomic I/O.** Use `atomic_write_text`, `atomic_write_yaml`, `atomic_write_json` from `agent_runtime/atomic_io.py` for all persistent writes. A root-level `atomic_io.py` re-exports these for backward compatibility.

- **CLI is conservative.** The `run-agent` command requires explicit `--execute` to actually call model APIs. Without `--execute`, the CLI is read-only (planning, inspection, status).

- **AgentLab only runs when explicitly invoked.** It must not auto-trigger on normal coding requests — the user or external IDE must explicitly start AgentLab workflows.

- **Provider: DeepSeek official API + DashScope (Qwen).** OpenRouter is not a default provider. See `config/model_providers.yml` and `config/model_catalog.yml`.

- **Never store credentials.** API keys go in `agent_runtime/.env`, which is gitignored.

- **Dual-End Collaboration and Sync Protocol (双端协作与同步协议)**:
  * **Architecture**:
    - **Local Host (Mac)**: Primary development environment and source of truth.
    - **Relay Hub (TrueNAS at `10.147.17.61:2222`)**: Shared repository and exchange relay station at `/mnt/hdd2/AgentLab_WorkSpace/`.
    - **Cloud Runtime (Server at `10.147.17.250`)**: Run/deployment server. Connected to `10.147.17.61` and directly accessible from Local Mac via SSH (`admin@10.147.17.250`).
  * **Sync Workflow**:
    - **Local Mac -> Relay Hub**: Push local changes to config, skills, memory snapshots using:
      `./agentlab.sh truenas-sync --execute`
      Or manual full rsync:
      `rsync -avz -e "ssh -p 2222" --exclude '__pycache__' --exclude '.pytest_cache' /Users/saintpeter/Desktop/AgentLab/ agentlab@10.147.17.61:/mnt/hdd2/AgentLab_WorkSpace/`
    - **Relay Hub -> Cloud Runtime (250)**: Remote agents on `10.147.17.250` pull workspace/skills/MCP updates from `10.147.17.61` to `/home/admin/AgentLab/` using:
      `ssh admin@10.147.17.250 "rsync -avz --exclude '__pycache__' --exclude '.pytest_cache' truenas:/mnt/hdd2/AgentLab_WorkSpace/ /home/admin/AgentLab/"`
    - **Cloud Runtime (250) -> Relay Hub -> Local Mac**: Tasks executed on `10.147.17.250` sync run logs back to `10.147.17.61` first, which then can be pulled to local Mac, maintaining synchronized memory capabilities.


