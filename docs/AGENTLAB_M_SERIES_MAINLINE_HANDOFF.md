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

v0.8 Operator OS
  M2 completed. AgentLab is transparent, configurable, observable, and cost-controlled.

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
- literal `/Users/...` private paths.
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
M2 Operator OS / Transparent Control Plane
  M2-1 Config Center
  M2-2 Cost System v2
  M2-3 Event Timeline / Observability
  M2-4 TUI
  M2-5 WebUI
  M2-6 AgentLab Assistant Modes
  M2-7 Skill / Capability / Executor Control Panel
  M2-8 Operator Acceptance Demo
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

# 6. M2 — Operator OS / Transparent Control Plane

## 6.1 M2 Objective

M2 makes AgentLab easy to control.

The user should be able to see:

```text
what AgentLab is doing
why it is doing it
what it costs
what is blocked
what needs approval
which agent/tool/skill is involved
what evidence exists
what changed
what happens next
```

M2 is about transparency and operator control.

## 6.2 M2 Non-Goals

Do not implement in M2:

```text
- real commercial revenue loop
- platform posting
- CRM
- payment
- advanced business strategy
- real social scraping
- unsafe automation
```

M2 may show placeholders for future business/ROI fields, but must not make them core.

---

## 6.3 M2-1 — Config Center

### Goal

Make configuration transparent, inspectable, validated, and override-aware.

### Add Modules

```text
agent_runtime/config_center/
  __init__.py
  schema.py
  loader.py
  validator.py
  resolver.py
  diff.py
  profile.py
  renderer.py
```

### Add Configs

```text
config/config_center.yml
config/config_ui_schema.yml
config/config_profiles.yml
```

### Config Layers

```text
global defaults
environment profile
project override
executor override
skill override
capability override
user approval override
runtime temporary override
```

### CLI

```bash
./agentlab.sh config-list
./agentlab.sh config-get --key cost.budget_policy.project_soft_limit_usd
./agentlab.sh config-diff --project DemoProject
./agentlab.sh config-validate
```

### Tests

```text
tests/test_m2_config_center.py
tests/test_m2_config_resolution.py
tests/test_m2_config_cli.py
```

### Acceptance

M2-1 passes if:

```text
- config values show source layer
- invalid config fails cleanly
- project override works
- config diff works
- no secret values are displayed raw
```

---

## 6.4 M2-2 — Cost System v2

### Goal

Replace weak cost tracking with budget, prediction, attribution, alerts, and efficiency review.

### Add Modules

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
  renderer.py
```

### Add Configs

```text
config/cost_policy_v2.yml
config/model_cost_profiles.yml
config/executor_cost_profiles.yml
```

### Data Layout

```text
projects/<project_id>/cost/
  project_budget.yml
  phase_budget.yml
  spend_ledger.yml
  model_usage_ledger.yml
  executor_cost_ledger.yml
  cost_alerts.yml
  cost_efficiency_report.md
```

### Budget Policy Example

```yaml
budget_policy:
  project_soft_limit_usd: 5.00
  project_hard_limit_usd: 10.00
  phase_soft_limit_usd: 1.00
  require_approval_above_usd: 0.50
  cheap_model_first: true
  escalate_model_on_failure: true
  max_retries_before_escalation: 1
  stop_on_unbounded_loop: true
  unknown_external_cli_cost_policy: approval_required
```

### Cost Attribution Dimensions

```text
project
phase
task
executor
model
skill
capability
artifact
recovery_attempt
```

### CLI

```bash
./agentlab.sh cost-status --project DemoProject
./agentlab.sh cost-estimate --project DemoProject --phase phase_001
./agentlab.sh cost-alerts --project DemoProject
./agentlab.sh cost-efficiency-review --project DemoProject
```

### Tests

```text
tests/test_m2_cost_policy.py
tests/test_m2_cost_estimator.py
tests/test_m2_spend_ledger.py
tests/test_m2_cost_alerts.py
tests/test_m2_cost_attribution.py
```

### Acceptance

M2-2 passes if:

```text
- budget can be set per project and phase
- estimated cost is generated before task packet
- spend ledger records model/executor/skill/capability attribution
- hard limit blocks execution
- soft limit creates approval decision card
- unknown external CLI cost requires approval
- efficiency review compares cost across phases/tasks
```

---

## 6.5 M2-3 — Event Timeline / Observability

### Goal

Create a unified event timeline.

### Add Modules

```text
agent_runtime/observability/
  event.py
  event_log.py
  timeline.py
  query.py
  renderer.py
  log_redaction.py
```

### Data Layout

```text
projects/<project_id>/observability/
  timeline.jsonl
  event_log.jsonl
  warnings.yml
  executor_runs.yml
  artifact_events.yml
  cost_events.yml
  decision_events.yml
```

### Event Schema

```yaml
event:
  event_id:
  timestamp:
  project_id:
  phase_id:
  task_id:
  event_type:
  actor:
  summary:
  references:
  cost_delta:
  severity:
  redacted:
```

### CLI

```bash
./agentlab.sh timeline --project DemoProject
./agentlab.sh timeline --project DemoProject --event-type cost
./agentlab.sh event-log-tail --project DemoProject
```

### Tests

```text
tests/test_m2_event_log.py
tests/test_m2_timeline_query.py
tests/test_m2_log_redaction.py
```

### Acceptance

M2-3 passes if:

```text
- key actions emit events
- timeline can be queried
- events link to artifacts/evidence/cost/decision cards
- logs redact secrets and private paths
- timeline is append-only
```

---

## 6.6 M2-4 — TUI

### Goal

Build a terminal control surface for project operations.

### Add Modules

```text
agentlab_tui/
  __init__.py
  app.py
  screens/
  widgets/
  commands.py
```

Or place under existing app structure if preferred.

### TUI Screens

```text
Project List
Project Overview
Current Phase
Task Packets
Executor Results
Evidence
Cost Dashboard
Decision Cards
Skills
Capabilities
Config
Logs / Timeline
```

### Required Actions

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
```

### CLI

```bash
./agentlab.sh tui
```

### Tests

Use lightweight tests only:

```text
tests/test_m2_tui_routes.py
tests/test_m2_tui_command_handlers.py
```

### Acceptance

M2-4 passes if:

```text
- TUI can start locally
- project list loads
- project status view works
- decision card approve/reject calls backend APIs
- cost status visible
- TUI failure does not break CLI core
```

---

## 6.7 M2-5 — WebUI

### Goal

Build a local WebUI dashboard.

### Add Modules

```text
agentlab_app/dashboard/
  app.py
  routes.py
  api.py
  templates/
  static/
```

Or use existing app structure.

### Pages

```text
/dashboard
/projects
/project/<id>
/project/<id>/timeline
/project/<id>/costs
/project/<id>/phases
/project/<id>/artifacts
/tasks
/skills
/capabilities
/executors
/settings
/recovery
```

### Security

```text
- bind to 127.0.0.1 by default
- no public bind unless explicit config
- no secrets display
- path redaction
- mutating actions require CSRF or local action token if applicable
- read-only mode available
```

### CLI

```bash
./agentlab.sh webui --host 127.0.0.1 --port 8765
```

### Tests

```text
tests/test_m2_webui_routes.py
tests/test_m2_webui_security.py
tests/test_m2_webui_api.py
```

### Acceptance

M2-5 passes if:

```text
- WebUI starts locally
- project overview loads
- timeline/cost/phase/artifact pages work
- decision actions can be approved/rejected
- WebUI does not expose secrets
- WebUI can be disabled
```

---

## 6.8 M2-6 — AgentLab Assistant Modes

### Goal

Give AgentLab a self-explanation and operation assistant layer.

This should not become a free-form uncontrolled chat agent. It should be grounded in system state.

### Add Modules

```text
agent_runtime/assistant/
  modes.py
  state_reader.py
  response_planner.py
  explanations.py
  command_suggestions.py
```

### Modes

```text
operator mode
  Help user operate AgentLab.

planner mode
  Explain roadmap, phase status, next action.

reviewer mode
  Explain acceptance verdict, evidence, risks.

teacher mode
  Explain why the system made a decision.
```

### CLI

```bash
./agentlab.sh ask --project DemoProject "为什么这个项目被 blocked？"
./agentlab.sh explain-phase --project DemoProject --phase phase_001
./agentlab.sh explain-cost --project DemoProject
```

### Tests

```text
tests/test_m2_assistant_modes.py
tests/test_m2_assistant_state_grounding.py
```

### Acceptance

M2-6 passes if:

```text
- assistant answers using project state
- assistant cites local artifact paths/state references
- assistant does not hallucinate unavailable facts
- assistant can explain cost, phase acceptance, executor result, decision card
```

---

## 6.9 M2-7 — Skill / Capability / Executor Control Panel

### Goal

Unify management of skills, capabilities, and executors.

### Add Modules

```text
agent_runtime/control_panel/
  skill_control.py
  capability_control.py
  executor_control.py
  approval_actions.py
  status_summary.py
```

### Features

```text
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

### CLI

```bash
./agentlab.sh control skills
./agentlab.sh control capabilities
./agentlab.sh control executors
./agentlab.sh control approve --decision-card <id>
```

### Tests

```text
tests/test_m2_control_panel_skills.py
tests/test_m2_control_panel_capabilities.py
tests/test_m2_control_panel_executors.py
```

### Acceptance

M2-7 passes if:

```text
- operator can inspect skills/capabilities/executors
- mutating actions require explicit approval
- risky entities show warnings
- disabled entities cannot execute
```

---

## 6.10 M2-8 — Operator Acceptance Demo

### Goal

Prove M2 works as an operator control plane.

### Demo

```text
1. create demo project
2. generate task packet
3. estimate cost
4. show in TUI
5. show in WebUI
6. ingest mock executor result
7. generate phase acceptance
8. view timeline
9. approve/retry decision
10. show cost report
```

### CLI

```bash
./agentlab.sh m2-operator-demo --out acceptance_runs/m2_operator_demo
```

### Acceptance

M2 fully passes if:

```text
- WebUI/TUI can inspect same project
- config center works
- cost v2 works
- timeline records key events
- assistant can explain project state
- user can approve/reject/retry from UI/TUI/CLI
- core CLI works without UI
```

---

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
- configuration is transparent and layered
- cost system v2 estimates, tracks, alerts, attributes, and reviews spend
- timeline records project events
- TUI works
- WebUI works
- assistant explains project state
- skills/capabilities/executors can be inspected and controlled
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

Current goal: M2 Operator OS / Transparent Control Plane.

Assume M1 is complete.
Do not implement M3 business/revenue/CRM.
Do not add unsafe external execution.

Implement:
- Config Center
- Cost System v2
- Event Timeline / Observability
- TUI skeleton
- WebUI skeleton
- AgentLab Assistant Modes
- Skill/Capability/Executor Control Panel

All UI must be optional. CLI core must work without UI.

Create acceptance_runs/m2_operator_os/M2_OPERATOR_OS_REPORT.md.
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

# 11. One-Line Summary

```text
M1 makes AgentLab able to govern long projects.
M2 makes AgentLab transparent, controllable, and cost-aware.
M3 makes AgentLab know why it produces, what assets it creates, and how those assets connect to delivery, revenue, learning, and reuse.
```
