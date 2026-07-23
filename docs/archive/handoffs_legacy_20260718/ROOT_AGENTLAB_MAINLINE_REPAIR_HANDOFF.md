# AgentLab S0-S12 Mainline Repair Handoff

## 0. 总目标

AgentLab 的最终目标不是做一个更强的单体 coding agent，而是升级成一个 **local-first 通用任务生产系统**：

> 用户输入一个粗略自然语言需求，AgentLab 能识别任务规模、领域、风险和所需能力；生成任务合同、领域工作流、阶段路线图；调度本地/外部 agent、skills、MCP tools、网页情报、视觉/音频/文档能力；持续验收、恢复、重规划、沉淀技能；最终交付大型长周期任务。

最终应支持：

```text
rough_user_prompt
→ mission_contract
→ domain_workflow_plan
→ skill/capability plan
→ project_roadmap
→ phase task packets
→ executor / skill / tool dispatch
→ artifact ingestion
→ evidence review
→ phase acceptance
→ recovery / replanning
→ project memory update
→ next phase
→ final delivery package
```

---

## 1. 全局工程纪律

所有阶段都必须遵守：

1. 不碰用户本地私密路径、`.venv`、缓存、私有 memory、临时 run 产物，除非任务明确要求。
2. 不引入重型依赖，除非阶段目标明确需要，并且有 fallback。
3. 默认不联网；需要联网的阶段必须 mock-first、policy-first、allowlist-first。
4. 默认不执行外部 skill / hooks / MCP server / shell command；执行前必须经过权限门禁。
5. 所有新增功能必须有：

   * deterministic loader / model；
   * CLI 或 API；
   * docs；
   * tests；
   * acceptance report；
   * text integrity guard。
6. 所有阶段必须跑：

   ```bash
   python -m compileall agent_runtime agentlab_app.py
   python -m pytest -q
   ./agentlab.sh --help
   ./agentlab.sh run-pipeline --help
   ```
7. 重要阶段必须生成：

   ```text
   acceptance_runs/<stage_name>/<STAGE_REPORT>.md
   ```
8. 每轮修复前必须记录：

   ```bash
   git status --short
   git branch --show-current
   git log --oneline -5
   ```
9. 每轮修复后必须确认：

   ```bash
   git status --short
   git log --oneline -5
   git ls-remote --heads origin main
   ```
10. 不允许“测试绿但 raw 文件单行压缩”。GitHub raw / git blob / local file 必须一致为真实多行文本。

---

# S0 — Repository Health + Stable Baseline Re-Acceptance

## 目标

修复并锁死仓库地基，确保 P0/P1/P2 的基础闭环可信。

S0 不做新功能，只修健康状态。

## 要修什么

### S0-A：文本完整性

重点检查：

```text
.github/workflows/*.yml
agentlab.sh
agent_runtime/**/*.py
scripts/**/*.py
tests/**/*.py
config/**/*.yml
docs/**/*.md
README.md
```

需要修：

1. Python / YAML / Markdown 单行压缩。
2. `from __future__ import annotations` 不在首行。
3. YAML 单行嵌套导致不可解析。
4. 超长单行源码。
5. raw GitHub 与 local git blob 不一致。
6. CI workflow 自身损坏。
7. 测试文件自己被压缩，导致守卫无效。

## 怎么修

新增或强化：

```text
scripts/audit_text_integrity.py
scripts/check_remote_raw_integrity.py
tests/test_repository_text_integrity.py
tests/test_remote_raw_integrity_cli.py
```

检查项：

```text
- Python ast.parse
- YAML safe_load
- max line length guard
- min line count guard for key files
- future import physical line guard
- no literal /Users/
- no secrets / tokens
- GitHub raw line count verification
```

## 期望产物

```text
acceptance_runs/s0_repository_health/S0_REPOSITORY_HEALTH_REPORT.md
```

## 验收标准

1. 全仓 compileall 通过。
2. 全 pytest 通过。
3. CI workflow 可解析并实际触发。
4. GitHub raw 关键文件为多行。
5. 文本完整性 audit 0 suspicious。
6. 没有用户本地路径泄露。
7. P0/P1/P2 baseline smoke 全部可运行。

---

# S1 — Mission Compiler / Task Compiler MVP

## 目标

让 AgentLab 先理解用户到底要什么，而不是直接进入执行。

S1 是“大脑入口”。没有 S1，AgentLab 会把写小说、修仓库、做研究、看图片全部粗暴塞进工程 workflow。

## 要修什么

新增：

```text
agent_runtime/brain/
  __init__.py
  mission_contract.py
  task_compiler.py
  domain_classifier.py
  artifact_builder.py
  acceptance_builder.py
  assumption_resolver.py
  risk_classifier.py
  renderer.py
```

新增配置：

```text
config/mission_compiler.yml
config/domain_classifier.yml
config/artifact_contract_defaults.yml
config/acceptance_gate_defaults.yml
```

新增 CLI：

```bash
./agentlab.sh compile-mission --prompt-file examples/prompts/creative_longform.txt --out /tmp/mission_demo
```

## 怎么修

S1-A：定义 `MissionContract` schema。

必须包含：

```yaml
task_id: null
task_type: creative_longform | coding | research | business | audio | multimodal | data | document | ops | unknown
domain: string
user_goal: string
intent_summary: string
non_goals: []
hard_constraints: []
soft_preferences: []
unknowns: []
assumptions: []
required_capabilities: []
required_artifacts: []
acceptance_gates: []
risk_flags: []
recommended_route: string
human_approval_required: bool
```

S1-B：实现 deterministic compiler。

不调用 LLM，先用规则 + keyword + prompt length + artifact hints。

S1-C：实现 domain classifier。

至少识别：

```text
coding
research
creative_longform
business_strategy
product_design
data_analysis
document_processing
multimodal_vision
audio_music
local_ops_automation
education_tutoring
unknown_exploratory
```

S1-D：实现 artifact / acceptance builder。

例如：

```text
creative_longform → story_bible, character_bible, chapter_outline, continuity_ledger
research → source_plan, fact_table, citation_grounded_report
coding → repo_context, patch_plan, tests, acceptance_report
```

S1-E：实现 assumption / risk builder。

例如：

```text
missing_sources
requires_web
requires_vision
requires_user_approval
large_scope
long_running_project
external_execution_required
```

## 期望产物

```text
mission_contract.yml
intent_summary.md
assumptions.yml
required_capabilities.yml
artifact_contracts.yml
acceptance_gates.yml
decision_cards/
docs/S1_MISSION_COMPILER.md
acceptance_runs/s1_mission_compiler/S1_MISSION_COMPILER_REPORT.md
```

## 验收标准

1. 输入小说 prompt，不允许直接写正文，必须生成 creative_longform contract。
2. 输入代码 bug prompt，必须识别 coding/debugging。
3. 输入公司分析 prompt，必须识别 research/business，并要求证据来源。
4. 输入图片任务，必须识别 vision capability gap。
5. 输入音频任务，必须识别 audio_music。
6. 大于 800 字开放需求必须触发 long_project risk。
7. 没有 mission_contract，不允许进入执行层。

---

# S2 — Domain Workflow Templates

## 目标

让 AgentLab 不只知道“用户要什么”，还知道“这个领域的任务应该怎么生产”。

S2 是领域生产方法层。

## 要修什么

新增：

```text
agent_runtime/domain_workflows/
  __init__.py
  models.py
  loader.py
  matcher.py
  planner.py
  renderer.py
```

新增配置：

```text
config/domain_workflow_templates.yml
config/artifact_contract_templates.yml
config/acceptance_gate_templates.yml
```

新增 CLI：

```bash
./agentlab.sh workflow-plan --mission-contract examples/mission_contracts/creative_longform.yml --out /tmp/workflow_demo
```

## 怎么修

S2-A：定义模板 schema。

每个 template 必须包含：

```yaml
template_id:
display_name:
description:
trigger_task_types:
trigger_signals:
required_capabilities:
recommended_agents:
recommended_skills:
phase_plan:
failure_recovery:
human_decision_points:
route_preferences:
risk_notes:
```

S2-B：内置 12 个模板：

```text
coding_software_engineering
research_investigation
creative_longform
business_strategy
product_design
data_analysis
document_processing
multimodal_vision
audio_music
local_ops_automation
education_tutoring
unknown_exploratory
```

S2-C：实现 matcher。

匹配顺序：

```text
mission_contract.task_type
→ mission_contract.domain
→ trigger_task_types
→ trigger_signals
→ unknown_exploratory
```

S2-D：实现 workflow planner。

输入：

```text
mission_contract.yml
domain_workflow_templates.yml
artifact_contract_templates.yml
acceptance_gate_templates.yml
```

输出：

```text
workflow_plan.yml
workflow_plan.md
```

## 期望产物

```text
workflow_plan.yml
workflow_plan.md
docs/S2_DOMAIN_WORKFLOW_TEMPLATES.md
examples/mission_contracts/*.yml
acceptance_runs/s2_domain_workflow_templates/S2_DOMAIN_WORKFLOW_TEMPLATES_REPORT.md
```

## 验收标准

1. 12 个模板可 deterministic load。
2. duplicate template_id 会报错。
3. creative_longform 必须先规划后写作。
4. research 必须包含 source quality / citation grounding。
5. coding 必须包含 tests / audit / rollback。
6. multimodal 缺 vision 时必须生成 capability gap。
7. unknown 不执行，只生成澄清计划。
8. CLI 能生成 YAML + Markdown。
9. S2 不执行任务，不联网，不装 skill，不调用 vision。

---

# S3 — Skill OS Discovery / Source / Package Parser

## 目标

把 Skill 从“已有 registry”升级成真正的 Skill OS：可发现、可解析、可登记、可审查。

## 要修什么

新增或强化：

```text
agent_runtime/skills/
  discovery.py
  source_registry.py
  package_parser.py
  metadata.py
  capability_index.py
  risk.py
  lifecycle.py
```

新增配置：

```text
config/skill_discovery_policy.yml
config/skill_source_registry.yml
config/skill_package_schema.yml
```

## 怎么修

S3-A：Skill Source Registry。

支持来源：

```text
builtin
local_folder
github_raw_allowlisted
github_repo_allowlisted
external_agent_pack
user_uploaded
self_learned_candidate
```

默认：

```yaml
network_enabled: false
auto_install: false
require_human_review: true
```

S3-B：Skill discovery plan。

给定 `mission_contract + workflow_plan`，输出：

```text
skill_search_plan.yml
```

内容：

```yaml
required_capabilities:
candidate_sources:
search_terms:
risk_policy:
approval_required:
```

S3-C：Package parser。

支持：

```text
SKILL.md
skill.yml
manifest.yml
README.md
examples/
tests/
```

必须解析：

```yaml
skill_id:
display_name:
capabilities:
permissions:
dependencies:
risk_level:
source:
license:
entrypoints:
examples:
```

## 期望产物

```text
skill_search_plan.yml
skill_candidates.yml
skill_source_registry.yml
docs/S3_SKILL_OS_DISCOVERY.md
acceptance_runs/s3_skill_os_discovery/S3_SKILL_OS_DISCOVERY_REPORT.md
```

## 验收标准

1. 能根据任务生成 skill_search_plan。
2. 能解析本地 fixture skill package。
3. 未审批 skill 不进入 active。
4. 未知来源 skill 默认 disabled。
5. 所有 skill 必须声明 capability / permission / risk。
6. 不执行 skill 代码。
7. 不自动下载未知 repo。
8. 不复制第三方源码。

---

# S4 — Skill Trust / Permission / Sandbox / Promotion

## 目标

让 skill 可安装、可信任、可验证、可晋升、可降权。

## 要修什么

新增：

```text
agent_runtime/skills/
  trust_scanner.py
  permission_manifest.py
  sandbox_runner.py
  validation.py
  promotion.py
  conflict_resolver.py
  roi.py
  retirement.py
```

新增配置：

```text
config/skill_trust_policy.yml
config/skill_permission_policy.yml
config/skill_sandbox_policy.yml
config/skill_promotion_policy.yml
```

## 怎么修

S4-A：权限声明。

每个 skill 必须声明：

```yaml
permissions:
  filesystem_read: []
  filesystem_write: []
  shell: false
  network: false
  env: false
  secrets: false
  external_tools: []
```

S4-B：Trust scanner。

检查：

```text
- suspicious shell commands
- network calls
- env var access
- secret patterns
- file deletion
- path traversal
- prompt injection instructions
- hidden binary files
- license unknown
```

S4-C：Sandbox validation。

先做 mock sandbox，不需要真实容器。

输出：

```text
skill_validation_report.yml
```

S4-D：Promotion lifecycle。

状态：

```text
discovered
→ pending_user_approval
→ approved
→ staging
→ validated
→ active
→ degraded
→ retired
```

## 期望产物

```text
skill_validation_report.yml
skill_promotion_report.yml
skill_conflict_report.yml
docs/S4_SKILL_TRUST_AND_PROMOTION.md
acceptance_runs/s4_skill_trust/S4_SKILL_TRUST_REPORT.md
```

## 验收标准

1. 未声明权限的 skill 不可 active。
2. 高风险权限必须人工批准。
3. license unknown 必须 review。
4. suspicious skill 必须 blocked。
5. staging skill 可验证但不可自动注入生产任务。
6. active skill 必须有测试证据。
7. 多次失败的 skill 自动降权或建议 retire。

---

# S5 — Native Web Intelligence + Local Knowledge Index

## 目标

让 AgentLab 具备自己的有限网页情报能力和本地知识搜索能力，不完全依赖 AnySearch。

## 要修什么

新增：

```text
agent_runtime/intelligence/
  web_policy.py
  web_fetcher.py
  web_cache.py
  source_extractor.py
  source_ranker.py
  research_planner.py
  research_brief.py
  citation_ledger.py

agent_runtime/local_search/
  fts_index.py
  bm25_index.py
  query.py
  rebuild.py
  evidence.py
```

新增配置：

```text
config/web_intelligence.yml
config/source_quality_policy.yml
config/local_search.yml
```

新增 CLI：

```bash
./agentlab.sh web-research-plan --mission-contract ...
./agentlab.sh local-search-index --project AgentLab
./agentlab.sh local-search-query --query "recovery policy"
```

## 怎么修

S5-A：Web policy。

默认禁止：

```text
localhost
private IP
file://
login wall
paywall bypass
large binary download
script execution
unbounded crawling
```

S5-B：Research planner。

输入 mission/workflow，输出：

```text
research_plan.yml
```

S5-C：Native fetcher。

先做安全的 mock / fixture fetcher，再加可选真实 fetch。

S5-D：Source extractor。

支持：

```text
HTML
Markdown
plain text
PDF placeholder extraction contract
```

S5-E：Citation ledger。

每条来源记录：

```yaml
url:
fetched_at:
content_hash:
extract_path:
source_quality:
freshness:
used_in:
```

S5-F：Local index。

索引：

```text
docs
configs
skills
task histories
recovery histories
acceptance reports
web snapshots
project_brain
```

## 期望产物

```text
research_plan.yml
research_brief.md
citation_ledger.yml
local_search_index/
docs/S5_NATIVE_WEB_INTELLIGENCE.md
docs/S5_LOCAL_SEARCH.md
acceptance_runs/s5_web_intelligence/S5_WEB_INTELLIGENCE_REPORT.md
```

## 验收标准

1. research task 能生成 research_plan。
2. 所有来源必须进入 citation ledger。
3. 没有来源不得生成事实性结论。
4. 禁止 private URL / localhost / file URL。
5. 不绕登录墙和 paywall。
6. local-search 能检索 docs / reports / skills。
7. AnySearch 只是 provider，不是唯一依赖。

---

# S6 — Recovery Brain / Alternative Route Planner

## 目标

让 AgentLab 失败后不只是 retry，而是能诊断失败类型、寻找替代路径、请求权限、换路线继续。

## 要修什么

新增：

```text
agent_runtime/recovery/
  failure_taxonomy.py
  strategy_search.py
  alternative_route_planner.py
  capability_gap_resolver.py
  escalation_policy.py
  fake_evidence_detector.py
```

新增配置：

```text
config/recovery_strategy_policy.yml
config/failure_taxonomy.yml
config/evidence_integrity_policy.yml
```

## 怎么修

S6-A：扩展 failure taxonomy。

至少包括：

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
```

S6-B：Alternative route planner。

每种失败生成 next action：

```text
retry_same
retry_with_stronger_model
decompose_smaller
search_skill
install_capability
switch_external_agent
fallback_manual_template
ask_user
stop_safely
```

S6-C：Capability gap resolver。

当 mission 需要 web / vision / audio / shell / external executor 但能力不存在时，生成 decision card。

S6-D：Fake evidence hard fail。

Researcher 不能伪造搜索，Verifier 不能接受无 evidence 的事实结论。

## 期望产物

```text
recovery_strategy_plan.yml
alternative_route_plan.yml
capability_gap_decision_card.yml
fake_evidence_report.yml
docs/S6_RECOVERY_BRAIN.md
acceptance_runs/s6_recovery_brain/S6_RECOVERY_BRAIN_REPORT.md
```

## 验收标准

1. evidence_missing 必须 fail，不允许通过。
2. skill_missing 能建议 skill discovery。
3. vision_missing 能建议 capability install / user upload。
4. provider_failed 能切换 provider 或停下。
5. budget_exceeded 能降级路线。
6. 每个 recovery plan 必须写入 ledger。
7. 不允许无限 retry。

---

# S7 — Long Project Orchestrator + Project Brain

## 目标

让 AgentLab 能管理长周期大型项目，例如“写一部长篇小说”“建设一个仓库”“做一个产品原型”。

S7 是长任务记忆不崩塌的关键阶段。

## 要修什么

新增：

```text
agent_runtime/program_manager/
  __init__.py
  project_goal.py
  project_brief.py
  roadmap.py
  milestone.py
  task_graph.py
  phase_planner.py
  acceptance_contract.py
  phase_acceptance.py
  replanner.py
  delivery_manager.py
  context_compressor.py
  project_brain.py
```

新增目录规范：

```text
projects/<project>/project_brain/
  product_vision.md
  project_brief.yml
  roadmap.yml
  milestone_graph.yml
  decision_log.yml
  acceptance_history.yml
  unresolved_questions.yml
  known_risks.yml
  architecture_state.yml
  next_actions.yml
  phase_summaries/
  snapshots/
```

新增 CLI：

```bash
./agentlab.sh project-init --mission-contract ... --project NovelDemo
./agentlab.sh project-plan --project NovelDemo
./agentlab.sh project-status --project NovelDemo
./agentlab.sh project-next --project NovelDemo
```

## 怎么修

S7-A：Project init。

从 mission_contract + workflow_plan 生成：

```text
project_brief.yml
product_vision.md
roadmap.yml
```

S7-B：Milestone graph。

把项目拆成：

```text
milestone
→ phase
→ task_packet
```

S7-C：Phase planner。

每个 phase 必须有：

```yaml
phase_id:
goal:
scope:
inputs:
outputs:
acceptance_criteria:
required_capabilities:
recommended_skills:
risk_flags:
human_decision_points:
```

S7-D：Project Brain。

每轮结束更新：

```text
decision_log
acceptance_history
known_risks
unresolved_questions
architecture_state
next_actions
```

S7-E：Context compressor。

每轮生成 phase summary；每 3-5 轮生成 snapshot。

S7-F：Longform creative support。

针对小说类任务必须支持：

```text
story_constitution
world_bible
character_bible
chapter_outline
scene_cards
continuity_ledger
style_guide
revision_history
```

## 期望产物

```text
projects/<project>/project_brain/*
project_status.yml
phase_plan.yml
next_actions.yml
docs/S7_LONG_PROJECT_ORCHESTRATOR.md
acceptance_runs/s7_long_project_orchestrator/S7_LONG_PROJECT_ORCHESTRATOR_REPORT.md
```

## 验收标准

1. 粗略长篇小说 prompt 能变成 project roadmap。
2. 大型工程 prompt 能拆 milestone。
3. 每个 phase 有 acceptance criteria。
4. 每轮结束写 phase_summary。
5. project_brain 可恢复上下文。
6. 不把全部历史原文塞给模型。
7. `project-next` 能基于上一轮验收生成下一步。
8. S7 不要求真实执行，只要求长期规划和记忆闭环。

---

# S8 — Executor / Coding Agent Connector Loop

## 目标

让 AgentLab 能把任务包交给本地或外部执行者，收回结果，验收，再推进下一轮。

注意：虽然名字里有 coding agent，但协议必须泛化给 writing agent、research agent、audio agent、human contractor。

## 要修什么

新增：

```text
agent_runtime/executors/
  connector_contract.py
  task_packet.py
  result_ingestion.py
  diff_inspector.py
  evidence_collector.py
  executor_ledger.py
  local_shell_connector.py
  codex_connector.py
  cline_connector.py
  generic_handoff_connector.py
```

新增配置：

```text
config/executor_connectors.yml
config/executor_permission_policy.yml
```

新增 CLI：

```bash
./agentlab.sh executor-task-create --project ... --phase ...
./agentlab.sh executor-result-ingest --project ... --result-dir ...
./agentlab.sh executor-review --project ... --phase ...
```

## 怎么修

S8-A：Task packet schema。

```yaml
task_packet:
  project:
  phase_id:
  executor_type:
  objective:
  allowed_files:
  forbidden_files:
  required_outputs:
  acceptance_criteria:
  commands_allowed:
  evidence_required:
  rollback_required:
```

S8-B：Connector contract。

支持：

```text
local_shell
codex
cline
claude_code
deepseek_coder
human_contractor
generic_patch_submitter
creative_writer
researcher
```

S8-C：Result ingestion。

接收：

```text
patch/diff
changed files report
test output
artifact folder
executor summary
open issues
```

S8-D：Evidence collector。

所有结果必须进入：

```text
executor_result_ledger.yml
phase_evidence/
```

S8-E：Phase acceptance hook。

执行结果必须经过 S7 phase_acceptance，不可直接 close。

## 期望产物

```text
task_packet.yml
executor_result_ledger.yml
phase_evidence/
executor_review.md
docs/S8_EXECUTOR_CONNECTOR_LOOP.md
acceptance_runs/s8_executor_connector/S8_EXECUTOR_CONNECTOR_REPORT.md
```

## 验收标准

1. 能生成 executor task packet。
2. 能 ingest mock result。
3. 能读取 diff / artifacts / test output。
4. 能调用 phase acceptance。
5. connector 不可绕过 cost/resource/artifact/evidence/recovery policy。
6. 未授权 executor 不可执行。
7. 不真实调用 Codex/Cline，先 mock / handoff。

---

# S9 — Capability Fabric + Multimodal / Media Artifact Perception

## 目标

把本地工具、多模态、文件、文档、视觉、音频、视频等能力统一成 capability fabric。

S9 是“AgentLab 有眼睛、有耳朵、有手”的阶段，但仍然必须受权限门禁控制。

## 要修什么

新增：

```text
agent_runtime/capabilities/
  __init__.py
  registry.py
  capability_contract.py
  permission_gate.py
  sandbox_policy.py
  mcp_adapter.py
  local_tool_adapter.py
  result_verifier.py
  media_artifact.py
  vision_contract.py
  audio_contract.py
  document_contract.py
```

新增配置：

```text
config/capability_registry.yml
config/capability_permission_policy.yml
config/media_artifact_policy.yml
```

## 怎么修

S9-A：Capability registry。

首批能力：

```text
filesystem_read
filesystem_write
shell_command
git_ops
web_search
browser_fetch
pdf_read
docx_read
spreadsheet_read
image_understanding
ocr
video_understanding
audio_transcription
audio_analysis
database_query
github_ops
ide_handoff
openclaw_notify
```

S9-B：Vision contract。

统一输出：

```yaml
vision_result:
  input_artifact:
  modality:
  observations:
  summary:
  evidence_artifacts:
  model_or_tool:
  risk:
```

S9-C：Audio contract。

统一输出：

```yaml
audio_result:
  input_artifact:
  duration:
  observations:
  transcript:
  features:
  summary:
  evidence_artifacts:
  model_or_tool:
  risk:
```

S9-D：Document contract。

统一输出：

```yaml
document_result:
  input_artifact:
  pages:
  extracted_text:
  tables:
  figures:
  citations:
  confidence:
```

S9-E：Capability gap decision card。

如果任务需要能力但 registry 没有 active backend，输出：

```text
capability_gap_decision_card.yml
```

## 期望产物

```text
capability_registry.yml
capability_result.yml
vision_result.yml
audio_result.yml
document_result.yml
capability_gap_decision_card.yml
docs/S9_CAPABILITY_FABRIC.md
docs/S9_VISION_AUDIO_DOCUMENT_CONTRACTS.md
acceptance_runs/s9_capability_fabric/S9_CAPABILITY_FABRIC_REPORT.md
```

## 验收标准

1. Mission Compiler 能识别 capability needs。
2. Capability registry 能查询、启用、禁用。
3. 无 backend 时必须生成 gap card。
4. 有 backend 时也必须记录权限和 evidence。
5. 图像/音频/视频/文档结果必须保存 artifact，不只写聊天文本。
6. 不自动安装模型。
7. 不自动执行外部 MCP。
8. 所有 multimodal 输出必须标注置信度和 human review 风险。

---

# S10 — Generalization Eval Suite + CI Gates

## 目标

证明 AgentLab 不是只会修自己的仓库，而是能泛化到多领域任务。

## 要修什么

新增：

```text
eval_tasks/
  coding/
  research/
  creative/
  multimodal/
  business/
  document/
  audio/
  ops/
```

新增：

```text
agent_runtime/evaluation/
  eval_task.py
  eval_runner.py
  metrics.py
  report.py
  fixtures.py
```

新增配置：

```text
config/generalization_eval.yml
```

新增 CLI：

```bash
./agentlab.sh eval-generalization --suite offline
./agentlab.sh eval-generalization --task creative/novel_blueprint.yml
```

## 怎么修

S10-A：任务集。

每类至少 5-10 个 offline fixture：

```text
creative: 长篇小说蓝图、章节卡、连续性审查
research: 公司调研、事实表、来源质量
coding: bug定位、patch plan、测试解释
document: PDF 摘要、表格提取计划
multimodal: 图片任务 capability gap
audio: 音频分析计划
ops: 本地文件整理 dry-run
business: 市场策略分析
```

S10-B：指标。

```text
mission_contract_pass_rate
domain_classification_accuracy
workflow_plan_completeness
artifact_contract_completeness
skill_match_precision
capability_gap_detection
fake_evidence_detection_rate
phase_acceptance_quality
recovery_success_rate
context_compression_quality
```

S10-C：CI gates。

新增 CI job：

```text
offline_generalization_eval
text_integrity
mission_contract_schema
workflow_template_integrity
skill_safety
capability_policy
```

## 期望产物

```text
generalization_eval_report.md
generalization_eval_metrics.yml
docs/S10_GENERALIZATION_EVAL.md
acceptance_runs/s10_generalization_eval/S10_GENERALIZATION_EVAL_REPORT.md
```

## 验收标准

1. creative/research/coding/document/multimodal/audio 至少各有一个通过 fixture。
2. fake evidence 必须 fail。
3. unknown task 不执行。
4. capability gap 能正确识别。
5. long project task 能触发 S7。
6. eval 可在 offline 环境运行。
7. CI 可选执行 smoke eval。

---

# S11 — Dashboard / Ops Console

## 目标

让用户可视化管理 AgentLab：项目、阶段、skills、capabilities、风险、预算、验收、恢复、产物。

S11 不是炫 UI，而是降低长期项目管理成本。

## 要修什么

新增：

```text
agentlab_app/
  dashboard/
    app.py
    views/
    components/
    api.py

agent_runtime/ops_console/
  status_api.py
  project_api.py
  skill_api.py
  capability_api.py
  evidence_api.py
```

或使用现有 app 结构，避免重构过大。

## 怎么修

S11-A：只读 dashboard MVP。

页面：

```text
Project Overview
Project Brain
Roadmap / Milestones
Phase Status
Task Packets
Skill Registry
Capability Registry
Recovery / Failures
Evidence Artifacts
Budget / Resource Ledger
```

S11-B：审批入口。

支持：

```text
approve skill
reject skill
approve capability
approve executor handoff
approve phase close
request replanning
```

S11-C：安全。

Dashboard 默认本地运行：

```text
127.0.0.1 only
no public bind by default
no secrets display
path redaction
read-only unless explicit action
```

## 期望产物

```text
docs/S11_OPS_CONSOLE.md
acceptance_runs/s11_dashboard/S11_DASHBOARD_REPORT.md
```

## 验收标准

1. 能查看 project status。
2. 能查看 skills / capabilities。
3. 能查看 phase acceptance。
4. 能查看 evidence links。
5. 能 approve/reject decision card。
6. 不暴露 secrets。
7. 默认只绑定本地。
8. UI 失败不影响 CLI 核心。

---

# S12 — Productization / Service Factory / Release Hardening

## 目标

把 AgentLab 从“研究型本地工具”打包成可交付、可复用、可演示、可开源吸引用户的 v1 系统。

S12 是最后的产品化阶段，也是 AI 自动化服务工厂的雏形。

## 要修什么

新增或整理：

```text
docs/
  GETTING_STARTED.md
  INSTALL.md
  QUICKSTART.md
  ARCHITECTURE.md
  SECURITY_MODEL.md
  SERVICE_FACTORY_MODEL.md
  ROADMAP.md
  EXAMPLES.md

examples/
  novel_project/
  repo_repair_project/
  company_research_project/
  document_processing_project/
  multimodal_capability_gap_project/

templates/
  service_catalog/
  quote_templates/
  delivery_templates/
  acceptance_templates/
```

新增：

```text
agent_runtime/service_factory/
  service_catalog.py
  quote_estimator.py
  timeline_estimator.py
  delivery_package.py
  quality_rubric.py
```

## 怎么修

S12-A：Service catalog。

定义可售卖/可交付服务类型：

```text
repo_cleanup
bug_fix_plan
longform_novel_blueprint
company_research_report
document_summary
spreadsheet_cleanup
local_file_organization
audio_analysis_plan
multimodal_review
personal_automation_workflow
```

每个服务包含：

```yaml
service_id:
description:
required_capabilities:
default_workflow_template:
estimated_phases:
quality_rubric:
deliverables:
human_approval_points:
risk_notes:
```

S12-B：Quote estimator。

根据：

```text
mission complexity
required capabilities
estimated phases
external execution needed
human approval count
risk level
```

输出：

```text
quote_estimate.yml
timeline_estimate.yml
```

S12-C：Delivery package。

每个项目最终生成：

```text
delivery/
  final_summary.md
  artifacts/
  evidence/
  acceptance_history.md
  risks_and_limitations.md
  reproduction_commands.md
  next_steps.md
```

S12-D：Release hardening。

补齐：

```text
install smoke
first-run wizard
example tasks
README 中英文同步
security policy
contribution guide
demo scripts
version tag
```

S12-E：Public demo。

至少准备 3 个完整 demo：

```text
1. coding repo repair demo
2. creative longform planning demo
3. research report with citation/evidence demo
```

## 期望产物

```text
service_catalog.yml
quote_estimate.yml
timeline_estimate.yml
delivery_package/
docs/S12_PRODUCTIZATION.md
docs/SERVICE_FACTORY_MODEL.md
acceptance_runs/s12_productization/S12_PRODUCTIZATION_REPORT.md
```

## 验收标准

1. 新用户能按 QUICKSTART 跑通一个 demo。
2. README 中英文一致。
3. docs 能解释 AgentLab 和 Claude Code / Codex / OpenClaw / MCP 的关系。
4. service catalog 能生成报价/周期估算。
5. delivery package 可复现、可验收。
6. 所有示例不含私密路径。
7. v1 tag 可发布。
8. CI 绿。
9. GitHub 页面能让陌生人理解：AgentLab 是通用稳定的任务生产系统，具备长项目自治的能力，不只是 coding agent wrapper。

---

# 阶段依赖关系

```text
S0 地基健康
↓
S1 Mission Compiler
↓
S2 Domain Workflow Templates
↓
S3 Skill Discovery / Parser
↓
S4 Skill Trust / Promotion
↓
S5 Web + Local Knowledge
↓
S6 Recovery Brain
↓
S7 Long Project Orchestrator
↓
S8 Executor Connector Loop
↓
S9 Capability Fabric / Multimodal
↓
S10 Generalization Eval
↓
S11 Dashboard / Ops Console
↓
S12 Productization / Service Factory
```

---

# 每阶段交付报告统一格式

每一阶段都必须提交：

```markdown
# AgentLab <Stage> Report

## Verdict
PASS / FAIL

## Baseline
- branch:
- before commit:
- after commit:
- remote:
- CI:

## Summary
本阶段完成了什么。

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
粘贴命令和结果。

## Safety Notes
确认没有越界行为。

## Known Limitations
哪些功能留到后续阶段。

## Next Recommended Stage
下一阶段是什么，为什么。
```

---

# 最终完成定义

AgentLab S0-S12 全主线完成后，必须能通过以下端到端场景：

## 场景 1：长篇小说

输入：

```text
帮我写一部长篇赛博朋克小说，风格偏黑色幽默，20万字左右。
```

系统应输出：

```text
mission_contract
creative_longform workflow
project roadmap
story bible
character bible
chapter outline
phase plan
scene cards
continuity ledger
draft/revision loop
final delivery package
```

不得直接一口气生成正文。

## 场景 2：仓库修复

输入：

```text
检查这个 repo，修复 CI、README、测试和目录结构问题。
```

系统应输出：

```text
mission_contract
coding workflow
repo context
patch task packet
executor handoff
result ingestion
test evidence
phase acceptance
next phase plan
delivery package
```

## 场景 3：公司调研

输入：

```text
分析某公司是否值得加入。
```

系统应输出：

```text
research workflow
source plan
citation ledger
fact table
uncertainty review
recommendation
```

无来源不得编造结论。

## 场景 4：图片/视频/音频任务

输入：

```text
看这张图 / 这段视频 / 这段音频，帮我分析。
```

系统应：

```text
识别 capability need
检查 capability registry
如果缺能力，生成 decision card
如果有能力，生成 structured evidence artifact
进入 workflow plan
```

## 场景 5：服务工厂

输入：

```text
客户想做一个本地文件整理助手，给报价、周期和交付方案。
```

系统应输出：

```text
service catalog match
quote estimate
timeline estimate
capability plan
risk notes
delivery contract
```

---

# 一句话版本

S0-S2 修脑子入口：先健康、再理解需求、再知道各领域怎么生产。
S3-S4 修技能系统：让能力可发现、可验证、可安装、可退役。
S5-S6 修视野和恢复：能找证据，失败能换路线。
S7-S8 修长期项目闭环：能长期规划、派活、验收、重规划。
S9 修感官和工具统一：能读图、读文档、听音频、接 MCP。
S10 修泛化评测：证明不是只会修自己。
S11-S12 修产品化：让它可视化、可交付、可演示、可开源传播。

最终 AgentLab 应该成为：

> 一个能把粗略自然语言需求变成可执行、可验收、可恢复、可沉淀、可交付的长期任务生产系统。


现在 AgentLab 已完成：

本地搜索：local-search-index / local-search-query，能从 repo/docs/reports 中找证据并记录 hash/line refs。
仓库治理：repo hygiene、text integrity audit、root artifact 规则、CI raw integrity 检查。
成本观测：轻量 cost observability 和 cost doctor。
项目运维：project routing/init/status、task compaction、mainline docs/acceptance reports。
S1：把粗略需求编译成 mission/task contract，并标注任务大小、风险、预算模式、失败策略。
S2：按领域生成 workflow plan，包含 route controls、recovery boundaries、approval-first/mock-first 策略。
S3：生成 skill search plan，能基于任务能力需求规划候选 skill 来源，但默认不联网、不安装、不执行。
S4：对 skill package 做 metadata-only trust scan、权限校验、mock sandbox、promotion eligibility 判断。
S5：生成 evidence/recovery-aware intelligence artifacts：研究计划、来源计划、证据账本、恢复包、阶段验收证据。

应当时刻验证一下这些能力是否真实达成/稳定/可真实任务验证，以及未来的修改不会轻易破坏这个系统。