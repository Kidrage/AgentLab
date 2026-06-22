# AgentLab M-Series Mainline Handoff

> Suggested target path: `docs/AGENTLAB_M_SERIES_MAINLINE_HANDOFF.md`
> Series: `M1 Project Governance Kernel` → `M2 Operator OS / Transparent Control Plane` → `M3 Project-to-Revenue OS`
> Goal: evolve AgentLab from a local-first AgentOps/project governance kernel into a transparent operator-controlled AI Production OS and finally into a Project-to-Revenue OS.

---

## 0. Executive Summary

AgentLab should not be positioned as a weaker replacement for Claude Code, Codex, Hermes, Cline, OpenClaw, or any other frontend/executor agent.

AgentLab should become the local-first backend operating system for long-running projects:

```text
rough user requirement
→ mission contract
→ domain/project workflow
→ project roadmap
→ task packets
→ external/local executor coordination
→ artifact ingestion
→ evidence review
→ phase acceptance
→ recovery/replanning
→ project memory update
→ asset registration
→ production pipeline
→ delivery package
→ revenue/analytics feedback
→ SOP / skill learning
```

The M-series mainline repairs are divided into three large upgrades:

```text
M1 — Project Governance Kernel
Make AgentLab reliably manage long-running projects and cooperate with local CLI agents without losing state, evidence, scope, or control.

M2 — Operator OS / Transparent Control Plane
Make AgentLab easy to operate, inspect, configure, pause, resume, approve, reject, and cost-control through CLI/TUI/WebUI/assistant modes.

M3 — Project-to-Revenue OS
Make AgentLab understand why a project is being produced, what assets are being created, how those assets may generate value, and how to track production, channels, revenue, compliance, CRM, and SOP learning.
```

The intended version milestones:

```text
v0.7 Project Kernel
  M1 completed. AgentLab can run long-governance projects and coordinate local CLI agents.

v0.8 Operator OS / Local Agent Company Control Plane
  M2 completed. AgentLab is transparent, configurable, observable, cost-controlled, and able to discover, evaluate, assign, and govern local agent/tool workers.

v0.9 Project-to-Revenue OS
  M3 completed. AgentLab can assetize projects and manage business-oriented production/revenue loops.

v1.0 Local-first AI Production OS
  M1/M2/M3 stabilized, documented, demo-ready, and suitable for public release.
```

---

## 1. Strategic Positioning

### 1.1 What AgentLab Is

AgentLab is:

```text
A local-first AI Production OS / Project-to-Revenue OS.

It coordinates projects, memory, tasks, executors, skills, capabilities,
evidence, costs, approvals, artifacts, recovery, acceptance, delivery,
and eventually business/asset/revenue loops.
```

AgentLab is the backend truth source.

### 1.2 What AgentLab Is Not

AgentLab is not:

```text
- A direct Claude Code replacement.
- A direct Codex replacement.
- A direct Hermes replacement.
- A direct OpenClaw replacement.
- A frontend-only chat agent.
- A random collection of plugins.
- A self-running unsafe autonomous agent.
- A crawler that ignores source, platform, or compliance boundaries.
- A platform automation bot for spam, fake engagement, policy evasion, or bulk abuse.
```

### 1.3 Role Relationship

```text
AgentLab
  = project operating system / backend truth source / governance kernel.

Claude Code / Codex / Hermes / Cline / DeepSeek Coder
  = high-skill executors.

OpenClaw / WebUI / TUI / CLI
  = user-facing control surfaces.

MCP
  = tool/capability bus.

Skills
  = SOPs, expert playbooks, reusable methods, and approved capability packages.

External open-source projects
  = capability providers or reference implementations, never uncontrolled dependencies.
```

---

## 2. Global Engineering Discipline

These rules apply to every M-series stage.

### 2.1 Repository Discipline

Before every repair round:

```bash
git status --short
git branch --show-current
git log --oneline -5
```

Create a rollback point:

```bash
git tag m-series-pre-<stage>-backup
```

If tag exists:

```bash
git branch backup/m-series-pre-<stage>
```

Never commit:

```text
.venv/
__pycache__/
node_modules/
local caches
private memory
temporary run artifacts
user-specific absolute paths
secrets
API keys
credentials
large generated binaries
```

### 2.2 Text Integrity

Do not repeat the historical multiline/raw integrity failure. Every stage must preserve real multiline files.

Required checks:

```bash
python -m compileall agent_runtime agentlab_app.py
python -m pytest -q
./agentlab.sh --help
./agentlab.sh run-pipeline --help
python scripts/audit_text_integrity.py
```

If remote raw checks exist:

```bash
python scripts/check_remote_raw_integrity.py --ref HEAD
```

Guard against:

```text
- Python files compressed into one line.
- YAML files compressed into one line.
- Markdown files with broken code fences.
- `from __future__ import annotations` not placed correctly.
- literal private absolute paths.
- secrets/tokens.
- broken GitHub Actions YAML.
- tests that pass locally but are unreadable on GitHub raw.
```

### 2.3 Security and Safety

Default stance:

```text
- No automatic external tool execution.
- No automatic skill installation.
- No automatic MCP server launch.
- No automatic web crawling.
- No automatic platform posting/uploading.
- No automatic dependency installation.
- No automatic shell execution outside approved scopes.
- No private IP / localhost / file URL fetches unless explicitly approved.
- No bypassing paywalls, login walls, platform terms, or rate limits.
```

Every capability that can touch outside data, local files, shell, network, or user accounts must pass:

```text
permission declaration
→ risk scan
→ approval gate
→ scoped execution
→ evidence logging
→ result verification
```

### 2.4 Testing Requirements

Every M stage must add:

```text
- deterministic unit tests
- fixture-based tests
- CLI smoke tests
- text integrity tests for new key files
- acceptance report under acceptance_runs/<stage>/
```

Network, vision, audio, browser, external executor, and platform tests must be mock-first unless a stage explicitly adds a real adapter behind approval gates.

### 2.5 Acceptance Report Format

Every stage must output:

```markdown
# AgentLab <M-Stage> Report

## Verdict
PASS / FAIL

## Baseline
- branch:
- before commit:
- after commit:
- remote:
- CI:

## Summary
What changed and why.

## Changed Files
- path: reason

## New Runtime Modules
- module: purpose

## New Configs
- config: purpose

## New CLI
- command: usage

## Artifacts Produced
- artifact: purpose

## Tests Added
- test file: coverage

## Tests Run
Paste command results.

## Safety Notes
Confirm no unauthorized external execution, no secret exposure, no path leakage.

## Known Limitations
What remains for later stages.

## Next Recommended Stage
What should happen next.
```

---

# 3. M-Series Dependency Graph

```text
M0 Preflight / Baseline Lock
↓
M1 Project Governance Kernel
  M1-1 External Project Registry + Capability Mapping
  M1-2 Mission Compiler v2
  M1-3 Project Workflow Templates v2
  M1-4 Project Brain v1
  M1-5 Executor Connector Loop v1
  M1-6 Document / Code / Media Ingestion v1
  M1-7 Phase Acceptance v1
  M1-8 Recovery / Replanning v2
  M1-9 Context Compression v1
  M1-10 Generalization Demo Suite
↓
M2 Operator OS / Local Agent Company Control Plane
  M2-0 Runtime Hygiene & Safety Baseline
  M2-1 Local Worker Registry / Agent Doctor
  M2-1.5 CLI Invocation Contract Validator
  M2-1.6 Cache-Aware Execution Economy Engine
  M2-1.7 Skill / MCP Capability Broker
  M2-2 Capability Schema & 9-Role Requirement Matrix
  M2-3 Worker Audition / Performance Ledger
  M2-4 Role Activation + Assignment Router v2
  M2-5 Config Center v2
  M2-6 Cost, Risk & Approval System v2
  M2-7 Observability / Event Timeline v2
  M2-8 Control Panel: Workers / Skills / MCPs / Capabilities / Executors
  M2-9 AgentLab Assistant Modes
  M2-10 TUI
  M2-11 WebUI
  M2-12 Operator Acceptance Demo
↓
M3 Project-to-Revenue OS
  M3-1 Business Contract
  M3-2 Asset Registry + Lineage
  M3-3 Production Pipeline Templates
  M3-4 Market / Channel Intelligence
  M3-5 Analytics + Revenue Ledger
  M3-6 Compliance / Risk Brain
  M3-7 CRM / Client Delivery Loop
  M3-8 SOP / Skill Factory 2.0
  M3-9 End-to-End P2R Demo Projects
```

---

# 4. M0 — Preflight / Baseline Lock

## 4.1 Objective

Before entering M1, lock the current repository state and prove the baseline is usable.

M0 does not add product features. It creates a safe base for M-series development.

## 4.2 Tasks

### M0-A: Current State Report

Create:

```text
acceptance_runs/m0_preflight/M0_PREFLIGHT_REPORT.md
```

Include:

```text
- current branch
- current commit
- remote status
- CI status if available
- pytest status
- compileall status
- text integrity status
- existing M/S/P stage tags if any
- dirty files, if any
```

### M0-B: Mainline Scope Freeze

Create:

```text
docs/M_SERIES_SCOPE.md
```

Define:

```text
M1 = project governance, not business automation.
M2 = operator control, not commercial growth.
M3 = business/asset/revenue loop, not unsafe platform automation.
```

### M0-C: Acceptance Gate Baseline

Run:

```bash
python -m compileall agent_runtime agentlab_app.py
python -m pytest -q
./agentlab.sh --help
./agentlab.sh run-pipeline --help
python scripts/audit_text_integrity.py
```

## 4.3 Acceptance

M0 passes only if:

```text
- compileall passes
- tests pass or known failing tests are documented
- text integrity has no unknown critical issue
- no private path leakage
- no uncommitted unrelated file is touched
- M-series scope document exists
```

---

# 5. M1 — Project Governance Kernel

## 5.1 M1 Objective

M1 makes AgentLab reliably manage long-running projects and cooperate with local CLI agents.

M1 should prove AgentLab can handle:

```text
- video generation project planning
- text generation / longform content projects
- codebase construction / repair projects
- research paper or repository archive projects
- multi-stage mixed projects
```

M1 is not about UI polish or business monetization. It is about long-project governance.

## 5.2 M1 Non-Goals

Do not implement in M1:

```text
- full business/revenue model
- CRM
- real platform posting
- real social media crawling
- heavy WebUI
- full TUI
- automatic external skill installation
- BabyAGI-style self-executing tool creation
- uncontrolled browser automation
- payment or invoicing integration
- real autonomous video generation calls
```

M1 may produce handoff packets, adapter contracts, mock results, and safe ingestion workflows.

---

## 5.3 M1-1 — External Project Registry + Capability Mapping

### Goal

Register useful open-source projects as capability providers or reference implementations without blindly absorbing or executing them.

Initial projects:

```text
MinerU
MarkItDown
Codebase-Memory-MCP
Graphify
Supervision
mattpocock/skills
Ponytail
Agent-Reach
BabyAGI
AiToEarn
```

### Add Runtime Modules

```text
agent_runtime/external_projects/
  __init__.py
  registry.py
  models.py
  loader.py
  risk_profile.py
  capability_mapper.py
  adapter_contract.py
  renderer.py
```

### Add Configs

```text
config/external_project_registry.yml
config/external_project_risk_policy.yml
config/external_project_capability_map.yml
```

### Registry Schema

```yaml
external_projects:
  - project_id: mineru
    display_name: MinerU
    source_url: https://github.com/opendatalab/MinerU
    role: capability_provider
    default_enabled: false
    integration_stage: registry_only
    capabilities:
      - complex_document_ingestion
      - pdf_ocr
      - table_extraction
      - formula_extraction
    risk:
      level: medium
      reasons:
        - external_dependency
        - parser_quality_varies
        - heavy_runtime_optional
      requires_approval: true
    permissions:
      filesystem_read: scoped
      filesystem_write: artifacts_only
      network: false
      shell: false
    adapter_contract:
      expected_inputs:
        - document_path
      expected_outputs:
        - document_asset.yml
        - extracted_markdown.md
        - extraction_quality_report.yml
    notes:
      - Do not vendor source.
      - Do not execute until adapter is explicitly approved.
```

### Required Capability Mapping

```text
MinerU
  → complex_document_ingestion
  → pdf_ocr
  → table_extraction
  → formula_extraction

MarkItDown
  → lightweight_document_to_markdown
  → office_to_markdown
  → pdf_text_extraction
  → media_metadata_extraction

Codebase-Memory-MCP
  → codebase_structural_memory
  → symbol_lookup
  → call_graph_query
  → impact_analysis

Graphify
  → project_knowledge_graph
  → multi_artifact_graph
  → repo_doc_media_relationships

Supervision
  → vision_evidence_normalization
  → detection_annotation
  → dataset_visualization

mattpocock/skills
  → skill_package_reference
  → engineering_sop_reference
  → handoff_skill_reference

Ponytail
  → minimal_patch_reviewer
  → dependency_skeptic
  → anti_overengineering_gate

Agent-Reach
  → web_social_intelligence_provider
  → market_channel_research
  → disabled_by_default_high_risk

BabyAGI
  → self_evolving_skill_research_reference
  → trace_to_skill_inspiration
  → no_auto_exec

AiToEarn
  → p2r_reference
  → content_production_pipeline_reference
  → channel_operation_reference
```

### CLI

```bash
./agentlab.sh external-projects list
./agentlab.sh external-projects inspect --project mineru
./agentlab.sh external-projects capability-map --capability complex_document_ingestion
./agentlab.sh external-projects risk-report --out acceptance_runs/m1_external_projects
```

### Tests

```text
tests/test_m1_external_project_registry.py
tests/test_m1_external_project_capability_map.py
tests/test_m1_external_project_risk_policy.py
tests/test_m1_external_project_cli.py
```

Minimum tests:

```text
- registry loads deterministically
- project_id is unique
- all required projects are present
- all projects default_enabled=false unless explicitly safe
- high-risk providers require approval
- Agent-Reach and BabyAGI cannot be active by default
- capability lookup returns matching providers
- CLI list/inspect works
- no external project code is executed
```

### Acceptance

M1-1 passes if:

```text
- external project registry exists
- capabilities are mapped
- risk profile exists
- adapter contracts are defined
- no external project is executed
- all risky providers are disabled by default
```

---

## 5.4 M1-2 — Mission Compiler v2

### Goal

Upgrade mission compilation from task-level intent classification into project-level demand compilation.

The compiler must detect:

```text
- task domain
- long-project scale
- project type
- required artifacts
- required capabilities
- external executor need
- document/code/media ingestion needs
- phase acceptance need
- asset registry relevance
- human approval points
- risk flags
```

### Add / Extend Modules

```text
agent_runtime/brain/
  mission_contract.py
  task_compiler.py
  domain_classifier.py
  project_type_classifier.py
  capability_requirement_builder.py
  artifact_contract_builder.py
  acceptance_gate_builder.py
  risk_classifier.py
  decision_card_builder.py
  renderer.py
```

### Add Configs

```text
config/mission_compiler_v2.yml
config/project_type_classifier.yml
config/project_artifact_contracts.yml
config/project_acceptance_gates.yml
```

### Mission Contract v2 Schema

```yaml
mission_contract:
  task_id: null
  project_id: null
  user_goal: ""
  intent_summary: ""
  task_type: coding | research | creative_longform | video_generation | document_processing | audio_music | multimodal | business | local_ops | unknown
  project_type: codebase_build_project | longform_text_project | video_generation_project | research_archive_project | document_knowledgebase_project | multimodal_content_project | local_automation_project | unknown
  is_long_project: true
  estimated_scale: small | medium | large | unknown
  non_goals: []
  hard_constraints: []
  soft_preferences: []
  unknowns: []
  assumptions: []
  required_capabilities: []
  required_artifacts: []
  acceptance_gates: []
  risk_flags: []
  external_executor_needed: false
  asset_registry_recommended: true
  human_approval_required: true
  decision_cards: []
```

### CLI

```bash
./agentlab.sh compile-mission-v2 --prompt-file examples/prompts/video_project.txt --out /tmp/m1_mission
```

Outputs:

```text
mission_contract.yml
intent_summary.md
required_capabilities.yml
artifact_contracts.yml
acceptance_gates.yml
risk_flags.yml
decision_cards/
```

### Tests

```text
tests/test_m1_mission_compiler_v2.py
tests/test_m1_project_type_classifier.py
tests/test_m1_capability_requirement_builder.py
tests/test_m1_artifact_acceptance_builder.py
```

Minimum fixtures:

```text
examples/prompts/codebase_build_project.txt
examples/prompts/longform_text_project.txt
examples/prompts/video_generation_project.txt
examples/prompts/research_archive_project.txt
examples/prompts/document_knowledgebase_project.txt
examples/prompts/local_automation_project.txt
```

### Acceptance

M1-2 passes if:

```text
- rough project prompts produce mission_contract.yml
- long-running prompts are classified as long project
- video/text/code/research/archive projects are recognized
- capabilities and artifacts are produced
- human approval points are present where needed
- no task execution occurs
```

---

## 5.5 M1-3 — Project Workflow Templates v2

### Goal

Convert mission contracts into project-specific workflow plans.

M1-3 upgrades domain workflows into long-project workflows.

### Add Modules

```text
agent_runtime/project_workflows/
  __init__.py
  models.py
  loader.py
  matcher.py
  planner.py
  renderer.py
```

### Add Configs

```text
config/project_workflow_templates.yml
config/project_phase_artifact_templates.yml
config/project_phase_acceptance_templates.yml
```

### Required Project Workflow Templates

```text
codebase_build_project
longform_text_project
video_generation_project
research_archive_project
document_knowledgebase_project
multimodal_content_project
local_automation_project
unknown_project
```

### Workflow Plan Schema

```yaml
workflow_plan:
  project_id:
  template_id:
  project_type:
  mission_contract_path:
  phases:
    - phase_id:
      title:
      goal:
      required_inputs:
      expected_outputs:
      expected_artifacts:
      required_capabilities:
      recommended_skills:
      recommended_executors:
      acceptance_gates:
      human_decision_points:
      failure_recovery:
      asset_registry_updates:
      next_phase_conditions:
  warnings: []
  decision_points: []
```

### Required Phase Examples

#### codebase_build_project

```text
compile_mission
→ inspect_repo_or_create_blueprint
→ define_architecture
→ create_task_packets
→ executor_patch_loop
→ run_tests
→ phase_acceptance
→ documentation_and_delivery
```

#### longform_text_project

```text
compile_mission
→ define_audience_style_constraints
→ create_content_constitution
→ create_world_or_topic_bible
→ build_outline
→ create_section_or_scene_cards
→ draft_batch
→ continuity_review
→ revision_loop
→ final_package
```

#### video_generation_project

```text
compile_mission
→ define_platform_audience_style
→ research_or_source_plan
→ script_generation
→ storyboard_or_shot_plan
→ asset_plan
→ video_tool_handoff
→ qa_review
→ revision_notes
→ delivery_package
```

#### research_archive_project

```text
compile_mission
→ define_research_scope
→ ingest_sources
→ extract_metadata
→ build_fact_table
→ summarize_by_topic
→ create_archive_index
→ evidence_quality_review
→ final_report
```

### CLI

```bash
./agentlab.sh project-workflow-plan --mission-contract /tmp/m1_mission/mission_contract.yml --out /tmp/m1_workflow
```

Outputs:

```text
project_workflow_plan.yml
project_workflow_plan.md
```

### Tests

```text
tests/test_m1_project_workflow_templates.py
tests/test_m1_project_workflow_planner.py
tests/test_m1_project_workflow_cli.py
```

### Acceptance

M1-3 passes if:

```text
- every required project template loads
- every template has at least 5 phases
- video project workflow includes script/storyboard/asset/QA phases
- longform text workflow includes bible/outline/cards/continuity phases
- research archive workflow includes source ingestion/fact table/archive index
- codebase workflow includes task packet/executor/test/acceptance phases
- unknown project does not execute and asks clarification
```

---

## 5.6 M1-4 — Project Brain v1

### Goal

Create durable project-level memory.

Task runs are not enough. Long projects need a stable brain.

### Add Modules

```text
agent_runtime/program_manager/
  __init__.py
  project_brief.py
  project_brain.py
  roadmap.py
  milestone_graph.py
  phase_plan.py
  decision_log.py
  risk_register.py
  status.py
  renderer.py
```

### Project Directory Layout

```text
projects/<project_id>/
  project_brain/
    project_brief.yml
    product_vision.md
    roadmap.yml
    milestone_graph.yml
    current_phase.yml
    phase_plan.yml
    decision_log.yml
    acceptance_history.yml
    unresolved_questions.yml
    known_risks.yml
    architecture_state.yml
    next_actions.yml
    context_snapshots/
    phase_summaries/
  artifacts/
  evidence/
  task_packets/
  executor_results/
  acceptance/
```

### CLI

```bash
./agentlab.sh project-init --mission-contract /tmp/m1_mission/mission_contract.yml --workflow-plan /tmp/m1_workflow/project_workflow_plan.yml --project DemoProject
./agentlab.sh project-status --project DemoProject
./agentlab.sh project-next --project DemoProject
```

### Tests

```text
tests/test_m1_project_brain.py
tests/test_m1_project_init_cli.py
tests/test_m1_project_status.py
```

### Acceptance

M1-4 passes if:

```text
- project-init creates project_brain directory
- roadmap and milestone_graph exist
- project-status summarizes current state
- project-next produces next recommended action
- project memory persists across reloads
- no raw full history is required to reconstruct current status
```

---

## 5.7 M1-5 — Executor Connector Loop v1

### Goal

Standardize collaboration with local CLI agents and external executors.

M1 should not fully automate every CLI. It must produce safe task packets, ingest results, and route them through acceptance.

### Add Modules

```text
agent_runtime/executors/
  __init__.py
  connector_contract.py
  task_packet.py
  handoff_renderer.py
  result_ingestion.py
  diff_inspector.py
  evidence_collector.py
  executor_ledger.py
  generic_cli_connector.py
  manual_patch_submitter.py
```

### Add Configs

```text
config/executor_connectors.yml
config/executor_permission_policy.yml
config/executor_handoff_templates.yml
```

### Task Packet Schema

```yaml
task_packet:
  packet_id:
  project_id:
  phase_id:
  executor_type: local_cli_generic | claude_code_handoff | hermes_handoff | codex_handoff | manual_patch_submitter
  objective:
  context_summary:
  allowed_files: []
  forbidden_files: []
  required_outputs: []
  acceptance_criteria: []
  commands_allowed: []
  commands_forbidden: []
  evidence_required: []
  rollback_required: true
  cost_policy:
  safety_notes: []
```

### Executor Result Schema

```yaml
executor_result:
  packet_id:
  executor_type:
  summary:
  changed_files: []
  artifacts: []
  commands_run: []
  tests_run: []
  test_results:
  risks: []
  unresolved_issues: []
  evidence_paths: []
  proposed_next_action:
```

### CLI

```bash
./agentlab.sh executor-task-create --project DemoProject --phase phase_001 --executor claude_code_handoff --out /tmp/task_packet
./agentlab.sh executor-result-ingest --project DemoProject --result-dir /tmp/executor_result
./agentlab.sh executor-review --project DemoProject --phase phase_001
```

### Tests

```text
tests/test_m1_executor_task_packet.py
tests/test_m1_executor_result_ingestion.py
tests/test_m1_executor_review.py
tests/test_m1_executor_policy.py
```

### Acceptance

M1-5 passes if:

```text
- task packet can be generated
- executor-specific handoff markdown can be generated
- mock executor result can be ingested
- changed files and artifacts are recorded
- result ingestion does not auto-close phase
- phase acceptance is invoked
- unauthorized executor cannot run
- no real external CLI call is required
```

---

## 5.8 M1-6 — Document / Code / Media Ingestion v1

### Goal

Give AgentLab safe ingestion contracts for project inputs.

M1 focuses on registry and fallback/mock adapters, not heavy external execution.

### Add Modules

```text
agent_runtime/ingestion/
  document_ingestion.py
  code_ingestion.py
  media_ingestion.py
  ingestion_contract.py
  ingestion_result.py
  quality_report.py
```

### Add Configs

```text
config/ingestion_providers.yml
config/document_ingestion_policy.yml
config/media_ingestion_policy.yml
```

### Providers

```text
MarkItDown
  - lightweight fallback
  - default disabled or mock unless installed
  - output: extracted_markdown.md, document_asset.yml

MinerU
  - complex PDF/OCR/table/formula contract
  - no automatic heavy execution
  - output: document_asset.yml, extraction_quality_report.yml

Codebase-Memory-MCP
  - code structural memory contract
  - no auto MCP launch
  - output: code_graph_asset.yml

Graphify
  - project knowledge graph contract
  - no auto hook/install
  - output: project_graph_asset.yml

Supervision
  - vision evidence normalization contract
  - no model execution by default
  - output: vision_evidence.yml
```

### Ingestion Result Schema

```yaml
ingestion_result:
  artifact_id:
  source_path:
  source_type:
  provider:
  status:
  output_assets: []
  evidence_paths: []
  quality:
    confidence:
    warnings: []
    requires_human_review:
  provenance:
    created_at:
    content_hash:
```

### CLI

```bash
./agentlab.sh ingest-artifact --project DemoProject --path examples/docs/sample.pdf --provider markitdown_mock
./agentlab.sh ingest-repo-memory --project DemoProject --repo . --provider codebase_memory_mock
```

### Tests

```text
tests/test_m1_ingestion_contracts.py
tests/test_m1_document_ingestion_mock.py
tests/test_m1_code_ingestion_mock.py
tests/test_m1_media_ingestion_mock.py
```

### Acceptance

M1-6 passes if:

```text
- document/code/media ingestion contracts exist
- mock/fallback providers produce deterministic outputs
- ingestion outputs enter evidence ledger
- quality report exists
- heavy external projects are not executed without approval
```

---

## 5.9 M1-7 — Phase Acceptance v1

### Goal

Make phase-level acceptance the core governance checkpoint.

### Add Modules

```text
agent_runtime/program_manager/
  phase_acceptance.py
  acceptance_contract.py
  acceptance_renderer.py
  scope_checker.py
  evidence_checker.py
  next_action_decider.py
```

### Phase Acceptance Schema

```yaml
phase_acceptance:
  project_id:
  phase_id:
  verdict: accept | retry | redesign | split | rollback | ask_user | blocked
  phase_goal:
  expected_scope:
  actual_scope:
  changed_files: []
  artifacts: []
  evidence: []
  tests_run: []
  test_results:
  quality_findings: []
  risks_introduced: []
  unresolved_issues: []
  scope_drift:
  cost_summary:
  recommended_next_action:
  rationale:
```

### CLI

```bash
./agentlab.sh phase-accept --project DemoProject --phase phase_001 --result-dir /tmp/executor_result --out /tmp/phase_acceptance
```

### Tests

```text
tests/test_m1_phase_acceptance.py
tests/test_m1_phase_scope_checker.py
tests/test_m1_phase_next_action.py
```

### Acceptance

M1-7 passes if:

```text
- phase acceptance produces YAML and Markdown
- missing evidence fails or asks user
- scope drift is detected
- unresolved test failure causes retry/redesign/block
- accepted phase updates project_brain acceptance_history
- rejected phase produces recovery/replanning input
```

---

## 5.10 M1-8 — Recovery / Replanning v2

### Goal

Upgrade recovery from task-level retry into project-phase replanning.

### Add Modules

```text
agent_runtime/recovery/
  phase_recovery.py
  replanning.py
  alternative_route_planner.py
  capability_gap_resolver.py
  escalation_policy.py
  fake_evidence_detector.py
```

### Failure Taxonomy

```text
tool_unavailable
network_blocked
provider_failed
skill_missing
skill_failed
artifact_failed_validation
quality_failed
agent_hallucinated
evidence_missing
permission_missing
context_insufficient
budget_exceeded
capability_gap
executor_result_incomplete
scope_drift
phase_goal_mismatch
```

### Next Actions

```text
retry_same
retry_with_stronger_model
decompose_smaller
search_skill
install_capability
switch_executor
fallback_manual_template
ask_user
stop_safely
redesign_phase
split_phase
rollback_phase
```

### CLI

```bash
./agentlab.sh phase-replan --project DemoProject --phase phase_001 --acceptance /tmp/phase_acceptance/phase_acceptance.yml --out /tmp/replan
```

### Tests

```text
tests/test_m1_phase_recovery.py
tests/test_m1_replanning.py
tests/test_m1_fake_evidence_detector.py
```

### Acceptance

M1-8 passes if:

```text
- failed phase produces replanning plan
- evidence_missing cannot pass
- capability_gap creates decision card
- budget_exceeded produces cheaper route or stop
- repeated retry is capped
- replanning updates project next_actions
```

---

## 5.11 M1-9 — Context Compression v1

### Goal

Keep long-running project context stable and compact.

### Add Modules

```text
agent_runtime/program_manager/
  context_compressor.py
  snapshot.py
  phase_summary.py
  architecture_snapshot.py
  memory_compaction.py
```

### Outputs

```text
projects/<project_id>/project_brain/
  phase_summaries/
    phase_001_summary.md
  context_snapshots/
    snapshot_001.yml
  architecture_state.yml
  decision_log.yml
```

### Rules

```text
- Do not pass all raw history to every model call.
- Summarize every accepted/rejected phase.
- Snapshot every N phases.
- Keep unresolved questions and risks separate.
- Keep architecture state separate from chat transcript.
- Keep decision log append-only.
```

### CLI

```bash
./agentlab.sh project-summarize-phase --project DemoProject --phase phase_001
./agentlab.sh project-snapshot --project DemoProject
```

### Tests

```text
tests/test_m1_context_compression.py
tests/test_m1_project_snapshot.py
```

### Acceptance

M1-9 passes if:

```text
- phase summary is generated
- snapshot is generated
- project-next can use summary/snapshot without raw history
- unresolved questions and risks persist
- no private transcript dump is required
```

---

## 5.12 M1-10 — Generalization Demo Suite

### Goal

Prove M1 can handle multiple project types.

### Demo Projects

```text
demo_codebase_build
demo_longform_text
demo_research_archive
demo_video_generation
```

### Add

```text
examples/m1_demo_projects/
  codebase_build/
  longform_text/
  research_archive/
  video_generation/

acceptance_runs/m1_generalization_demo/
  M1_GENERALIZATION_DEMO_REPORT.md
```

### CLI

```bash
./agentlab.sh m1-demo --suite all --out acceptance_runs/m1_generalization_demo
```

### Minimum Demo Expectations

#### Codebase Build / Repair

```text
rough prompt
→ mission_contract
→ project workflow
→ project brain
→ task packet
→ mock executor result
→ phase acceptance
```

#### Longform Text

```text
rough prompt
→ constitution
→ bible
→ outline
→ scene/section cards
→ continuity ledger
→ phase summary
```

#### Research Archive

```text
research/archive prompt
→ ingestion plan
→ mock source extraction
→ fact table
→ archive index
→ evidence quality report
```

#### Video Generation

```text
video project prompt
→ platform/audience/style
→ script
→ storyboard
→ asset plan
→ video tool handoff skeleton
→ QA report
```

### Acceptance

M1 fully passes if:

```text
- all four demos run offline
- every demo creates mission/workflow/project brain
- every demo creates phase acceptance
- project-next works after phase acceptance
- no real external execution occurs
- no business/revenue layer is required
```

---

# 6. M2 — Operator OS / Local Agent Company Control Plane

## 6.1 M2 Objective

M2 makes AgentLab transparent, controllable, cost-aware, and able to manage the user’s local agent/tool ecosystem as an “agent company.”

M2 is no longer only a dashboard/control-plane upgrade. It must also solve the central product problem:

```text
Most users already have multiple local agent CLIs and tools:
Claude Code, Codex, Hermes, OpenClaw, Aider, Bailian CLI, Qwen CLI,
Gemini CLI, rg, git, ast-grep, pytest, ruff, eslint, docker, etc.

AgentLab should discover these workers, evaluate their capabilities,
assign them to the 9 AgentLab roles, route tasks safely, track cost,
record evidence, and let the operator inspect/override decisions.
```

The user should be able to see:

```text
what AgentLab is doing
why it is doing it
which role is responsible
which local CLI/tool/worker is assigned
why that worker was selected
what capabilities were required
what permissions are involved
what the cost/risk is
what is blocked
what needs approval
what evidence exists
what changed
what happens next
```

M2 turns AgentLab into the local-first management layer for a multi-agent workstation.

The core product narrative is:

```text
Other tools provide individual agents.
AgentLab manages the local agent company.

Claude Code / Codex / Aider / Hermes / OpenClaw / Bailian CLI / deterministic tools
are not competitors to AgentLab. They are workers, front desks, specialist tools,
or capability providers managed by AgentLab.
```

M2 must also establish AgentLab's cache-aware execution economy:

```text
9 roles are governance responsibilities, not mandatory model calls.
Workers are lazily activated.
Stable role/skill/MCP startup context may be cache-discounted when cache confidence is measurable.
Deterministic tools and cached evidence are preferred before model/API/CLI/MCP calls when sufficient.
Every activation must explain effective marginal cost, cache assumption, expected benefit, risk reduction, permission risk, and fallback.
```

M2 must also establish AgentLab's capability brokerage:

```text
Do not force every local agent CLI to share the same skills/MCP servers.
Normalize heterogeneous skills/MCPs as capability provider passports.
AgentLab-owned skills and brokered MCPs are canonical.
Worker-local skills/MCPs are delegated opaque capabilities until verified.
```

---

## 6.2 M2 Non-Goals

Do not implement in M2:

```text
- real commercial revenue loop
- CRM
- payment
- platform posting
- unsafe automation
- real social scraping
- autonomous external tool installation
- uncontrolled shell execution
- automatic upload of user files to cloud providers
- automatic public network binding for WebUI/OpenClaw gateways
```

M2 may prepare hooks for M3 asset/revenue/business loops, but it must not make commercial automation core yet.

M2 may expose local frontdesk gateway status, such as OpenClaw or a WeChat gateway, but it must not turn those gateways into uncontrolled autonomous execution endpoints.

---

## 6.3 Revised M2 Dependency Graph

The old M2 order was:

```text
Config Center
→ Cost System
→ Timeline
→ TUI
→ WebUI
→ Assistant
→ Skill/Capability/Executor Control Panel
→ Operator Demo
```

The revised M2 order should be:

```text
M2-0 Runtime Hygiene & Safety Baseline
↓
M2-1 Local Worker Registry / Agent Doctor
↓
M2-1.5 CLI Invocation Contract Validator
↓
M2-1.6 Cache-Aware Execution Economy Engine
↓
M2-1.7 Skill / MCP Capability Broker
↓
M2-2 Capability Schema & 9-Role Requirement Matrix
↓
M2-3 Worker Audition / Performance Ledger
↓
M2-4 Role Activation + Assignment Router v2
↓
M2-5 Config Center v2
↓
M2-6 Cost, Risk & Approval System v2
↓
M2-7 Observability / Event Timeline v2
↓
M2-8 Control Panel: Workers / Skills / Capabilities / Executors
↓
M2-9 AgentLab Assistant Modes
↓
M2-10 TUI
↓
M2-11 WebUI
↓
M2-12 Operator Acceptance Demo
```

Reason for the reorder:

```text
Worker discovery and role assignment must come before UI.

Otherwise the TUI/WebUI can only show static configs, not the real product value:
“AgentLab knows which local agents/tools exist, what they are good at,
what they cost, what they are allowed to do, and which role they should fill.”
```

---

# 6.4 M2-0 — Runtime Hygiene & Safety Baseline

## Goal

Before adding worker management, fix and validate the local/remote runtime topology.

AgentLab must clearly separate:

```text
profiles = private runtime state/config/auth/cache/logs
workspaces = temporary execution/build/checkouts/task sandboxes
bridges = gateway/adapter/connector processes
logs = redacted operational logs
runtime = pid/socket/health/status files
```

This stage exists because local agent CLIs often create private directories such as:

```text
.claude
.codex
.qwen
.hermes
.gemini
.claude.json
```

These are usually runtime profile/state/config/auth directories, not task workspaces. AgentLab must not treat them as cleanable project workspaces.

## Required Layout

```text
AgentLab/
  .agents/
    profiles/
      claude/
      codex/
      qwen/
      hermes/
      gemini/
      bailian/
      openclaw/
    workspaces/
      claude/
      codex/
      qwen/
      hermes/
      openclaw/
      generic_cli/
    bridges/
      agy_bridge/
      openclaw_gateway/
      wechat_gateway/
    logs/
    runtime/
```

## Required Git Ignore Rules

Add or verify:

```gitignore
.agents/
.claude/
.codex/
.hermes/
.gemini/
.qwen/
.claude.json
*.db
*.sqlite
*.sqlite3
*.log
*.pid
*.sock
.env
.env.*
```

If `.qwen/` or `.env` already exists in `.gitignore`, keep it. The key requirement is that all new local agent state paths are explicitly protected.

## Add Modules

```text
agent_runtime/runtime_hygiene/
  __init__.py
  layout.py
  symlink_audit.py
  gitignore_audit.py
  secret_scan.py
  profile_workspace_classifier.py
  renderer.py
```

## Runtime Layout Report Schema

```yaml
runtime_layout:
  agentlab_root:
  profiles_dir:
  workspaces_dir:
  bridges_dir:
  logs_dir:
  runtime_dir:
  profile_entries:
    - name:
      path:
      exists:
      symlink:
      target:
      git_tracked:
      risk_flags: []
  workspace_entries:
    - name:
      path:
      exists:
      symlink:
      target:
      git_tracked:
      cleanable:
      risk_flags: []
  warnings: []
```

## CLI

```bash
./agentlab.sh runtime-doctor
./agentlab.sh runtime-layout
./agentlab.sh runtime-audit-symlinks
./agentlab.sh runtime-secret-scan
```

## Tests

```text
tests/test_m2_runtime_hygiene_layout.py
tests/test_m2_runtime_gitignore_audit.py
tests/test_m2_runtime_secret_scan.py
tests/test_m2_profile_workspace_classifier.py
```

## Acceptance

M2-0 passes if:

```text
- .agents/profiles and .agents/workspaces are semantically separated
- .agents/ is ignored by Git
- agent profile directories are never treated as cleanable task workspaces
- no token/state/log file is tracked
- symlink targets can be inspected
- local and remote layout can be represented symmetrically
- runtime-doctor produces a Markdown and YAML report
```

---

# 6.5 M2-1 — Local Worker Registry / Agent Doctor

## Goal

Discover local agent CLIs and deterministic tools installed on the user’s machine.

AgentLab must not assume the user has Claude, Codex, Aider, Hermes, OpenClaw, Bailian CLI, or any other tool. It must detect and record what is actually available.

## Worker Categories

```text
coding_agent
planning_agent
frontdesk_agent
multimodal_cloud_tool
research_tool
deterministic_repo_tool
deterministic_ast_tool
test_runner
linter
formatter
shell_tool
vcs_tool
container_tool
unknown
```

## Initial Worker Candidates

```text
claude
codex
aider
hermes
openclaw
agy
bl / bailian-cli
qwen
gemini
rg
git
git grep
ast-grep / sg
pytest
ruff
eslint
mypy
npm
pnpm
uv
docker
```

## Add Modules

```text
agent_runtime/workers/
  __init__.py
  worker_card.py
  registry.py
  detector.py
  command_probe.py
  auth_probe.py
  version_probe.py
  health_probe.py
  renderer.py
```

## Worker Card Schema

```yaml
worker:
  worker_id: claude_code
  display_name: Claude Code
  command: claude
  installed: true
  version: null
  authenticated: unknown
  category: coding_agent
  source: local_cli
  can_read_files: true
  can_edit_files: true
  can_run_shell: true
  can_access_network: unknown
  can_upload_files: unknown
  interactive: true
  supports_noninteractive_task: unknown
  supports_mcp: unknown
  supports_long_context: unknown
  cost_tier: high
  risk_level: high
  default_enabled: false
  approval_required: true
  best_for:
    - repo_level_coding
    - architecture_reasoning
    - large_refactor
  avoid_for:
    - deterministic_search
    - cheap_lint
    - secret_handling
  notes: []
```

## Detection Rules

Detection must be safe and best-effort:

```text
- command presence may use `which` / `command -v`
- version probe may call `--version` or equivalent only when safe
- auth probe must never print tokens
- health probe must not launch an interactive editing session
- unknown tools are represented as unknown, not failure
- worker-scan must work offline
```

## CLI

```bash
./agentlab.sh worker-scan
./agentlab.sh worker-list
./agentlab.sh worker-inspect --worker claude_code
./agentlab.sh worker-doctor
```

## Outputs

```text
.agentlab/cache/worker_registry.yml
acceptance_runs/m2_worker_registry/worker_scan_report.md
```

## Tests

```text
tests/test_m2_worker_registry.py
tests/test_m2_worker_detector.py
tests/test_m2_worker_card_schema.py
tests/test_m2_worker_cli.py
```

## Acceptance

M2-1 passes if:

```text
- worker-scan works even if no external agent CLI is installed
- missing tools are reported cleanly
- installed tools are detected by command presence
- version/auth probes are best-effort and never leak secrets
- worker cards are generated deterministically
- high-risk workers default to approval_required=true
- deterministic tools such as rg/git/pytest/ruff can be registered as workers
```
# 6.5.5 M2-1.5 — CLI Invocation Contract Validator

## Goal

Validate that every configured local agent CLI is not only installed, but also invoked through a real, supported, testable command contract.

This stage exists because command presence is not enough:

```text
CLI binary exists ≠ CLI invocation is valid
```

Example failure class:

```text
hermes binary exists
→ AgentLab selects Hermes as Supervisor
→ configured command uses fake template: hermes --task {task_packet_path}
→ Hermes exits with argparse usage failure / exit code 2
→ old AgentLab misclassifies the failure as blocked_user_decision
→ correct behavior should classify it as invalid_cli_invocation and fallback
```

M2-1.5 prevents stale, fake, hallucinated, or unsupported CLI templates from entering the worker routing pool.

---

## Required Principle

Every local agent CLI must be represented by an invocation contract, not only a raw command string.

Bad:

```yaml
cli_command: hermes --task {task_packet_path}
```

Good:

```yaml
worker_invocation_contract:
  worker_id: hermes
  command: hermes
  invocation_style: one_shot_prompt
  template: >
    hermes -z "You are an AgentLab CLI executor. Read the JSON task packet at {task_packet_path},
    perform the requested AgentLab role work, and return a concise markdown report
    with findings, actions taken, verification, and blockers."
  required_placeholders:
    - task_packet_path
  safe_probe:
    - hermes
    - --help
  expected_parse:
    argv_prefix:
      - hermes
      - -z
  invalid_invocation_patterns:
    - "usage:"
    - "unrecognized arguments"
  invalid_exit_codes:
    - 2
  fallback_on_invalid_invocation: direct_api
```

---

## Add Modules

```text
agent_runtime/workers/
  invocation_contract.py
  command_template_validator.py
  cli_error_classifier.py
  safe_probe_runner.py
  invocation_report.py
```

---

## Add Configs

```text
config/worker_invocation_contracts.yml
config/cli_error_classification.yml
```

---

## Invocation Contract Schema

```yaml
worker_invocation_contract:
  worker_id:
  display_name:
  command:
  invocation_style: one_shot_prompt | chat_query | task_file | stdin | custom | deterministic_tool
  template:
  required_placeholders: []
  optional_placeholders: []
  safe_probe: []
  expected_parse:
    argv_prefix: []
    must_contain: []
    must_not_contain: []
  validation:
    shlex_parse_required: true
    require_existing_binary: false
    allow_shell: false
    allow_unquoted_placeholders: false
  error_classification:
    invalid_exit_codes: []
    invalid_invocation_patterns: []
    auth_required_patterns: []
    rate_limit_patterns: []
    network_failure_patterns: []
    permission_denied_patterns: []
  fallback:
    on_binary_missing: alternate_worker_or_direct_api
    on_invalid_invocation: direct_api
    on_auth_required: blocked_user_setup
    on_network_required: offline_or_retry_later
    on_permission_denied: approval_required
```

---

## Required CLI Error Classes

```text
binary_missing
invalid_cli_invocation
auth_required
network_required
permission_denied
timeout
rate_limited
model_unavailable
provider_error
task_failed
unknown_failure
```

---

## Error Classification Rules

Minimum rules:

```text
exit code 2 + stderr contains "usage:" or "unrecognized arguments"
→ invalid_cli_invocation

binary missing / command not found
→ binary_missing

stderr contains auth/login/API key related failure
→ auth_required

stderr contains network/DNS/proxy/connection failure
→ network_required

stderr contains permission denied / sandbox denied
→ permission_denied

stderr contains rate limit / quota exceeded
→ rate_limited

timeout exceeded
→ timeout
```

The key rule:

```text
binary present but invalid arguments must never be treated as available worker.
```

---

## Initial Workers That Must Have Invocation Contracts

```text
hermes
claude
codex
aider
openclaw
agy
bl / bailian-cli
qwen
gemini
rg
git
ast-grep / sg
pytest
ruff
eslint
```

Priority order:

```text
P0 Hermes
  Already known to have had fake --task templates. Must be locked by regression tests.

P0 Claude / Codex / Aider
  High-risk coding workers. They can edit files and run shell commands, so invocation contracts must be validated.

P0 bl / Bailian CLI
  Cloud/multimodal/RAG/OSS-capable worker. Must be approval-gated before upload or paid generation.

P1 OpenClaw / agy
  Frontdesk/bridge/gateway workers. Must not be accidentally treated as unrestricted executors.

P1 qwen / gemini
  API/CLI fallback workers. Validate auth, model arguments, and failure classification.

P2 deterministic tools
  rg / git / ast-grep / pytest / ruff / eslint.
  Lower risk, but still require command presence, template parse, and output classification.
```

---

## CLI

```bash
./agentlab.sh worker-contracts
./agentlab.sh worker-contract-validate --worker hermes
./agentlab.sh worker-contract-validate --all
./agentlab.sh worker-invocation-probe --worker hermes --mock
./agentlab.sh worker-invocation-report --out acceptance_runs/m2_worker_invocation_contracts
```

---

## Outputs

```text
acceptance_runs/m2_worker_invocation_contracts/
  worker_invocation_contract_report.md
  worker_invocation_contract_report.yml
  invalid_templates.yml
  classified_cli_failures.yml
```

---

## Tests

```text
tests/test_m2_worker_invocation_contract.py
tests/test_m2_command_template_validator.py
tests/test_m2_cli_error_classifier.py
tests/test_m2_worker_invocation_probe.py
```

---

## Minimum Regression Tests

```text
- Hermes old fake template `hermes --task {task_packet_path}` is classified as invalid_cli_invocation.
- Hermes old fake template `hermes --task-packet {task_packet_path}` is classified as invalid_cli_invocation.
- Valid Hermes one-shot template parses as: ['hermes', '-z', <prompt containing task_packet_path>].
- invalid_cli_invocation returns CliAgentNotAvailable(reason="invalid_cli_invocation").
- invalid_cli_invocation triggers direct API or alternate worker fallback, not blocked_user_decision.
- all configured cli_command templates pass shlex validation.
- every command template declares required placeholders.
- missing placeholder fails config validation.
- binary present but bad args is not treated as available worker.
- grep hits of old bad templates are allowed only inside regression tests.
```

---

## Acceptance

M2-1.5 passes if:

```text
- every configured local CLI worker has an invocation contract
- command templates parse with shlex
- required placeholders are declared and validated
- invalid CLI arguments are classified as invalid_cli_invocation
- invalid_cli_invocation triggers fallback, not blocked_user_decision
- Hermes real one-shot interface is represented as hermes -z <prompt>
- stale/fake CLI templates are caught before route execution
- worker registry excludes or marks workers with invalid invocation contracts
- route assignment can only select workers with valid or explicitly approved invocation contracts
- no real external CLI execution is required for tests
```

---

# 6.5.6 M2-1.6 — Cache-Aware Execution Economy Engine

## Goal

Decide whether a worker/API/MCP/tool should be activated at all, using real marginal cost instead of raw prompt size.

This stage closes the cost-risk gap exposed by full-CLI style routing. AgentLab must not treat the 9 roles as 9 mandatory agent invocations. It also must not over-penalize workers whose stable role/skill/MCP startup context can reliably hit provider context cache.

Core distinction:

```text
9 roles = always-on governance responsibilities
workers = lazily activated execution resources
LLM/API/CLI/MCP calls = resources whose activation must be justified by marginal cost, risk, and expected value
cached startup context = potentially cheap tokens, not free permission or coordination
```

This is the key product differentiator:

```text
AgentLab is not a multi-agent spammer.
AgentLab is a cache-aware execution economy manager.

It does not win by blindly calling fewer agents.
It wins by knowing when extra agents are cheap, useful, safe, and worth activating.
```

---

## Required Principle

Every task may be reviewed through the 9-role responsibility model, but workers are activated only when the expected value of activation exceeds the effective marginal cost, coordination overhead, and permission risk.

Hard rule:

```text
Do not spawn an unmeasured, unauthorized, or low-value LLM/API/CLI/MCP worker.
If a worker is warm/cached/read-only/low-risk, its activation threshold may be lower.
If a worker can mutate files, run shell, access network, upload data, or use opaque MCP/skills, permission and evidence gates remain strict regardless of token cache.
```

Cost principle:

```text
Optimize for marginal cost, not raw token count.
Stable role/skill/MCP context may be cache-discounted, but permission risk, coordination cost, evidence quality, and state mutation risk are never discounted by token cache.
```

Default order:

```text
1. deterministic local tools
2. cached evidence/context assets
3. local context assembly
4. small cache-friendly direct API reasoning
5. warm/cached read-only reviewer or planner
6. single CLI/API worker for mutation or generation
7. additional reviewer / specialist when marginal value is justified
8. multi-agent / swarm only with explicit approval
```

Examples:

```text
RepoScout
  default: rg / git grep / repo-index
  not default: Claude/Codex/Hermes for simple search
  allowed: cached LLM repo scout if semantic repo understanding is high-value and read-only

InterfaceMapper
  default: ast-grep / tree-sitter-style scripts
  not default: full LLM repo scan
  allowed: cached LLM interface review if deterministic map is incomplete or ambiguous

TesterAuditor
  default: pytest / npm test / diff parser
  not default: LLM test reviewer unless test failure is complex
  allowed: cached reviewer when failure interpretation is cheap and likely to reduce retry loops

Verifier
  default: ruff / eslint / git diff --check / secret scan
  not default: LLM reviewer unless diff risk is high
  allowed: cached read-only LLM reviewer for medium/high-risk semantic diffs

Archivist
  default: local ledger / task compact / git metadata
  not default: LLM call
  allowed: compact cached summarizer when a long phase needs durable project memory
```

---

## Add Runtime Modules

```text
agent_runtime/execution_economy/
  __init__.py
  activation_cost.py
  cache_profile.py
  effective_cost.py
  marginal_utility_gate.py
  role_activation_policy.py
  role_coalescing.py
  context_reuse_policy.py
  escalation_ladder.py
  activation_decision.py
  activation_plan.py
  renderer.py
```

---

## Add Configs

```text
config/execution_economy_policy.yml
config/worker_activation_costs.yml
config/context_cache_policy.yml
config/role_activation_policy.yml
config/escalation_ladders.yml
```

---

## Activation Cost Schema

```yaml
worker_activation_cost:
  worker_id:
  fixed_startup_cost:
    raw_prompt_tokens:
    cacheable_prompt_tokens:
    expected_cache_hit_rate:
    effective_prompt_tokens:
    estimated_cached_input_discount: none | low | medium | high | unknown
    estimated_latency_s:
    operator_friction: low | medium | high
  cache_profile:
    stable_prefix_hash:
    skill_context_hash:
    mcp_manifest_hash:
    last_cache_hit_observed: true | false | unknown
    cache_confidence: low | medium | high | unknown
  variable_cost:
    task_specific_context_tokens:
    context_tokens_per_kb:
    output_tokens_expected:
    dollars_per_call:
  non_token_costs:
    coordination_cost: low | medium | high
    permission_risk: low | medium | high | critical
    state_mutation_risk: low | medium | high | critical
  hidden_costs:
    - context_duplication
    - handoff_interpretation
    - diff_conflict_risk
  confidence: low | medium | high
```

Deterministic tool example:

```yaml
worker_activation_cost:
  worker_id: rg
  fixed_startup_cost:
    raw_prompt_tokens: 0
    cacheable_prompt_tokens: 0
    expected_cache_hit_rate: 0.0
    effective_prompt_tokens: 0
    estimated_cached_input_discount: none
    estimated_latency_s: 0.1
    operator_friction: low
  cache_profile:
    stable_prefix_hash: null
    skill_context_hash: null
    mcp_manifest_hash: null
    last_cache_hit_observed: false
    cache_confidence: high
  variable_cost:
    task_specific_context_tokens: 0
    context_tokens_per_kb: 0
    output_tokens_expected: 0
    dollars_per_call: 0
  non_token_costs:
    coordination_cost: low
    permission_risk: low
    state_mutation_risk: low
  hidden_costs: []
  confidence: high
```

High-skill CLI worker example:

```yaml
worker_activation_cost:
  worker_id: claude_code
  fixed_startup_cost:
    raw_prompt_tokens: 12000
    cacheable_prompt_tokens: 9500
    expected_cache_hit_rate: 0.85
    effective_prompt_tokens: 2500
    estimated_cached_input_discount: high
    estimated_latency_s: 8
    operator_friction: medium
  cache_profile:
    stable_prefix_hash: "sha256:role-skill-prefix"
    skill_context_hash: "sha256:approved-skill-set"
    mcp_manifest_hash: "sha256:declared-mcp-passports"
    last_cache_hit_observed: unknown
    cache_confidence: medium
  variable_cost:
    task_specific_context_tokens: 3000
    context_tokens_per_kb: 180
    output_tokens_expected: 2000
    dollars_per_call: unknown
  non_token_costs:
    coordination_cost: medium
    permission_risk: high
    state_mutation_risk: high
  hidden_costs:
    - context_duplication
    - handoff_interpretation
    - diff_conflict_risk
  confidence: medium
```

---

## Activation Decision Schema

```yaml
activation_decision:
  project_id:
  phase_id:
  task_id:
  role:
  candidate_worker:
  decision: spawn | skip | satisfy_by_deterministic | satisfy_by_cache | coalesce | defer | require_approval
  activation_temperature: deterministic | cold | warm_cached | hot_session | unknown
  satisfied_by: []
  selected_worker:
  selected_provider:
  activation_cost:
    raw_tokens:
    cacheable_tokens:
    effective_tokens:
    estimated_usd:
    effective_estimated_usd:
    latency_class:
    coordination_cost: low | medium | high
    permission_risk: low | medium | high | critical
    state_mutation_risk: low | medium | high | critical
  cache_verdict:
    expected: hit | partial_hit | miss | unknown
    confidence: low | medium | high
    evidence: []
  expected_benefit:
    quality_gain: none | low | medium | high
    risk_reduction: none | low | medium | high
    speed_gain: none | low | medium | high
    recovery_value: none | low | medium | high
  marginal_utility_verdict: justified | not_justified | unknown_requires_approval
  reason: []
  fallback: []
  context_budget:
    max_raw_tokens:
    max_effective_tokens:
    required_assets: []
    excluded_assets: []
  evidence_paths: []
```

Example: skip LLM verifier when deterministic checks are enough:

```yaml
activation_decision:
  role: Verifier
  candidate_worker: claude_code
  decision: satisfy_by_deterministic
  activation_temperature: deterministic
  satisfied_by:
    - ruff_check
    - git_diff_check
    - secret_scan
  expected_benefit:
    quality_gain: low
    risk_reduction: low
    speed_gain: none
  marginal_utility_verdict: not_justified
  reason:
    - deterministic verification is sufficient
    - no high-risk semantic change detected
    - cached LLM reviewer still has low marginal value for this diff
```

Example: spawn cached read-only reviewer because marginal cost is low and risk reduction is useful:

```yaml
activation_decision:
  role: Verifier
  candidate_worker: claude_code
  decision: spawn
  activation_temperature: warm_cached
  selected_worker: claude_code
  activation_cost:
    raw_tokens: 11000
    cacheable_tokens: 9000
    effective_tokens: 2200
    estimated_usd: unknown
    effective_estimated_usd: low
    latency_class: medium
    coordination_cost: low
    permission_risk: low
    state_mutation_risk: low
  cache_verdict:
    expected: hit
    confidence: medium
    evidence:
      - stable role/skill prefix reused
      - read-only review packet
  expected_benefit:
    quality_gain: medium
    risk_reduction: high
    speed_gain: low
  marginal_utility_verdict: justified
  reason:
    - cached startup context makes reviewer activation cheap
    - diff has semantic risk not covered by deterministic checks
    - worker is read-only for this packet
```

Example: spawn Coder because patch work is needed:

```yaml
activation_decision:
  role: Coder
  candidate_worker: claude_code
  decision: spawn
  activation_temperature: warm_cached
  selected_worker: claude_code
  expected_benefit:
    quality_gain: high
    risk_reduction: high
    speed_gain: medium
  marginal_utility_verdict: justified
  reason:
    - task requires multi-file patch generation
    - deterministic tools cannot modify code
    - Coder role has high expected value for this task
    - cache may reduce token cost but write/shell permissions still require approval gates
```

---

## Role Coalescing

Small tasks should not spawn separate workers for every role. Multiple roles can be bundled into one compact packet when the risk is low.

Examples:

```text
Small code fix:
  Supervisor + PromptEngineer + Coder
  → single compact coder packet

Validation task:
  TesterAuditor + Verifier
  → deterministic validation packet or one cached read-only review packet if semantic risk is meaningful

Archive task:
  Archivist
  → local ledger writer, no model call unless a compact cached summary is needed
```

Role coalescing output:

```yaml
role_coalescing:
  coalesced_packet_id:
  roles:
    - Supervisor
    - PromptEngineer
    - Coder
  selected_worker: codex
  reason:
    - small bounded patch
    - no separate planning worker needed
    - one compact context pack has lower effective cost than multiple cold activations
  risk_level: medium
```

---

## Context Reuse Policy

AgentLab must not send raw full project history to every worker.

Preferred context assets:

```text
task_contract.yml
mission_contract.yml
project_brain/current_phase.yml
repo_map.yml
interface_map.yml
diff_summary.md
acceptance_criteria.yml
known_risks.yml
decision_log_compact.yml
related_evidence_index.yml
stable_role_prefix.md
approved_skill_context.md
mcp_provider_passport_index.yml
```

Context budget example:

```yaml
context_budget:
  max_raw_tokens: 16000
  max_effective_tokens: 8000
  required_assets:
    - task_contract
    - changed_files_summary
    - relevant_symbol_map
    - acceptance_criteria
  excluded_assets:
    - full_chat_history
    - unrelated_phase_reports
    - private_runtime_logs
```

---

## Escalation Ladder

Default escalation ladder:

```text
Level 0: deterministic tools
Level 1: cached evidence + local context assembly
Level 2: small cache-friendly API reasoning
Level 3: warm/cached read-only reviewer or planner
Level 4: single CLI coder / mutating worker with approval gates
Level 5: additional specialist reviewer when effective cost and risk reduction justify it
Level 6: multi-agent compare / swarm with explicit approval
```

Escalation triggers:

```text
missing_context
failed_deterministic_validation
patch_required
tests_failed
high_risk_diff
repeated_failure
budget_exceeded
human_approval
cache_miss_or_unknown_cost
```

Escalation ladder example:

```yaml
escalation_ladder:
  initial: deterministic_scan
  if_missing_context: api_supervisor_compact
  if_patch_needed: single_cli_coder
  if_tests_fail: cached_failure_analyzer
  if_diff_high_risk: cached_or_strong_llm_verifier
  if_repeated_failure: multi_agent_redesign
  if_budget_exceeded: stop_or_ask_user
  if_cache_miss_or_unknown_cost: downgrade_or_require_approval
```

---

## CLI

```bash
./agentlab.sh activation-plan --task-packet <path>
./agentlab.sh activation-explain --decision <path>
./agentlab.sh execution-economy-report --project <project>
./agentlab.sh estimate-spawn-cost --worker claude_code --role Coder
./agentlab.sh cache-profile-report --worker claude_code
```

---

## Outputs

```text
projects/<project_id>/execution_economy/
  activation_plan.yml
  activation_decisions/
    supervisor.yml
    reposcout.yml
    interface_mapper.yml
    researcher.yml
    prompt_engineer.yml
    coder.yml
    tester_auditor.yml
    verifier.yml
    archivist.yml
  role_coalescing.yml
  context_reuse_plan.yml
  cache_profile_report.yml
  escalation_ladder.yml
  execution_economy_report.md
```

---

## Tests

```text
tests/test_m2_activation_cost.py
tests/test_m2_cache_profile.py
tests/test_m2_effective_cost.py
tests/test_m2_marginal_utility_gate.py
tests/test_m2_role_activation_policy.py
tests/test_m2_role_coalescing.py
tests/test_m2_context_reuse_policy.py
tests/test_m2_escalation_ladder.py
tests/test_m2_activation_plan_cli.py
```

---

## Acceptance

M2-1.6 passes if:

```text
- large_or_risky_task no longer means activate all 9 LLM/CLI workers
- roles are always checked, workers are lazily activated
- raw prompt tokens, cacheable tokens, effective tokens, and cache confidence are recorded separately
- deterministic tools are preferred for RepoScout / InterfaceMapper / TesterAuditor / Verifier when sufficient
- cached evidence is preferred before repeated tool/model calls
- warm/cached low-risk workers can be activated with a lower threshold when expected marginal value is meaningful
- LLM/API/CLI/MCP worker spawn requires marginal utility gate based on effective cost, not raw token count alone
- token cache never discounts permission risk, state mutation risk, evidence requirements, or coordination risk
- small task can complete with zero or one LLM worker if deterministic checks suffice
- medium/high-risk semantic diff can trigger cached read-only LLM reviewer when justified
- repeated failure can escalate to stronger worker
- high-risk diff can trigger LLM reviewer
- max_quality_swarm requires explicit approval
- every skipped worker has explicit reason
- every spawned worker has raw/effective cost, cache verdict, quality/risk justification, and fallback
```

---

# 6.5.7 M2-1.7 — Skill / MCP Capability Broker

## Goal

Manage heterogeneous skills and MCP services across local workers without forcing every worker to install or expose the same skill/MCP set.

Core principle:

```text
Do not unify every CLI's skills/MCP installation.
Unify capability semantics, provider passports, permissions, cost, trust, transparency, and evidence.
```

This stage prevents AgentLab from becoming a fragile skill-sync manager.

Correct interpretation:

```text
AgentLab-owned skills/SOPs and approved MCP adapters are canonical.
Worker-local skills/MCPs are heterogeneous delegated capabilities.
AgentLab may discover, record, score, and use them, but it does not treat them as truth by default.
```

---

## Provider Types

```text
agentlab_owned_tool
agentlab_owned_skill
agentlab_brokered_mcp
direct_api_provider
worker_local_skill
worker_local_mcp
external_handoff_provider
unknown
```

---

## Provider Priority

Default provider priority:

```text
1. AgentLab-owned deterministic tool / skill
2. AgentLab-brokered approved MCP
3. direct API provider
4. worker-local delegated skill/MCP
5. external manual handoff
```

Rationale:

```text
Transparent, cheap, testable providers should win by default.
Opaque worker-local skills/MCPs may be useful, but they require trust scoring and evidence.
```

---

## Add Runtime Modules

```text
agent_runtime/capability_broker/
  __init__.py
  capability_provider.py
  provider_passport.py
  skill_discovery.py
  mcp_discovery.py
  broker_registry.py
  provider_trust.py
  provider_routing.py
  brokered_invocation.py
  delegated_capability.py
  renderer.py
```

---

## Add Configs

```text
config/capability_provider_registry.yml
config/skill_mcp_broker_policy.yml
config/provider_trust_policy.yml
config/mcp_permission_policy.yml
```

---

## Provider Passport Schema

```yaml
capability_provider_passport:
  provider_id:
  provider_type:
  owner_worker:
  source: discovered | declared | agentlab_owned | external
  canonical_capabilities: []
  transparency: transparent | semi_transparent | opaque
  invocation_mode: direct | brokered_mcp | delegated_worker | manual_handoff
  permissions:
    filesystem_read:
    filesystem_write:
    shell:
    network:
    cloud_upload:
  risk_level: low | medium | high | critical
  cost_model:
    known:
    attribution:
    estimated_usd:
    estimated_tokens:
  verification:
    probe_available:
    audition_required:
    last_successful_use:
  trust_level: trusted | provisional | untrusted | disabled
  disabled_by_default:
  allowed_projects: []
  notes: []
```

AgentLab-owned deterministic provider example:

```yaml
capability_provider_passport:
  provider_id: agentlab_repo_scout_rg
  provider_type: agentlab_owned_tool
  source: agentlab_owned
  canonical_capabilities:
    - read_only_repo_search
  transparency: transparent
  invocation_mode: direct
  permissions:
    filesystem_read: scoped
    filesystem_write: false
    shell: limited
    network: false
    cloud_upload: false
  risk_level: low
  cost_model:
    known: true
    attribution: provider_level
    estimated_usd: 0
    estimated_tokens: 0
  trust_level: trusted
  disabled_by_default: false
```

Worker-local skill example:

```yaml
capability_provider_passport:
  provider_id: claude_local_skill_code_review
  provider_type: worker_local_skill
  owner_worker: claude_code
  source: discovered
  canonical_capabilities:
    - code_review
    - diff_risk_analysis
  transparency: opaque
  invocation_mode: delegated_worker
  permissions:
    filesystem_read: unknown
    filesystem_write: possible
    shell: possible
    network: unknown
    cloud_upload: unknown
  risk_level: high
  cost_model:
    known: false
    attribution: worker_level_only
  verification:
    probe_available: false
    audition_required: true
    last_successful_use: null
  trust_level: provisional
  disabled_by_default: true
```

---

## Discovery Levels

```text
Level 0: declarative config
  User or config declares worker-local skills/MCPs. Low risk, low trust.

Level 1: safe probe
  Run safe list/version/help commands only if supported. Never leak tokens.

Level 2: sandbox audition
  Test provider capability inside mock repo/fixture. No real user repo mutation.
```

---

## Brokered vs Delegated MCP

Preferred:

```text
AgentLab MCP Broker
→ approved MCP server
→ scoped tool call
→ evidence ledger
→ result returned as context asset
```

Fallback:

```text
Worker-local MCP
→ represented as delegated opaque/semi-transparent capability
→ requires provider passport
→ routed through risk/cost/approval policy
```

Rule:

```text
If AgentLab can call a tool directly or through an approved broker, do not ask an LLM worker to spend tokens discovering the same information through its own MCP unless the marginal value is justified.
```

---

## CLI

```bash
./agentlab.sh capability-providers
./agentlab.sh capability-provider-inspect --provider <id>
./agentlab.sh skill-discover --worker claude_code --safe
./agentlab.sh mcp-discover --worker claude_code --safe
./agentlab.sh capability-broker-plan --capability code_review
./agentlab.sh provider-trust-report
```

---

## Outputs

```text
projects/<project_id>/capability_broker/
  provider_passports.yml
  broker_registry.yml
  provider_trust_report.md
  provider_routing_decisions.yml
  delegated_capabilities.yml
```

---

## Tests

```text
tests/test_m2_capability_provider_passport.py
tests/test_m2_skill_discovery.py
tests/test_m2_mcp_discovery.py
tests/test_m2_provider_trust_policy.py
tests/test_m2_provider_routing.py
tests/test_m2_brokered_invocation.py
tests/test_m2_delegated_capability.py
```

---

## Acceptance

M2-1.7 passes if:

```text
- AgentLab does not require every worker to share the same skills/MCP servers
- worker-local skills are represented as delegated opaque capabilities
- worker-local MCPs are represented as delegated opaque or semi-transparent providers
- AgentLab-owned tools/skills are preferred when cheaper and transparent
- MCP access is brokered through AgentLab when possible
- worker-local MCP use is allowed only as declared/delegated capability
- every provider has a passport
- every provider has permissions, risk, trust, cost, and transparency level
- high-risk MCP providers require approval
- cached evidence is preferred before tool/MCP calls
- provider selection is explainable
```

---

# 6.6 M2-2 — Capability Schema & 9-Role Requirement Matrix

## Goal

Separate AgentLab roles from concrete CLIs.

A role is not a CLI.
A role requires capabilities.
A capability can be provided by one or more workers/tools.

This is the conceptual center of M2.

## 9 AgentLab Roles

```text
Supervisor
RepoScout
InterfaceMapper
Researcher
PromptEngineer
Coder
TesterAuditor
Verifier
Archivist
```

## Add Modules

```text
agent_runtime/capabilities/
  __init__.py
  capability_schema.py
  role_requirements.py
  compatibility.py
  risk_tags.py
  renderer.py
```

## Add Configs

```text
config/capability_schema.yml
config/agent_role_requirements.yml
config/worker_capability_defaults.yml
```

## Capability Families

```text
planning
task_decomposition
budget_reasoning
read_only_repo_search
symbol_lookup
structural_ast_scan
external_research
web_search
context_assembly
prompt_handoff
file_edit
patch_generation
shell_execution
test_execution
diff_review
lint_check
format_check
secret_scan
artifact_archive
git_commit
multimodal_generation
cloud_upload
rag_query
frontdesk_chat
approval_ui
```

## Role Requirement Example

```yaml
roles:
  supervisor:
    required_capabilities:
      - planning
      - task_decomposition
      - budget_reasoning
    preferred_capabilities:
      - long_context
      - tool_routing
    forbidden_capabilities: []
    default_risk_ceiling: medium
    human_approval_required_for:
      - shell_execution
      - cloud_upload
      - external_network

  repo_scout:
    required_capabilities:
      - read_only_repo_search
    preferred_capabilities:
      - symbol_lookup
    forbidden_capabilities:
      - file_edit
      - cloud_upload
    default_risk_ceiling: low

  interface_mapper:
    required_capabilities:
      - structural_ast_scan
    preferred_capabilities:
      - symbol_lookup
      - read_only_repo_search
    forbidden_capabilities:
      - cloud_upload
    default_risk_ceiling: low

  researcher:
    required_capabilities:
      - external_research
    preferred_capabilities:
      - web_search
      - rag_query
    forbidden_capabilities:
      - file_edit
    default_risk_ceiling: medium
    human_approval_required_for:
      - external_network
      - cloud_upload

  prompt_engineer:
    required_capabilities:
      - context_assembly
      - prompt_handoff
    preferred_capabilities:
      - budget_reasoning
    forbidden_capabilities:
      - file_edit
      - shell_execution
    default_risk_ceiling: medium

  coder:
    required_capabilities:
      - file_edit
      - patch_generation
    preferred_capabilities:
      - shell_execution
      - test_execution
    forbidden_capabilities: []
    default_risk_ceiling: high

  tester_auditor:
    required_capabilities:
      - test_execution
      - diff_review
    preferred_capabilities:
      - evidence_quality_review
    forbidden_capabilities:
      - cloud_upload
    default_risk_ceiling: medium

  verifier:
    required_capabilities:
      - lint_check
      - diff_review
      - secret_scan
    preferred_capabilities:
      - format_check
      - test_execution
    forbidden_capabilities:
      - unrelated_file_edit
    default_risk_ceiling: medium

  archivist:
    required_capabilities:
      - artifact_archive
    preferred_capabilities:
      - git_commit
    forbidden_capabilities:
      - unsafe_delete
    default_risk_ceiling: medium
```

## CLI

```bash
./agentlab.sh capabilities
./agentlab.sh role-requirements
./agentlab.sh role-inspect --role Coder
./agentlab.sh role-compatible-workers --role RepoScout
```

## Tests

```text
tests/test_m2_capability_schema.py
tests/test_m2_role_requirements.py
tests/test_m2_role_worker_compatibility.py
```

## Acceptance

M2-2 passes if:

```text
- all 9 roles are defined
- each role has required capabilities
- deterministic tools can satisfy deterministic roles
- rg/git grep cannot be assigned as Coder
- pytest cannot be assigned as Supervisor
- bl cannot be assigned to cloud_upload tasks without approval
- cloud/multimodal/upload capabilities are marked high-risk
```

---

# 6.7 M2-3 — Worker Audition / Performance Ledger

## Goal

Evaluate workers instead of trusting static recommendations.

AgentLab should know not only whether a CLI exists, but whether it performs well for a role.

## Audition Levels

```text
quick
  command presence, version, help output, safe dry-run if available

standard
  small fixture task per role, no real repo mutation

deep
  controlled sandbox task with mock repo and measurable outcome
```

## Add Modules

```text
agent_runtime/workers/
  audition.py
  audition_tasks.py
  audition_runner.py
  audition_scorer.py
  performance_ledger.py
  sandbox.py
```

## Audition Task Types

```text
repo_search_task
interface_mapping_task
small_patch_task
test_runner_task
lint_review_task
handoff_generation_task
research_summary_task
archive_task
```

## Score Dimensions

```text
role_fit_score
success_rate
cost_score
latency_score
safety_score
diff_minimality_score
evidence_quality_score
operator_friction_score
```

## Performance Ledger Schema

```yaml
worker_performance:
  worker_id: claude_code
  role_scores:
    coder: 0.91
    supervisor: 0.82
    tester_auditor: 0.72
  cost_score: 0.35
  safety_score: 0.68
  last_audition:
    timestamp:
    suite: standard
    verdict: pass
  historical_runs:
    total: 12
    success: 10
    failed: 2
```

## CLI

```bash
./agentlab.sh worker-audition --all --level quick
./agentlab.sh worker-audition --worker codex --role Coder --level standard
./agentlab.sh worker-scorecard
```

## Tests

```text
tests/test_m2_worker_audition.py
tests/test_m2_audition_scorer.py
tests/test_m2_worker_performance_ledger.py
```

## Acceptance

M2-3 passes if:

```text
- audition can run with fully mocked workers
- failed audition does not break registry
- role scorecards are produced
- performance ledger persists
- real external CLI audition is opt-in
- no user repo is mutated during audition
- audition output can influence route assignment
```

---

# 6.8 M2-4 — Role Assignment Router v2

## Goal

Assign local workers/tools to the 9 AgentLab roles based on:

```text
role requirements
worker capabilities
worker availability
mode
tier
cost policy
risk policy
approval status
historical performance
project override
task packet constraints
```

## Add Modules

```text
agent_runtime/routing/
  __init__.py
  role_assignment.py
  worker_router.py
  route_decision.py
  fallback_policy.py
  mode_tier_policy.py
  approval_gate.py
  renderer.py
```

## Add Configs

```text
config/role_assignment_policy.yml
config/worker_fallback_policy.yml
config/mode_tier_worker_policy.yml
```

## Assignment Modes

```text
single_cli_company
  One strong local agent can fill multiple roles through separate task contracts.

hybrid_local_company
  Deterministic tools handle search/test/lint/archive; agent CLIs handle reasoning/coding.

cost_saving_factory
  Prefer zero-cost deterministic tools and cheap models; escalate only on failure.

max_quality_swarm
  Strong workers can run competing plans/patches with verifier arbitration.

frontdesk_gateway
  OpenClaw/WeChat/WebUI receives the user request; AgentLab compiles/contracts/routes.
```

## Route Decision Schema

```yaml
route_decision:
  project_id:
  phase_id:
  task_id:
  role: Coder
  selected_worker: claude_code
  selected_command: claude
  selection_reason:
    - required file_edit and patch_generation
    - worker has highest coder score
    - max_quality tier allows high-cost worker
  rejected_workers:
    - worker: rg
      reason: lacks file_edit
    - worker: bl
      reason: cloud_upload risk not needed
  required_capabilities:
    - file_edit
    - patch_generation
  risk_level: high
  approval_required: true
  cost_estimate:
    known: false
    policy: approval_required
  fallback_workers:
    - codex
    - aider
  constraints:
    allowed_files: []
    forbidden_files: []
  evidence_paths: []
```

## CLI

```bash
./agentlab.sh assign-role --role Coder --project DemoProject --tier performance
./agentlab.sh route-task --task-packet /tmp/task_packet.yml
./agentlab.sh route-explain --decision /tmp/route_decision.yml
```

## Tests

```text
tests/test_m2_role_assignment_router.py
tests/test_m2_worker_fallback_policy.py
tests/test_m2_mode_tier_worker_policy.py
tests/test_m2_route_decision_schema.py
```

## Acceptance

M2-4 passes if:

```text
- Coder falls back from Claude to Codex/Aider when Claude is unavailable
- RepoScout prefers rg/git grep over LLM workers
- InterfaceMapper prefers ast-grep/tree-sitter-style tools
- Verifier prefers deterministic lint/test tools
- high-risk workers require approval
- route decisions record why selected and why rejected
- route decisions are saved as evidence
- route decision can be explained by CLI and assistant mode
```

---

# 6.9 M2-5 — Config Center v2

## Goal

Make configuration transparent, layered, validated, override-aware, and connected to worker/role routing.

## Add Modules

```text
agent_runtime/config_center/
  __init__.py
  schema.py
  loader.py
  validator.py
  resolver.py
  diff.py
  profile.py
  secrets_redaction.py
  renderer.py
```

## Add Configs

```text
config/config_center.yml
config/config_ui_schema.yml
config/config_profiles.yml
```

## Config Layers

```text
global defaults
environment profile
local worker registry
role assignment policy
cost policy
risk policy
project override
executor override
skill override
capability override
user approval override
runtime temporary override
```

## CLI

```bash
./agentlab.sh config-list
./agentlab.sh config-get --key routing.default_mode
./agentlab.sh config-diff --project DemoProject
./agentlab.sh config-validate
```

## Tests

```text
tests/test_m2_config_center.py
tests/test_m2_config_resolution.py
tests/test_m2_config_cli.py
```

## Acceptance

M2-5 passes if:

```text
- config values show source layer
- invalid config fails cleanly
- project override works
- worker/role routing configs validate
- config diff works
- no secret values are displayed raw
```

---

# 6.10 M2-6 — Cost, Risk & Approval System v2

## Goal

Connect costs and approval gates to worker routing.

Cost is not only model token cost. M2 must treat unknown local CLI cost, paid API usage, cloud uploads, video/image generation, and long-running agents as budget-sensitive operations.

## Add Modules

```text
agent_runtime/costs/
  budget_policy.py
  estimator.py
  spend_ledger.py
  attribution.py
  alerts.py
  efficiency_review.py
  model_cost_profile.py
  executor_cost_profile.py
  worker_cost_profile.py
  renderer.py

agent_runtime/approvals/
  decision_card.py
  approval_policy.py
  approval_ledger.py
  risk_gate.py
  renderer.py
```

## Add Configs

```text
config/cost_policy_v2.yml
config/model_cost_profiles.yml
config/executor_cost_profiles.yml
config/worker_cost_profiles.yml
config/approval_policy.yml
```

## Cost Attribution Dimensions

```text
project
phase
task
role
worker
executor
model
skill
capability
artifact
recovery_attempt
```

## Approval Triggers

```text
unknown external CLI cost
high-cost model
cloud upload
multimodal generation
file deletion
large diff
shell execution
network access
private path access
secret-adjacent file access
public WebUI/OpenClaw bind
```

## CLI

```bash
./agentlab.sh cost-status --project DemoProject
./agentlab.sh cost-estimate --task-packet /tmp/task_packet.yml
./agentlab.sh cost-alerts --project DemoProject
./agentlab.sh cost-efficiency-review --project DemoProject

./agentlab.sh approvals
./agentlab.sh approve --decision-card <id>
./agentlab.sh reject --decision-card <id>
```

## Tests

```text
tests/test_m2_cost_policy.py
tests/test_m2_cost_estimator.py
tests/test_m2_spend_ledger.py
tests/test_m2_cost_alerts.py
tests/test_m2_cost_attribution.py
tests/test_m2_approval_policy.py
tests/test_m2_decision_cards.py
```

## Acceptance

M2-6 passes if:

```text
- estimated cost is generated before route execution
- spend ledger records role/worker/model/executor attribution
- hard limit blocks execution
- soft limit creates approval decision card
- unknown external CLI cost requires approval
- risky worker capabilities require approval
- bl/cloud/multimodal calls are gated before upload/generation
- efficiency review compares cost across workers and roles
```

---

# 6.11 M2-7 — Observability / Event Timeline v2

## Goal

Create a unified event timeline covering mission, routing, worker assignment, cost, approvals, execution, evidence, acceptance, and recovery.

## Add Modules

```text
agent_runtime/observability/
  event.py
  event_log.py
  timeline.py
  query.py
  renderer.py
  log_redaction.py
```

## Event Types

```text
mission_compiled
worker_detected
worker_auditioned
role_assigned
route_decision_created
approval_requested
approval_accepted
approval_rejected
task_packet_created
executor_started
executor_finished
artifact_created
evidence_collected
cost_estimated
cost_recorded
phase_accepted
phase_retried
recovery_planned
config_changed
ui_action
```

## Data Layout

```text
projects/<project_id>/observability/
  timeline.jsonl
  event_log.jsonl
  warnings.yml
  executor_runs.yml
  artifact_events.yml
  cost_events.yml
  decision_events.yml
  route_events.yml
  worker_events.yml
```

## CLI

```bash
./agentlab.sh timeline --project DemoProject
./agentlab.sh timeline --project DemoProject --event-type role_assigned
./agentlab.sh event-log-tail --project DemoProject
```

## Tests

```text
tests/test_m2_event_log.py
tests/test_m2_timeline_query.py
tests/test_m2_log_redaction.py
tests/test_m2_route_events.py
```

## Acceptance

M2-7 passes if:

```text
- key actions emit events
- route decisions appear in timeline
- approvals appear in timeline
- cost events link to role/worker/task
- events link to artifacts/evidence/decision cards
- logs redact secrets and private paths
- timeline is append-only
```

---

# 6.12 M2-8 — Control Panel: Workers / Skills / Capabilities / Executors

## Goal

Unify management of local workers, skills, capabilities, and executors.

This replaces the old narrow Skill / Capability / Executor Control Panel with a broader company-management view.

## Add Modules

```text
agent_runtime/control_panel/
  worker_control.py
  skill_control.py
  capability_control.py
  executor_control.py
  approval_actions.py
  status_summary.py
  renderer.py
```

## Features

```text
- list local workers by status
- enable/disable worker
- show worker permissions/risk/cost
- show worker role scores
- show assigned roles
- force-assign worker to role for a project
- reset assignment override
- list skills by status
- enable/disable skill
- approve/reject skill candidate
- show skill risk/permissions
- list capabilities and active backend
- approve capability use
- list executors and trust level
- enable/disable executor
- show executor cost policy
```

## CLI

```bash
./agentlab.sh control workers
./agentlab.sh control worker-inspect --worker claude_code
./agentlab.sh control worker-enable --worker codex
./agentlab.sh control worker-disable --worker bl

./agentlab.sh control skills
./agentlab.sh control capabilities
./agentlab.sh control executors
./agentlab.sh control approve --decision-card <id>
```

## Tests

```text
tests/test_m2_control_panel_workers.py
tests/test_m2_control_panel_skills.py
tests/test_m2_control_panel_capabilities.py
tests/test_m2_control_panel_executors.py
```

## Acceptance

M2-8 passes if:

```text
- operator can inspect workers/skills/capabilities/executors
- mutating actions require explicit approval where risky
- disabled workers cannot be routed
- disabled capabilities cannot execute
- risky entities show warnings
- route overrides are recorded and reversible
```

---

# 6.13 M2-9 — AgentLab Assistant Modes

## Goal

Give AgentLab a grounded self-explanation and operation assistant layer.

The assistant must explain AgentLab state, not hallucinate free-form answers.

## Add Modules

```text
agent_runtime/assistant/
  modes.py
  state_reader.py
  response_planner.py
  explanations.py
  command_suggestions.py
  route_explainer.py
  worker_explainer.py
```

## Modes

```text
operator mode
  Help user operate AgentLab.

planner mode
  Explain roadmap, phase status, next action.

reviewer mode
  Explain acceptance verdict, evidence, risks.

teacher mode
  Explain why the system made a decision.

router mode
  Explain why a role was assigned to a worker.

worker doctor mode
  Explain missing/broken local CLI setup.
```

## CLI

```bash
./agentlab.sh ask --project DemoProject "为什么这个项目被 blocked？"
./agentlab.sh explain-phase --project DemoProject --phase phase_001
./agentlab.sh explain-cost --project DemoProject
./agentlab.sh explain-route --decision /tmp/route_decision.yml
./agentlab.sh explain-worker --worker claude_code
```

## Tests

```text
tests/test_m2_assistant_modes.py
tests/test_m2_assistant_state_grounding.py
tests/test_m2_assistant_route_explainer.py
tests/test_m2_assistant_worker_explainer.py
```

## Acceptance

M2-9 passes if:

```text
- assistant answers using project state
- assistant cites local artifact paths/state references
- assistant can explain worker selection
- assistant can explain rejected workers
- assistant can explain cost/risk/approval gates
- assistant does not hallucinate unavailable facts
```

---

# 6.14 M2-10 — TUI

## Goal

Build a terminal control surface for project operations and local agent company management.

## Add Modules

```text
agentlab_tui/
  __init__.py
  app.py
  screens/
  widgets/
  commands.py
```

Or place under existing app structure if preferred.

## TUI Screens

```text
Project List
Project Overview
Current Phase
Task Packets
Route Decisions
Worker Registry
Role Assignment Matrix
Worker Scorecards
Executor Results
Evidence
Cost Dashboard
Decision Cards
Skills
Capabilities
Executors
Config
Logs / Timeline
```

## Required Actions

```text
approve
reject
pause
resume
retry
rollback
open artifact
show cost
show next action
export handoff
enable/disable worker
inspect worker
run worker doctor
show route explanation
```

## CLI

```bash
./agentlab.sh tui
```

## Tests

Use lightweight tests only:

```text
tests/test_m2_tui_routes.py
tests/test_m2_tui_command_handlers.py
tests/test_m2_tui_worker_views.py
```

## Acceptance

M2-10 passes if:

```text
- TUI can start locally
- project list loads
- project status view works
- worker registry view works
- role assignment view works
- decision card approve/reject calls backend APIs
- cost status visible
- TUI failure does not break CLI core
```

---

# 6.15 M2-11 — WebUI

## Goal

Build a local WebUI dashboard for AgentLab operations and local worker/company management.

## Add Modules

```text
agentlab_app/dashboard/
  app.py
  routes.py
  api.py
  templates/
  static/
```

Or use existing app structure.

## Pages

```text
/dashboard
/projects
/project/<id>
/project/<id>/timeline
/project/<id>/costs
/project/<id>/phases
/project/<id>/artifacts
/project/<id>/routes
/workers
/workers/<id>
/roles
/skills
/capabilities
/executors
/settings
/recovery
/approvals
```

## Security

```text
- bind to 127.0.0.1 by default
- no public bind unless explicit config and approval
- no secrets display
- path redaction
- mutating actions require CSRF or local action token if applicable
- read-only mode available
- OpenClaw/frontdesk gateway status is visible but cannot expose private endpoints by default
```

## CLI

```bash
./agentlab.sh webui --host 127.0.0.1 --port 8765
```

## Tests

```text
tests/test_m2_webui_routes.py
tests/test_m2_webui_security.py
tests/test_m2_webui_api.py
tests/test_m2_webui_worker_pages.py
```

## Acceptance

M2-11 passes if:

```text
- WebUI starts locally
- project overview loads
- worker registry page loads
- role assignment page loads
- timeline/cost/phase/artifact pages work
- decision actions can be approved/rejected
- WebUI does not expose secrets
- WebUI can be disabled
```

---

# 6.16 M2-12 — Operator Acceptance Demo

## Goal

Prove M2 works as an operator-controlled local agent company.

## Demo Flow

```text
1. run runtime-doctor
2. run worker-scan
3. build worker registry
4. load 9-role requirement matrix
5. run mocked worker audition
6. create demo project
7. generate task packet
8. estimate cost
9. route task to role/worker
10. create route_decision.yml
11. request approval if needed
12. show project/route/cost in TUI
13. show project/route/cost in WebUI
14. ingest mock executor result
15. generate phase acceptance
16. view timeline
17. approve/retry decision
18. show cost report
19. show worker scorecard
20. export operator report
```

## CLI

```bash
./agentlab.sh m2-operator-demo --out acceptance_runs/m2_operator_demo
```

## Acceptance Report

Create:

```text
acceptance_runs/m2_operator_demo/M2_OPERATOR_OS_EXECUTION_ECONOMY_REPORT.md
```

Include:

```text
- runtime hygiene report
- worker registry summary
- detected/mocked worker cards
- role requirement matrix summary
- audition scorecard
- route_decision.yml examples
- approval decision card examples
- cost estimate and ledger examples
- timeline excerpts
- TUI smoke result
- WebUI smoke result
- assistant explanation examples
- safety notes
- known limitations
```

## Final M2 Acceptance

M2 fully passes if:

```text
- runtime hygiene passes
- worker registry works
- all 9 roles have capability requirements
- worker audition works with mocks
- role assignment router produces explainable route decisions
- config center works
- cost/risk/approval gates work
- timeline records key events
- WebUI/TUI can inspect same project and route decisions
- assistant can explain project state and worker routing
- user can approve/reject/retry from UI/TUI/CLI
- core CLI works without UI
- no real external CLI execution is required for tests
- no secrets/private paths are leaked
```


# 7. M3 — Project-to-Revenue OS

## 7.1 M3 Objective

M3 upgrades AgentLab from project governance to project operation and assetization.

M3 answers:

```text
Why is this project being produced?
Who is it for?
What assets are being created?
How are those assets used?
What revenue or value path exists?
What is the cost?
What data should be tracked?
How does the strategy improve?
What SOP/skill should be learned?
```

## 7.2 M3 Non-Goals

Do not implement in M3:

```text
- unsafe growth hacking
- fake engagement
- spam automation
- platform policy evasion
- bulk account creation
- payment processing unless explicitly scoped
- legal contract automation without human review
- unapproved real platform posting
```

M3 is about planning, assetization, legitimate production, analytics, compliance, and delivery loops.

---

## 7.3 M3-1 — Business Contract

### Goal

Every business-oriented project must have a business brain.

### Add Modules

```text
agent_runtime/business/
  __init__.py
  business_contract.py
  revenue_model.py
  customer_profile.py
  unit_economics.py
  monetization_plan.py
  commercial_risk.py
  success_metrics.py
  renderer.py
```

### Business Brain Layout

```text
projects/<project_id>/business_brain/
  business_goal.yml
  revenue_model.yml
  customer_profile.yml
  monetization_plan.yml
  cost_model.yml
  pricing_assumptions.yml
  risk_register.yml
  success_metrics.yml
```

### Business Contract Schema

```yaml
business_contract:
  project_id:
  business_goal:
  target_customer_or_audience:
  problem_solved:
  offer:
  deliverables:
  revenue_model:
    type: service | content | product | consulting | licensing | subscription | unknown
    assumptions: []
  cost_model:
    fixed_costs: []
    variable_costs: []
    unknowns: []
  success_metrics: []
  failure_thresholds: []
  compliance_boundaries: []
  human_decision_points: []
```

### CLI

```bash
./agentlab.sh business-compile --project DemoProject --out projects/DemoProject/business_brain
./agentlab.sh business-status --project DemoProject
```

### Tests

```text
tests/test_m3_business_contract.py
tests/test_m3_revenue_model.py
tests/test_m3_success_metrics.py
```

### Acceptance

M3-1 passes if:

```text
- business_contract can be generated from project brief
- revenue model is explicit
- customer/audience is explicit
- success/failure metrics exist
- compliance boundaries exist
- unknowns are not hidden
```

---

## 7.4 M3-2 — Asset Registry + Lineage

### Goal

Turn project outputs into durable assets.

### Add Modules

```text
agent_runtime/assets/
  __init__.py
  asset_registry.py
  asset_lineage.py
  asset_versioning.py
  rights_metadata.py
  usage_tracker.py
  quality_report.py
  renderer.py
```

### Asset Layout

```text
projects/<project_id>/assets/
  asset_registry.yml
  asset_lineage.yml
  version_history.yml
  rights_and_license.yml
  usage_records.yml
  asset_quality_reports/
```

### Asset Types

```text
text
script
novel_chapter
paper_summary
research_note
video
cover
subtitle
audio
code_repo
dataset
prompt
SOP
proposal
contract
delivery_package
analytics_report
platform_post
template
```

### Asset Schema

```yaml
asset:
  asset_id:
  type:
  title:
  path:
  version:
  status: draft | reviewed | delivered | published | retired
  created_from: []
  derived_assets: []
  rights:
    owner:
    license:
    usage_constraints: []
  usage:
    platforms: []
    campaigns: []
    clients: []
  quality:
    score:
    reviewer:
    notes: []
  linked_revenue: []
  linked_delivery: []
  linked_metrics: []
```

### CLI

```bash
./agentlab.sh asset-register --project DemoProject --path outputs/script.md --type script
./agentlab.sh asset-lineage --project DemoProject --asset asset_001
./agentlab.sh asset-list --project DemoProject
```

### Tests

```text
tests/test_m3_asset_registry.py
tests/test_m3_asset_lineage.py
tests/test_m3_asset_versioning.py
```

### Acceptance

M3-2 passes if:

```text
- artifacts can be registered as assets
- asset lineage can track source/derived relationships
- versions are recorded
- usage metadata exists
- rights/license fields exist
- asset quality report can be attached
```

---

## 7.5 M3-3 — Production Pipeline Templates

### Goal

Move from one-off project phases to repeatable production pipelines.

### Add Modules

```text
agent_runtime/production/
  __init__.py
  pipeline_template.py
  pipeline_instance.py
  production_calendar.py
  batch_scheduler.py
  stage_gate.py
  throughput_tracker.py
  backlog_manager.py
  renderer.py
```

### Add Config

```text
config/production_pipeline_templates.yml
```

### Required Templates

```text
content_ip_pipeline
service_delivery_pipeline
saas_product_pipeline
research_consulting_pipeline
local_automation_pipeline
audio_music_pipeline
```

### Example: content_ip_pipeline

```text
topic_or_idea
→ research_or_reference
→ outline
→ draft
→ script
→ storyboard
→ media_assets
→ cover_title_description
→ publish_plan
→ data_collection
→ review
→ next_batch_strategy
```

### Example: service_delivery_pipeline

```text
lead
→ requirement_clarification
→ quote
→ contract_scope
→ execution
→ acceptance
→ delivery
→ support
→ followup
→ upsell_or_referral
```

### Pipeline Instance Layout

```text
projects/<project_id>/production/
  pipeline.yml
  calendar.yml
  backlog.yml
  batches/
  stage_gates/
  throughput_report.yml
```

### CLI

```bash
./agentlab.sh production-plan --project DemoProject --template content_ip_pipeline
./agentlab.sh production-status --project DemoProject
./agentlab.sh production-next --project DemoProject
```

### Tests

```text
tests/test_m3_production_templates.py
tests/test_m3_pipeline_instance.py
tests/test_m3_stage_gate.py
```

### Acceptance

M3-3 passes if:

```text
- required pipeline templates load
- pipeline instance can be created
- stage gates exist
- assets are linked to pipeline stages
- production-next recommends next stage
- pipeline does not auto-post externally
```

---

## 7.6 M3-4 — Market / Channel Intelligence

### Goal

Maintain project-specific market/channel knowledge.

### Add Modules

```text
agent_runtime/market/
  __init__.py
  platform_policy.py
  channel_strategy.py
  competitor_tracker.py
  audience_model.py
  offer_builder.py
  pricing_playbook.py
  trend_watch.py
  renderer.py
```

### Layout

```text
projects/<project_id>/market_brain/
  platform_rules.yml
  channel_strategy.yml
  competitor_notes.yml
  audience_segments.yml
  trend_watch.yml
  content_style_guides.yml
  offer_templates.yml
  pricing_playbook.yml
```

### Provider Policy

Agent-Reach and similar tools may be registered as providers, but:

```text
- disabled by default
- dry-run first
- rate-limited
- no login-wall bypass
- no private data extraction
- all sources enter citation ledger
- platform terms risk is recorded
```

### CLI

```bash
./agentlab.sh market-init --project DemoProject
./agentlab.sh market-plan --project DemoProject
./agentlab.sh market-source-add --project DemoProject --url <url>
```

### Tests

```text
tests/test_m3_market_brain.py
tests/test_m3_channel_strategy.py
tests/test_m3_market_provider_policy.py
```

### Acceptance

M3-4 passes if:

```text
- market brain can be created
- channel strategy can be represented
- competitor notes can be attached
- Agent-Reach-like providers remain disabled unless approved
- sources are cited
```

---

## 7.7 M3-5 — Analytics + Revenue Ledger

### Goal

Track cost, revenue, metrics, experiments, attribution, and ROI.

### Add Modules

```text
agent_runtime/analytics/
  __init__.py
  metric_schema.py
  data_ingestion.py
  experiment_tracker.py
  attribution.py
  revenue_ledger.py
  roi_report.py
  growth_report.py
  strategy_update.py
  renderer.py
```

### Layout

```text
projects/<project_id>/analytics/
  metrics.yml
  experiments.yml
  revenue_ledger.yml
  cost_ledger.yml
  attribution_report.yml
  roi_report.md
  weekly_review.md
  strategy_updates.yml
```

### Metric Families

#### Content

```text
views
click_through_rate
completion_rate
followers
comments
saves
shares
revenue
ad_conversion
```

#### Service

```text
lead_count
conversion_rate
average_order_value
delivery_cycle_time
revision_rate
gross_margin
repeat_purchase_rate
client_satisfaction
```

#### Product

```text
visits
signups
activation
retention
paid_conversion
churn
feature_usage
support_cost
```

### CLI

```bash
./agentlab.sh analytics-init --project DemoProject
./agentlab.sh revenue-add --project DemoProject --amount 100 --source manual
./agentlab.sh metrics-add --project DemoProject --metric views --value 1000
./agentlab.sh roi-report --project DemoProject
```

### Tests

```text
tests/test_m3_metrics_schema.py
tests/test_m3_revenue_ledger.py
tests/test_m3_roi_report.py
tests/test_m3_strategy_update.py
```

### Acceptance

M3-5 passes if:

```text
- metrics schema exists
- revenue ledger records manual entries
- cost ledger can be linked
- ROI report can be generated
- strategy update can reference metrics
- no external analytics API is required
```

---

## 7.8 M3-6 — Compliance / Risk Brain

### Goal

Keep business automation safe and legitimate.

### Add Modules

```text
agent_runtime/compliance/
  __init__.py
  policy_registry.py
  platform_terms_check.py
  copyright_check.py
  client_data_policy.py
  automation_risk.py
  content_safety_gate.py
  contract_risk.py
  renderer.py
```

### Layout

```text
projects/<project_id>/compliance/
  risk_register.yml
  approval_gates.yml
  platform_policy_notes.yml
  copyright_notes.yml
  client_data_handling.yml
  automation_risk.yml
```

### Explicitly Forbidden Categories

```text
fake engagement
spam automation
bulk account creation
platform risk evasion
circumventing rate limits
bypassing paywalls/login walls
impersonating humans
stealing copyrighted material
leaking client data
posting without approval
```

### CLI

```bash
./agentlab.sh compliance-init --project DemoProject
./agentlab.sh compliance-check --project DemoProject --asset asset_001
./agentlab.sh compliance-risks --project DemoProject
```

### Tests

```text
tests/test_m3_compliance_policy.py
tests/test_m3_platform_risk.py
tests/test_m3_client_data_policy.py
```

### Acceptance

M3-6 passes if:

```text
- compliance brain can be created
- risk register exists
- risky automation requires approval
- forbidden categories are blocked
- assets can be checked for rights/client data flags
```

---

## 7.9 M3-7 — CRM / Client Delivery Loop

### Goal

Support service-style projects from lead to delivery to follow-up.

### Add Modules

```text
agent_runtime/crm/
  __init__.py
  lead.py
  client_profile.py
  opportunity.py
  proposal.py
  contract_state.py
  delivery_status.py
  invoice_record.py
  followup.py
  renderer.py
```

### Layout

```text
projects/<project_id>/crm/
  leads.yml
  clients.yml
  opportunities.yml
  proposals/
  contracts/
  delivery_records/
  followups.yml
```

### CLI

```bash
./agentlab.sh crm-lead-add --project DemoProject --name "Client A"
./agentlab.sh crm-proposal-create --project DemoProject --lead lead_001
./agentlab.sh crm-delivery-status --project DemoProject
./agentlab.sh crm-followup-plan --project DemoProject
```

### Tests

```text
tests/test_m3_crm_leads.py
tests/test_m3_proposal.py
tests/test_m3_delivery_status.py
```

### Acceptance

M3-7 passes if:

```text
- lead can be recorded
- proposal skeleton can be created
- delivery status can link assets and acceptance history
- follow-up plan can be generated
- no payment/legal automation is performed
```

---

## 7.10 M3-8 — SOP / Skill Factory 2.0

### Goal

Convert successful workflows and failures into reusable SOPs, playbooks, and skill candidates.

BabyAGI-style self-building is only a reference. No automatic unsafe execution.

### Add Modules

```text
agent_runtime/sop_factory/
  __init__.py
  sop_candidate.py
  playbook.py
  workflow_miner.py
  failure_pattern.py
  skill_candidate_builder.py
  quality_rubric.py
  promotion_recommendation.py
  renderer.py
```

### Layout

```text
projects/<project_id>/sop_factory/
  sop_candidates/
  playbooks/
  skill_candidates/
  quality_rubrics/
  failure_patterns/
```

### Process

```text
successful project phase
→ extract repeatable workflow
→ create SOP candidate
→ create skill candidate if automatable
→ attach quality rubric
→ require human review
→ stage/promote through existing Skill OS
```

### CLI

```bash
./agentlab.sh sop-review --project DemoProject
./agentlab.sh sop-candidates --project DemoProject
./agentlab.sh sop-promote-candidate --project DemoProject --candidate sop_001
```

### Tests

```text
tests/test_m3_sop_candidate.py
tests/test_m3_workflow_miner.py
tests/test_m3_skill_candidate_builder.py
```

### Acceptance

M3-8 passes if:

```text
- successful phase can generate SOP candidate
- repeated failure can generate failure pattern
- candidate marks source_code_copied=false
- human review is required before promotion
- candidate can link to skill lifecycle
```

---

## 7.11 M3-9 — End-to-End P2R Demo Projects

### Goal

Prove M3 can run business-oriented projects end to end.

### Demo 1 — AI Novel / Video IP Project

Expected flow:

```text
rough request
→ mission_contract
→ business_contract
→ content_ip_pipeline
→ story/script/video asset plan
→ asset registry
→ compliance notes
→ metrics skeleton
→ strategy update
```

### Demo 2 — Local Automation Service Project

Expected flow:

```text
client request
→ business_contract
→ service_delivery_pipeline
→ quote/timeline
→ task packets
→ mock executor result
→ delivery package
→ CRM follow-up
```

### Demo 3 — Small SaaS / Tool Product Project

Expected flow:

```text
product idea
→ business_contract
→ roadmap
→ MVP task packets
→ release package
→ pricing assumptions
→ analytics skeleton
→ next strategy
```

### CLI

```bash
./agentlab.sh m3-p2r-demo --suite all --out acceptance_runs/m3_p2r_demo
```

### Acceptance

M3 fully passes if:

```text
- all three P2R demos run offline
- each demo has business_contract
- each demo has asset_registry
- each demo has production_pipeline
- each demo has analytics skeleton
- each demo has compliance risk notes
- each demo has delivery or strategy update
- no real platform posting or unsafe automation occurs
```

---

# 8. External Project Placement Across M-Series

| External Project | M1 Placement | M2 Placement | M3 Placement |
|---|---|---|---|
| MinerU | complex document ingestion adapter contract / fixture | parser quality UI and config | contract/report/commercial document assetization |
| MarkItDown | lightweight ingestion fallback | provider toggle/config | content/document asset pipeline |
| Codebase-Memory-MCP | code structural memory provider contract | index status UI/TUI | code asset lineage and repo knowledge reuse |
| Graphify | project knowledge graph provider contract | graph viewer placeholder | asset lineage graph / project graph |
| Supervision | vision evidence normalization contract | visual evidence display | video/content QA assets |
| mattpocock/skills | skill package parser fixture/reference | skill management UI | SOP/skill factory reference |
| Ponytail | minimal patch reviewer | reviewer config toggle | cost-reduction / anti-overengineering gate |
| Agent-Reach | high-risk provider registry only | provider permissions UI | market/channel intelligence provider, gated |
| BabyAGI | trace-to-skill research reference only | no direct execution | SOP/skill factory inspiration, no auto-exec |
| AiToEarn | P2R reference only | demo config reference | content production and channel-operation reference |

---

# 9. Final M-Series Acceptance Definition

AgentLab M-series is complete when all of the following are true.

## 9.1 M1 Final Acceptance

```text
- rough project prompts compile into mission contracts
- project workflows are generated
- project brain is created and persists
- task packets can be sent to local CLI/handoff executors
- mock executor results can be ingested
- phase acceptance decides accept/retry/redesign/split/rollback/ask_user
- context compression prevents long-project memory collapse
- document/code/media ingestion contracts exist
- four generalization demos pass offline
```

## 9.2 M2 Final Acceptance

```text
- runtime hygiene separates profiles/workspaces/bridges/logs/runtime
- local worker registry discovers installed/missing agent CLIs and deterministic tools
- CLI invocation contracts validate real supported command templates
- invalid CLI invocation triggers fallback instead of blocked_user_decision
- cache-aware execution economy creates activation decisions before route decisions
- roles are always checked but workers are lazily activated
- raw tokens, cached tokens, effective cost, and cache confidence are recorded separately
- warm/cached low-risk workers may be activated more aggressively when marginal value is justified
- deterministic tools and cached evidence are preferred before model/API/CLI/MCP calls when sufficient
- capability broker represents AgentLab-owned tools, MCPs, worker-local skills, and worker-local MCPs as provider passports
- all 9 roles have explicit capability requirements
- worker audition and scorecards work with mocked workers
- role activation + assignment router produces explainable activation and route decisions
- configuration is transparent, layered, and connected to routing/economy/brokerage
- cost/risk/approval system gates high-risk workers, high-risk providers, max_quality_swarm, unknown costs, and untrusted cache assumptions
- timeline records project, worker, provider, activation, route, approval, cost, artifact, and acceptance events
- TUI works
- WebUI works
- assistant explains project state, worker routing, activation economy, and provider brokerage
- workers/skills/MCPs/capabilities/executors can be inspected and controlled
- operator demo passes
- CLI remains fully usable without UI
```

## 9.3 M3 Final Acceptance

```text
- business contracts exist
- asset registry and lineage exist
- production pipelines exist
- market/channel brain exists
- analytics and revenue ledger exist
- compliance/risk brain exists
- CRM/client delivery loop exists
- SOP/skill factory produces candidates
- three P2R demos pass offline
```

## 9.4 v1.0 Release Acceptance

```text
- M1/M2/M3 pass
- full pytest passes
- compileall passes
- text integrity passes
- README explains AgentLab as AI Production OS / Project-to-Revenue OS
- docs include install, quickstart, security model, architecture, examples
- no private path leakage
- no unsafe external execution enabled by default
- demo projects can be reproduced by a new user
```

---

# 10. Suggested Execution Prompts

## 10.1 M1 Start Prompt

```markdown
You are working on Kidrage/AgentLab.

Current goal: M1 Project Governance Kernel.

Do not implement M2 WebUI/TUI/cost dashboard.
Do not implement M3 business/revenue/CRM.
Do not execute external projects.
Do not install external skills automatically.

Implement M1-1 through M1-3 first:
- External Project Registry + Capability Mapping
- Mission Compiler v2
- Project Workflow Templates v2

All features must be deterministic, local-first, fixture-tested, approval-safe, and text-integrity safe.

Run:
python -m compileall agent_runtime agentlab_app.py
python -m pytest -q
./agentlab.sh --help
./agentlab.sh run-pipeline --help

Create acceptance_runs/m1_project_governance_kernel/M1_PROJECT_GOVERNANCE_KERNEL_REPORT.md.
```

## 10.2 M2 Start Prompt

```markdown
You are working on Kidrage/AgentLab.

Current goal: M2 Operator OS / Local Agent Company / Cache-Aware Execution Economy.

Assume M1 is complete.
Do not implement M3 business/revenue/CRM.
Do not add unsafe external execution.
Do not auto-run real external agent CLIs in tests.
Do not expose WebUI/OpenClaw/frontdesk gateways publicly by default.
Do not display secrets or private runtime state.
Do not force all workers to install the same skills or MCP servers.
Do not define full_cli as "start all role workers.

Implement M2 in this order:
- M2-0 Runtime Hygiene & Safety Baseline
- M2-1 Local Worker Registry / Agent Doctor
- M2-1.5 CLI Invocation Contract Validator
- M2-1.6 Cache-Aware Execution Economy Engine
- M2-1.7 Skill / MCP Capability Broker
- M2-2 Capability Schema & 9-Role Requirement Matrix
- M2-3 Worker Audition / Performance Ledger
- M2-4 Role Activation + Assignment Router v2
- M2-5 Config Center v2
- M2-6 Cost, Risk & Approval System v2
- M2-7 Observability / Event Timeline v2
- M2-8 Control Panel: Workers / Skills / MCPs / Capabilities / Executors
- M2-9 AgentLab Assistant Modes
- M2-10 TUI skeleton
- M2-11 WebUI skeleton
- M2-12 Operator Acceptance Demo

All UI must be optional. CLI core must work without UI.
All worker discovery, invocation contract validation, provider discovery, and audition tests must be mock-first.
All route decisions must include activation decisions.
All route decisions must be explainable and saved as evidence.
All high-risk workers/capabilities/providers must require explicit approval.

Run:
python -m compileall agent_runtime agentlab_app.py
python -m pytest -q
./agentlab.sh --help
./agentlab.sh worker-scan --help
./agentlab.sh worker-contract-validate --help
./agentlab.sh worker-invocation-probe --help
./agentlab.sh activation-plan --help
./agentlab.sh capability-providers --help
./agentlab.sh assign-role --help
./agentlab.sh route-task --help
python scripts/audit_text_integrity.py
python scripts/check_remote_raw_integrity.py --ref HEAD

Create:
acceptance_runs/m2_operator_demo/M2_OPERATOR_OS_LOCAL_AGENT_COMPANY_REPORT.md
```


## 10.3 M3 Start Prompt

```markdown
You are working on Kidrage/AgentLab.

Current goal: M3 Project-to-Revenue OS.

Assume M1 and M2 are complete.
Do not implement unsafe platform automation.
Do not post to real platforms.
Do not scrape login-walled or paywalled content.
Do not automate payments or legal contracts.
Do not bypass M2 activation economy or provider brokerage.

Implement:
- Business Contract
- Asset Registry + Lineage
- Production Pipeline Templates
- Market / Channel Intelligence
- Analytics + Revenue Ledger
- Compliance / Risk Brain
- CRM / Client Delivery Loop
- SOP / Skill Factory 2.0
- End-to-End P2R Demo Projects

Create acceptance_runs/m3_project_to_revenue/M3_PROJECT_TO_REVENUE_REPORT.md.
```

---


# 11. Required Repository-Level Corrections

These cross-stage cleanup requirements must be completed before claiming M2 is stable.

## 11.1 Rename or Redefine `full_cli`

Problematic meaning:

```text
full_cli = all available roles are started through local CLI agents
```

Required meaning:

```text
full_cli / adaptive_cli = prefer local CLI workers only when activation is justified.
It must not mean all 9 roles spawn workers.
```

Recommended mode names:

```text
adaptive_hybrid       # default
api_governed
external_ide_handoff
frugal_deterministic
max_quality_swarm     # approval required
```

## 11.2 Fix Large Task Routing Semantics

Bad:

```text
large_or_risky_task = all 9 agents
```

Good:

```text
large_or_risky_task =
  all 9 roles are evaluated,
  but workers are lazily activated by Cache-Aware Execution Economy policy,
  and warm/cached low-risk reviewers may be used more aggressively when marginal value is justified.
```

## 11.3 Fix Fake CLI Command Templates

Known bad examples:

```text
hermes --task {task_packet_path}
hermes --task {task_packet_path} --max-quality
hermes --task-packet {task_packet_path}
claude --task {task_packet_path}
```

Required:

```text
- every external CLI command must be backed by a worker invocation contract
- fake/stale templates must fail validation
- invalid invocation must fallback, not block as user decision
```

## 11.4 Treat Agent-Local Skills/MCPs as Opaque Until Proven

Required:

```text
- do not assume Claude/Codex/Hermes/Aider local skills are equivalent
- do not force skill/MCP synchronization across workers
- discover worker-local skills/MCPs only through safe probes or declarations
- represent each provider with a passport
- prefer AgentLab-owned or brokered transparent providers
```

## 11.5 Ensure M3 Uses M2 Instead of Bypassing It

Required:

```text
- production pipeline stages request M2 activation planning before worker execution
- market/channel providers pass M2 capability broker policy
- analytics and revenue ledgers can link back to M2 activation/cost records
- SOP/Skill Factory can promote successful playbooks into AgentLab-owned provider passports
```

---

# 12. One-Line Summary

```text
M1 makes AgentLab able to govern long projects.
M2 makes AgentLab transparent, controllable, cost-aware, and able to manage local agent/tool workers.
M3 makes AgentLab know why it produces, what assets it creates, and how those assets connect to delivery, revenue, learning, and reuse.
```
