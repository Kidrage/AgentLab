# AgentLab Agent Map

This file is a compact navigation map for agents working in this repository.
Keep detailed policy in `config/*.yml` and long-lived project memory in
`projects/<ProjectName>/agent_docs/`.

## Source Of Truth

- Cross-endpoint collaboration rules live in `_shared/AGENT_PROTOCOL.md`.
- Endpoint, Agent, command, tool, and MCP inventory lives in
  `config/shared_agent_directory.yml`; never guess an invocation command.
- Capability selection order lives in `config/capability_routing_policy.yml`.
- Repository-safe inventory and durable memory rules live in
  `config/repository_handoff_policy.yml`.
- Workspace projects live as siblings under `projects/<ProjectName>/`.
- Active longform content projects are configured in `config/content_project_governance.yml`;
  the default active set is `NovelGen` and `Crown_of_Ash`.
- Content project memory and facts are index-driven: `project_artifact_index.yml`
  selects current artifacts and `project_brain/project_fact_snapshot.yml` selects
  durable world/role/timeline facts.
- `projects/<ProjectName>/production/` is the only formal current content source.
  `candidates/`, `runs/`, `archive/`, `_archive/`, `*_rebuild`, `v2_*`, and
  `legacy` paths are not formal fact sources unless explicitly referenced by
  `project_artifact_index.yml`.
- Project memory lives in `projects/<ProjectName>/agent_docs/`.
- Task state lives in `projects/<ProjectName>/runs/<task_id>/`.
- Runtime policy lives in `config/*.yml`.
- Hermes model-group routing lives in `config/hermes_brain_model_groups.yml`.
- Long-project constitutions, must-read artifact rules, and dispatch gates live in
  `config/long_project_governance.yml`.
- Frontdesk capability identities and role binding rules live in
  `config/agent_role_bindings.yml`; never infer write or role authority from a
  CLI name alone.
- User-readable model routing and proposal/apply flow live under
  `./agentlab.sh models ...`.
- Coder handoffs and external executor rules live in `DRIVER_PROTOCOL.md` and
  `OPERATING_MODEL.md`.

## Artifact & Deliverable Delivery Rules (业务产物交付与三层隔离规范)

To keep the project clean, all agents must strictly adhere to the following **three-tier artifact structure** when executing tasks (e.g., writing novels, compiling data, writing code):

Machine-readable project artifact governance lives in `docs/PROJECT_ARTIFACT_STEWARD.md`.
For long-running deliverable tasks, completion requires `artifact_lineage.yml`,
`artifact_promotion_plan.yml`, `archive_receipt.yml`, and an updated
`project_artifact_index.yml`; `09_archive_update.md` is only the human summary.

1. **Task Sandbox Area (工作进行区)**
   * **Path**: `projects/<ProjectName>/runs/<task_id>/`
   * **Purpose**: Task execution details, temporary diffs (`diffs/`), tool/command outputs (`command_logs/`), and step-by-step agent handoff reports (`01_supervisor_plan.md`, `06_implementation_report.md`, etc.). This contains the execution noise and gets archived/purged regularly.
2. **Task Artifact Capture (阶段产物产生区)**
   * **Path**: `projects/<ProjectName>/runs/<task_id>/artifacts/`
   * **Purpose**: The immediate deliverables completed *by this specific task* (e.g., Chapter 3 draft, revised outlines, specific script outputs) for verification.
3. **Project Production Area (项目级/最终交付区)**
   * **Path**: `projects/<ProjectName>/production/`
   * **Purpose**: The official, clean, project-level repository for all finalized deliverables. During the `ARCHIVE` phase, the **Archivist** agent extracts verified assets from the *Task Artifact Capture* area, copies them here, and maintains a clean index. Users can inspect this single directory for all completed deliverables without wading through runs or logs.
   * **Index Gate**: For content projects, `project_artifact_index.yml` decides
     the current version and `project_brain/project_fact_snapshot.yml` decides
     durable narrative facts. Content-changing tasks must emit
     `artifact_lineage.yml` and `state_transition_proposal.yml`.
   * **Visual Gate**: A media producer cannot accept its own work. The actual
     candidate files and hashes must be inspected by independent Observer and
     Reviewer role sessions and structurally checked by Verifier. Archivist may
     promote them only after those gates pass and Supervisor/human approval is
     explicit.

## Scope Rules

- New project: create a top-level sibling under `projects/`.
- New task: create work inside the selected project.
- Subtask: append work under the selected task ledger entry.
- Do not treat chat history as authoritative if a local memory file disagrees.

## Brain Layer Rules

- Hermes with GPT-5.6 Sol owns Supervisor/Brain Layer planning, routing, and
  policy decisions. The user-facing `extra` effort label maps to Hermes
  `xhigh`; only capacity-approved fallback routes may change worker or model.
- Hermes must use durable Plan Mode for long projects: draft the plan, check gaps,
  revise, self-check, then dispatch task packets with `must_read_artifacts`.
- Agy is a read-only multimodal Observer and isolated visual Reviewer. It may
  inspect bounded long text, image, video, audio, and PDF inputs, but it is
  never Writer or ArtifactProducer and cannot promote its own conclusions.
  Its Gemini and Claude subscription routes are independent capacity pools;
  remaining quota and reset time stay unknown until observed.
- Claude Code with DeepSeek owns the current pure Writer route. The ultracode
  surface is developmental and explicit opt-in only, never an automatic route.
- Hermes+xAI/Grok exposes separate sourced Researcher and candidate media
  ArtifactProducer contracts. ArtifactProducer cannot act as Observer,
  Reviewer, or Verifier and cannot accept its own media.
- Coder execution and local file edits use the current registered role profile;
  do not infer executor authority from a CLI name.
- Never silently switch provider, model, or CLI. Use only a declared capacity
  fallback and record the triggering evidence and execution receipt.
- Before execution, publish route, budget, editable scope, and validation gates.
- Prefer the smallest safe route; include agents only when their function is
  needed.
- Repeated human feedback or audit findings must be promoted into config,
  validation gates, scripts, or concise project memory.

## Editing Rules

- Before reading project content, run `./agentlab.sh repository-handoff --repo <path>`;
  if missing, rerun with `--write` before deep reading. This safely inventories all
  paths/metadata without bulk-reading contents and writes root-visible
  `PROJECT_HANDOFF.md`, `.agentlab/HandOff.md`, `agent_docs/HandOff.md`, plus the
  shared `memory/repositories/` mirror.
- Refresh all HandOff copies after every material repository/project change and
  before final reporting. This applies to every Agent and every code, literature,
  image, audio, or mixed-data project.
- Use existing patterns and helpers before adding new abstractions.
- Preserve unrelated user changes in the worktree.
- Use `apply_patch` for manual edits.
- Record real commands and real validation results only.
- Never store credentials or private tokens in project memory.

## Repository Directory Constitution & Hygiene (仓库目录宪章与数据整洁规范)

ALL agents entering this workspace MUST read and enforce this directory layout. NEVER write temporary artifacts, logs, or backups directly to the root directory. Keep the workspace pure and organized.

### Core Layout & Maintenance Policy

| Directory / File | Description & Purpose | Deletion / Cleanup Policy |
| :--- | :--- | :--- |
| `agent_runtime/` | Core python runtime (CLI, model router, lifecycle graph). | **NEVER DELETE**. Source code directory. |
| `agent_templates/` | Agent role prompts (supervisor, coder, auditor) and handoff templates. | **NEVER DELETE**. Critical template definitions. |
| `config/` | System-wide routing policies, token budgets, failover catalogs. | **NEVER DELETE**. Policy source of truth. |
| `docs/` | Engineering specifications, design documents, and historical archives. | **NEVER DELETE**. Keep docs updated. |
| `docs/archive/` | Historical blueprints, retired design reports, and `historical_runs/`. | Safe to organize, but contains historical context. |
| `examples/` | Integration guides, prompt examples, CLI run skeletons. | **NEVER DELETE**. Crucial reference files. |
| `projects/` | Workspace projects containing memory (`agent_docs/`) and task runs. | **DO NOT DELETE**. Active working directories. |
| `projects/<P>/runs/` | Task execution ledgers, event streams, local execution states. | Run `./agentlab.sh task-purge` to clean old tasks (keeps last 7 days). |
| `scripts/` | Git hooks, workspace hygiene verifiers, automation scripts. | **NEVER DELETE**. Core automation tools. |
| `skills/` | Agent skill vault (active/staging/retired local skill lifecycle packages). | **DO NOT DELETE**. Local skill database. |
| `tests/` | Integrated QA pipeline: artifact gates, task closure tests. | **NEVER DELETE**. Standard test suites. |
| `web_ui/` | Dashboard status UI and decision center server code. | **NEVER DELETE**. Control plane front-end. |
| `acceptance_runs/` | CI validation reports, generalization gate artifacts. | Managed by CI scripts. Do not manually touch. |
| `agentlab.sh` | Main CLI entry point. | **NEVER DELETE**. |
| `agentlab_app.py` | Standalone UI server app. | **NEVER DELETE**. |

### Hygiene & Compliance Rules (整洁性合规条例)
1. **Zero Root-level Pollution**: No logs (`.log`, `.txt`), task artifacts, or workspace snapshots are allowed to be created in the root directory.
2. **Task Artifact Scoping**: All task-level execution traces (such as `task_packet.yml`, `cost_ledger.yml`, `state.yml`) must be written exclusively to `projects/<ProjectName>/runs/<task_id>/`.
3. **Audit Before Commit**: The `rule_self_check.py` pre-push check is strictly integrated. Commit hooks will block pushes if root-level pollution or credential leak is detected.
4. **Task Purge & Archiving**: Regularly purge old task runs using `./agentlab.sh task-purge --project <ProjectName> --keep-days 7` to keep the disk space tidy.

## Front-Desk Operator & Tool Call Responsibilities (前端接线员与底层AI调用分工)

- **Frontdesk Protocol (`frontdesk_*`)**:
  - **权威协议**：`docs/FRONTDESK_PROTOCOL.md`，继承 `_shared/AGENT_PROTOCOL.md`。
  - **强制入口**：任何 AgentLab-managed 前台聊天助手都必须通过
    `./agentlab.sh frontdesk-session --agent <agent_id>` 获得会话包；进入仓库时先用
    `./agentlab.sh workspace-entry --agent <agent_id>` 获取最小上下文，禁止靠全仓库重读
    重新理解 AgentLab。
  - **角色边界**：frontdesk 只做用户沟通、状态解释、任务创建/准备、审批展示、handoff、
    调用登记 agent、监控与结果回传；不得自行实现任务或编辑目标文件。
  - **长期任务边界**：后续批次必须引用现有 plan handoff、revision log 和
    `must_read_artifacts`；不得为小说、工程、视频等长期项目重新发明 prompt。
  - **职责绑定**：CLI 名字不等于 AgentLab 角色。14 个 canonical AgentLab 角色必须通过
    `./agentlab.sh role-session --role <Role> --worker <worker> --project <P> --task-id <T>`
    生成强绑定会话包；`./agentlab.sh protocol-doctor` 是强规定自检入口。
  - **写入边界**：frontdesk 只能直接生成 `change_request.yml`、
    `patch_proposal.diff`、`frontdesk_notes.md` 等提案；核心配置、runtime、
    production 正式产物必须由 AgentLab gate 或修订治理流程应用。
- **OpenClaw (`openclaw`)**:
  - **角色与司职**：前端接线员 (Front-desk Operator)。
  - **主要职责**：负责对接与用户的自然语言沟通（如微信 wechat-mp-bot/wechat-ai-bot、Telegram 或 Web UI 交互），接收原始 prompt，展示计划门禁/审批流（如 Dry-Run vs Execute），并在必要时将任务推送到后端 AgentLab 公司系统中处理成资产。
  - **连接机制**：通过登记的 frontdesk session / bridge 调用底座 CLI（如 `agy -p`），再由 AgentLab 生成 handoff 或 role session 驱动后端 worker。
  - **显式委派边界**：用户明确点名调用其他 Agent 时，OpenClaw 只做 handoff、
    调用、监控和证据化报告，不得自行执行任务或编辑目标文件；目标不可用时停止并
    报告，不得静默 fallback。
- **Bailian CLI (`bl` / `bailian-cli`)**:
  - **角色与司职**：底层多模态 AI 工具调用者 (Multi-modal AI Tool Caller)。
  - **主要职责**：DashScope/阿里云百炼平台服务的主要交互工具。负责处理文本对话、多模态对话、图像生成与编辑、视频生成与编辑/参考（Wan2.x/happyhorse等）、语音合成与识别 (TTS/ASR)、临时 OSS 文件上传、知识库检索 (RAG) 等。
  - **使用规范**：仅在用户明确要求或任务确实需要百炼多模态、媒体、语音、RAG、
    百炼搜索等专用能力时调用。普通编码、Git、测试、仓库检索优先使用本地确定性
    工具；禁止为了流程进行象征性 `bl` 调用。

## Dual-End Collaboration Protocol (双端协作协约)

- **Network Topology / Link Layout**:
  - **Local Workstation**: Primary development environment and source of truth.
  - **Relay Hub** (`<RELAY_HOST>:<RELAY_SSH_PORT>`): Resource exchange relay station and backup.
  - **Cloud Runtime** (`<CLOUD_RUNTIME_HOST>`): Running / deployment environment. Directly accessible via SSH from local workstation and connected to the Relay Hub repository.
- **Sync Workflow**:
  - Local workstation pushes skills, configs, memory snapshots to Relay Hub using `./agentlab.sh relay-sync --execute`.
  - Cloud Runtime pulls updates from Relay Hub using `rsync` to synchronize `skills`, `mcp`, and task status.
  - Cloud Runtime execution results are pushed back to `<RELAY_IP>` and then pulled to Local Mac to ensure all memory capabilities are synchronized.

## Useful Commands

- `./agentlab.sh repository-handoff --repo <path>`
- `./agentlab.sh repository-handoff --repo <path> --write`
- `./agentlab.sh prepare --project AgentLab --task-id task_0009 --write-plan`
- `./agentlab.sh brain-status --project AgentLab --task-id task_0009`
- `./agentlab.sh harness-status --project AgentLab --task-id task_0009`
- `./agentlab.sh policy-status --project AgentLab`
- `./agentlab.sh models show --role Writer`
- `./agentlab.sh models doctor`
- `./agentlab.sh governance revision-intake --project <Project> --task-id <Task> --prompt "..."`
- `./agentlab.sh governance check-revision --project <Project> --task-id <Task>`
- `./agentlab.sh governance apply-revision --project <Project> --task-id <Task> --accept`
- `./agentlab.sh governance doctor --project Crown_of_Ash`
- `./agentlab.sh log-event --project AgentLab --task-id task_0009 --agent Coder --summary "..."`
