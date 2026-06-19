# AgentLab

Language: [English](README.en-US.md) | [中文](README.zh-CN.md)

AgentLab is a local-first AI Production OS and Project-to-Revenue OS under active development. It is not a replacement for Codex, Claude Code, Cline, Hermes, OpenClaw, or other executor/front-end agents. AgentLab is the backend truth source that keeps long-running projects governed, inspectable, recoverable, and evidence-backed.

Current repository: `Kidrage/AgentLab` on `main`.

## What AgentLab Does

AgentLab turns a rough user goal into a governed project workflow:

```text
user requirement
-> mission / task contract
-> project roadmap
-> phase plan
-> task packet
-> local or external executor handoff
-> artifact and evidence ingestion
-> review / retry / recovery
-> phase acceptance
-> project memory update
-> delivery package
-> future asset, production, revenue, and SOP loops
```

The default design is local-first and approval-gated. Real external execution, external skill installation, network access, platform posting, and public server exposure are disabled unless an explicit policy and user approval allow them.

## Current Stage

AgentLab already has the long-project governance foundation from the P-series and S-series work. The next product mainline is the M-series:

- `M1 Project Governance Kernel`: formalize long-running project governance and local CLI executor coordination.
- `M2 Operator OS / Transparent Control Plane`: make operations, configuration, approvals, cost, and observability transparent through CLI/TUI/WebUI/assistant modes.
- `M3 Project-to-Revenue OS`: add business contracts, asset lineage, production pipelines, market/channel intelligence, analytics, revenue tracking, compliance, CRM, and SOP learning.

Practical status: AgentLab is in the M-series alignment stage. Many S-series foundations are implemented, especially S7/S8, but M0/M1 acceptance should still be consolidated before moving to M2 and M3.

## Implemented Capabilities

### Core Runtime And Governance

- Local-first task state, project memory, run directories, and evidence artifacts.
- Canonical task lifecycle with checkpointing and resume support.
- 9-agent tiered operating model: Supervisor, RepoScout, Researcher, InterfaceMapper, PromptEngineer, Coder, TesterAuditor, Verifier, Archivist.
- Route profiles for small, medium, interface-sensitive, research-sensitive, and large/risky tasks.
- Brain governance with provider/model policy, token budgets, and route-aware execution.
- Budget planner, BudgetGate, CostLedger v2, pricing, and cost tracker.
- Artifact evidence gate and canonical artifact contract validation.
- Atomic state store, progress tracker, task index, task discovery, and task resume commands.
- Guard system for file locks, stale lock recovery, and crash-safe task handling.
- Provider failover, provider status checks, and model wiring diagnostics.

### CLI And Local Operations

- One-command entrypoint: `./agentlab.sh`.
- Health check: `./agentlab.sh doctor`.
- Policy and model inspection: `policy-status`, `models`, `providers`, `model-doctor`.
- Task operations: `init-task`, `task-list`, `task-open`, `task-map`, `task-artifacts`, `progress`, `pause`, `resume`.
- Pipeline operations: `run-agent`, `run-pipeline`, `run-next`, `lifecycle-status`, `artifact-check`.
- Local terminal chat and Codex full-driver handoff/resume helpers.
- Project ops commands for route inspection, hygiene checks, task compaction, and agent contribution summaries.
- Backup, migration, TrueNAS, and sync status commands.

### P0 Core Infrastructure

- CostLedger v2, cost pricing, BudgetGate, budget planner.
- RepoManifest, CloneGuard, ResourceLedger.
- Artifact Evidence Gate.
- Pipeline Runner and cost tracker.

### P1 External Integration

- External skill registry with disabled-by-default safety.
- ECC inventory scan-only workflow.
- External agent handoff artifacts for tools such as Codex/Cline/ECC, with no automatic execution.
- AnySearch adapter disabled by default.
- CodeGraph adapter local/dry-run only.
- Search provider base and local URL reader.

Safety posture:

- External skills are not enabled by default.
- External skills are not executed during tests.
- External agents are handoff-only and approval-gated.
- External costs are unknown unless explicitly reported.
- Evidence is required before external results can be accepted.

### P2 Review, Retry, Governance, And Recovery

- 3E reviewer, review models, and review policy.
- Retry manager, retry policy, and provider scorecard.
- Router patch builder/applier for governance-aware route updates.
- Context governance and context pack generation.
- P2 closure runner and capability map.
- Governance modules for performance, cost, and routing feedback.
- Failure recovery stack: event capture, classifier, diagnosis, recovery plan, verdict, retry policy, human review, resume policy, closure, closure feedback, and redaction.
- Recovery CLI commands: `failure-diagnose`, `failure-status`, `recovery-plan`, `recovery-smoke`, `recovery-approve`, `recovery-reject`, `recovery-stop`, `recovery-status`, `recovery-feedback`.

### S7 Long Project Orchestrator

- Deterministic project brain generation with no LLM calls, network access, or external executor dispatch.
- Roadmaps, milestone graphs, phase plans, summaries, snapshots, acceptance history, and next actions.
- CLI: `project-brain-init`, `project-plan`, `project-next`, `phase-accept`.
- Phase acceptance can drive accept, retry, redesign, split, rollback, or ask-user decisions.

### S8 Executor Connector Loop

- Phase-aware executor task packets.
- Connector contracts and handoff markdown for local CLI or manual/external executors.
- Mock executor support and evidence ingestion.
- External executor results remain evidence until phase acceptance passes.
- CLI: `executor-task-create`, `executor-result-ingest`, `executor-review`.

### S9 Capability Fabric

- Deterministic, mock-first capability registry.
- Built-in capability IDs for filesystem, shell, git, web search, browser fetch, document/media understanding, database, GitHub ops, IDE handoff, and OpenClaw notification.
- Permission gate for missing, disabled, approval-required, shell, network, write, and external capabilities.
- Capability gap decision cards.
- Mock-only vision, audio, and document result contracts.
- No external tools, models, or packages are executed or installed by the capability fabric.

### S10 Generalization Evaluation And CI Gates

- Offline-only generalization evaluation suite.
- Fixture domains: docs, CLI, capability gap, recovery, project brain, and mock search/repo workflows.
- Local CI gate policy for text integrity, compileall, focused tests, generalization suite, and CLI help checks.
- No model, web, browser, media, OCR, database, GitHub, or external-agent execution in the suite.

### S11 Ops Console

- Local-only read-only operations console snapshot.
- Snapshot sections for project overview, project brain, roadmap, phases, task packets, skills, capabilities, recovery, evidence, budget, and resource ledgers.
- Dry-run server planning with public bind addresses rejected by policy.
- Secrets and private paths are redacted.
- CLI core remains usable without UI.

### S12 Productization And Service Factory

- Local-first service factory planning.
- A rough customer request can be matched to a service catalog entry.
- Deterministic quote estimate, timeline estimate, risk notes, and delivery package skeleton.
- Service types include repo cleanup, bug fix planning, longform blueprint, company research, document summary, spreadsheet cleanup, local file organization, audio analysis planning, multimodal review, and personal automation workflow.
- Generated delivery packages separate final summary, acceptance history, risks, reproduction commands, next steps, artifacts, and evidence.
- No external execution, network access, capability installation, or real service execution occurs automatically.

### Skills And Learning

- Skill lifecycle MVP: request, approve, stage, validate, promote, retire, match, inject, and usage tracking.
- Project Memory to Skill Draft distillation.
- Central local Skill Vault lifecycle.
- Trace-to-Skill learning review and candidate approval/rejection.
- External skill discovery remains manual, disabled by default, and approval-gated.

### Web UI And Status Surfaces

- Dependency-free static status board.
- Task details panel tied to runtime artifacts.
- Local-only dashboard direction through S11 ops console snapshots.
- CLI remains the primary reliable control surface.

### Testing And Integrity

- Integration tests for artifact gates and task closure.
- P1/P2/S7/S8/S9/S10/S11/S12 acceptance artifacts.
- Text integrity audit to catch compressed multiline files, broken markdown fences, private path leakage, and raw-file corruption.
- `doctor` command for Python, bash syntax, py_compile, config parsing, directory layout, UI files, artifact contract, and API key readiness checks.

## Important Commands

```bash
./agentlab.sh --help
./agentlab.sh doctor
./agentlab.sh policy-status --project AgentLab
./agentlab.sh models
./agentlab.sh run-pipeline --help
./agentlab.sh project-next --project AgentLab
./agentlab.sh capability-list
./agentlab.sh eval-generalization --out acceptance_runs/s10_generalization_eval
./agentlab.sh ops-console-status --project AgentLab --out acceptance_runs/s11_dashboard
./agentlab.sh service-factory-plan --prompt "Plan a local file organization assistant" --out /tmp/agentlab_service_demo
```

## Future Update Plan

### M0 Preflight / Baseline Lock

- Produce a current-state report with branch, commit, remote, CI, test, compileall, text integrity, tags, and dirty files.
- Create `docs/M_SERIES_SCOPE.md`.
- Freeze scope: M1 is governance, M2 is operator control, M3 is business/asset/revenue loops.
- Run compileall, pytest, CLI help, run-pipeline help, and text integrity audit.

### M1 Project Governance Kernel

Goal: make AgentLab reliably manage long-running projects and coordinate local CLI or handoff executors.

Planned work:

- M1-1 External Project Registry + Capability Mapping.
- M1-2 Mission Compiler v2.
- M1-3 Project Workflow Templates v2.
- M1-4 Project Brain v1 consolidation.
- M1-5 Executor Connector Loop v1 consolidation.
- M1-6 Document / Code / Media Ingestion v1 contracts.
- M1-7 Phase Acceptance v1 consolidation.
- M1-8 Recovery / Replanning v2.
- M1-9 Context Compression v1.
- M1-10 Generalization Demo Suite.

M1 acceptance:

- Rough project prompts compile into mission contracts.
- Project workflows are generated.
- Project brain persists.
- Task packets can be sent to local CLI/handoff executors.
- Mock executor results can be ingested.
- Phase acceptance can choose accept, retry, redesign, split, rollback, or ask user.
- Context compression prevents long-project memory collapse.
- Document/code/media ingestion contracts exist.
- Four offline generalization demos pass.

### M2 Operator OS / Transparent Control Plane

Goal: make AgentLab easy to inspect, configure, pause, resume, approve, reject, and cost-control.

Planned work:

- Config Center.
- Cost System v2.
- Event Timeline / Observability.
- TUI.
- WebUI.
- AgentLab Assistant Modes.
- Skill / Capability / Executor Control Panel.
- Operator Acceptance Demo.

M2 acceptance:

- Configuration is transparent and layered.
- Cost estimates, tracking, alerts, attribution, and review are visible.
- Project events are recorded in a timeline.
- TUI and WebUI work without weakening CLI reliability.
- Assistant modes can explain roadmap, phase status, and next action.
- Skills, capabilities, and executors can be inspected and controlled.
- Operator demo passes.

### M3 Project-to-Revenue OS

Goal: connect project production to assets, delivery, channels, revenue, compliance, clients, and SOP learning.

Planned work:

- Business Contract.
- Asset Registry + Lineage.
- Production Pipeline Templates.
- Market / Channel Intelligence.
- Analytics + Revenue Ledger.
- Compliance / Risk Brain.
- CRM / Client Delivery Loop.
- SOP / Skill Factory 2.0.
- End-to-end Project-to-Revenue demo projects.

M3 acceptance:

- Business contracts exist.
- Assets and lineage are tracked.
- Production pipelines exist.
- Market/channel intelligence is structured and bounded by policy.
- Analytics and revenue ledger exist.
- Compliance and risk brain exists.
- CRM/client delivery loop exists.
- SOP/skill factory produces candidates.
- Three offline P2R demos pass.

### v1.0 Release Target

- M1, M2, and M3 pass.
- Full pytest passes.
- Compileall passes.
- Text integrity passes.
- README and docs explain AgentLab as a local-first AI Production OS / Project-to-Revenue OS.
- Install, quickstart, security model, architecture, and examples are documented.
- No private path leakage.
- No unsafe external execution is enabled by default.
- Demo projects can be reproduced by a new user.

## Safety Model

AgentLab should remain conservative by default:

- No automatic external tool execution.
- No automatic skill installation.
- No automatic MCP server launch.
- No automatic web crawling.
- No automatic platform posting or upload.
- No automatic dependency installation.
- No public bind by default.
- No credentials in project memory, artifacts, or handoffs.
- No accepting external results without evidence and explicit review.

## Source Documents

- Main README: [`../README.md`](../README.md)
- Mainline status: [`MAINLINE_BASELINE_STATUS.md`](MAINLINE_BASELINE_STATUS.md)
- External agent handoff: [`EXTERNAL_AGENT_HANDOFF.md`](EXTERNAL_AGENT_HANDOFF.md)
- P2 acceptance/retry loop: [`P2_ACCEPTANCE_RETRY_LOOP.md`](P2_ACCEPTANCE_RETRY_LOOP.md)
- S7 orchestrator: [`S7_LONG_PROJECT_ORCHESTRATOR.md`](S7_LONG_PROJECT_ORCHESTRATOR.md)
- S8 executor connector: [`S8_EXECUTOR_CONNECTOR_LOOP.md`](S8_EXECUTOR_CONNECTOR_LOOP.md)
- S9 capability fabric: [`S9_CAPABILITY_FABRIC.md`](S9_CAPABILITY_FABRIC.md)
- S10 eval suite: [`S10_GENERALIZATION_EVAL_SUITE.md`](S10_GENERALIZATION_EVAL_SUITE.md)
- S11 ops console: [`S11_OPS_CONSOLE.md`](S11_OPS_CONSOLE.md)
- S12 productization: [`S12_PRODUCTIZATION.md`](S12_PRODUCTIZATION.md)
