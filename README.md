# AgentLab / 智能体实验室

> English | 中文

AgentLab is a local-first, semi-managed development workflow for personal agentic software work.

AgentLab 是一个本地优先、半托管的个人 Agentic 软件开发工作流。

The goal is to make model-assisted development cheaper, more transparent, and more controllable than one long chat:

目标是让模型辅助开发比"一个长聊天"更便宜、更透明、更可控：

- Store task state and project memory locally. / 本地存储任务状态和项目记忆。
- Route only the agents needed for the task. / 仅路由任务所需的 Agent。
- Publish token budgets before work starts. / 工作开始前公开发布 Token 预算。
- Keep implementation, validation, audit, and archival evidence separate. / 实现、验证、审计、归档证据分离。
- Preserve long-running project direction through explicit memory files. / 通过显式记忆文件保持长期项目方向。

---

## Operating Model / 运行模型

AgentLab uses a multi-tier brain workflow with dynamic model selection:

```text
T1 大脑层  (Brain):    Supervisor          → DeepSeek V4 Pro / Qwen3.6-Plus
T2 感知层  (Perception): RepoScout, Researcher, InterfaceMapper → Qwen3.6+/Qwen3.7-Max
T3 执行层  (Execution): Coder, PromptEngineer → Qwen3-Coder-Next / DeepSeek V4 Pro
T4 审核层  (Audit):     TesterAuditor, Verifier → Qwen3.6-Flash/Plus
T5 归档层  (Archive):   Archivist → Qwen3.6-Plus / Qwen3.7-Max
```

Three budget modes control model selection per task:
- 🧠 **brain_allocated** (default): cost-optimized tier matching by project size (L1/L2/L3)
- ⚡ **max_quality**: best available models at every tier
- 💰 **frugal**: lightweight models, skip optional agents, local LLM support

Coder supports four backends:
- `api_qwen_coder` — Qwen3-Coder-Next (default)
- `api_deepseek_coder` — DeepSeek V4 Pro (max quality)
- `local_llm` — Ollama/vLLM (frugal mode)
- `external_ide` — external IDE AI handoff (Codex/Claude/Cline)

See `config/agent_registry.yml`, `config/model_catalog.yml`, and `OPERATING_MODEL.md`.

---

## Project Structure / 项目结构

```text
AgentLab/
├── agent_runtime/          # Core runtime: CLI, lifecycle graph, guard, progress tracker,
│                           # brain governor, task router, provider failover, LLM provider,
│                           # task index, terminal chat, evaluation suite, task snapshot,
│                           # memory writer, artifact contract, pipeline runner, state store
│                           # 核心运行时：CLI、生命周期图、守护、进度追踪、
│                           # 大脑治理、任务路由、提供者故障切换、LLM 提供者、
│                           # 任务索引、终端聊天、评估套件、任务快照、
│                           # 记忆写入器、产物契约、管线运行器、状态存储
├── agent_templates/        # 9 agent role prompts + Codex Full-Driver templates
│                           # 9 个 Agent 角色提示词 + Codex 全驱动模板
├── config/                 # YAML policies: routing, budget, models, validation gates,
│                           # guard, backup, auto-sync, evaluation, execution modes, etc.
│                           # YAML 策略：路由、预算、模型、验证门禁、
│                           # 守护、备份、自动同步、评估、执行模式等
├── skills/                 # Local skill lifecycle registry and staged/active/retired packages
│                           # 本地技能生命周期注册表，以及 staging/active/retired 技能包
├── projects/               # Per-project memory docs and task run records
│   ├── AgentLab/           #   AgentLab self-tracking project
│   └── AO-SpatialAuthoring-Modular/  # AO spatial audio authoring project
│                           # 每个项目的记忆文档和任务运行记录
├── streaming_stereo_spatializer/  # Non-AI streaming stereo→4.0 spatializer
│                           # 非AI流式立体声→4.0空间化处理器
├── tests/                  # Integration tests: artifact gates, task closure
│                           # 集成测试：产物门禁、任务闭环
├── web_ui/                 # Static status dashboard with task details panel
│                           # 静态状态看板（含任务详情面板）
├── scripts/                # Git hooks and automation
│                           # Git 钩子和自动化脚本
├── docs/                   # Specs: Codex Full-Driver Operation Chain
│                           # 规范：Codex 全驱动操作链
├── agentlab.sh             # One-command CLI entrypoint
│                           # 一键 CLI 入口
├── DRIVER_PROTOCOL.md      # Protocol for external AIs to drive AgentLab
│                           # 外部 AI 驱动 AgentLab 的协议
├── OPERATING_MODEL.md      # Multi-tier operating rules
│                           # 分层运行规则
└── CLI_ROADMAP.md          # CLI evolution roadmap
                            # CLI 演进路线图
```

---

## 9 Agents / 9 个智能体

| Agent / 智能体 | Tier | Role / 角色 | Permissions / 权限 |
|---|---|---|---|
| **Supervisor** | T1 | 任务规划、路由决策、范围锁定、Token 预算、预算模式选择 | 只读 |
| **RepoScout** | T2 | 仓库结构扫描和上下文映射 | 只读 + shell 检查 |
| **Researcher** | T2 | 外部信息/文档研究 | 只读 + 可浏览 |
| **InterfaceMapper** | T2 | 接口、契约、边界映射 | 只读 + shell 检查 |
| **PromptEngineer** | T3 | 稳定生成 Coder 执行提示词，拼接 scope + context + contracts | 只读 |
| **Coder** | T3 | 代码编辑、文件变更、项目命令（API/本地/外部IDE） | 可写源码 + 可执行 |
| **TesterAuditor** | T4 | Diff 审查、验证解读、风险发现、行为校验 | shell 验证命令 |
| **Verifier** | T4 | 输出匹配检查、行为完整性验证、Agent 交接缺口检测 | 只读 + shell 检查 |
| **Archivist** | T5 | 项目记忆维护 + 跨任务文档整合 + 任务归档清理 | 可写 agent_docs |

Configuration / 配置入口: `config/agent_registry.yml` | Templates / 模板: `agent_templates/*.md`

Budget modes and project sizes (L1/L2/L3) dynamically select which model profile each agent uses — see `config/model_catalog.yml`.

---

## Task Routing / 任务路由

5 route profiles based on task content + project size heuristics:

| Route / 路由 | Trigger / 触发条件 | Agents / 智能体 |
|---|---|---|
| `small_task` | Default / 默认 (<800 chars) | Supervisor → Coder → TesterAuditor |
| `medium_task` | >800 chars / 字符 | +RepoScout +Archivist |
| `interface_sensitive_task` | api/schema/protocol/db/ui 等 | +InterfaceMapper |
| `research_sensitive_task` | latest/docs/pricing/regulation 等 | +Researcher |
| `large_or_risky_task` | architecture/refactor/security 或 >2500 chars | 全 9 个 agent / all 9 agents |

Principle: **smallest safe route** / 原则：**最小安全路线**。

Verifier runs on L2+ tasks; skipped on L1 frugal mode.

---

## Lifecycle State Machine / 生命周期状态机

Every task follows a canonical 14-node lifecycle with checkpoint tracking and resume support:

```text
INIT_TASK → PREPARE_PLAN → SUPERVISOR_PLAN → REPO_CONTEXT
  → RESEARCH_OPTIONAL → INTERFACE_OPTIONAL → CODER_IMPLEMENTATION
  → VALIDATION → AUDIT → VERIFY → ARCHIVE → SELF_CHECK
  → SYNC_OPTIONAL → FINALIZE
```

Task states: `new` → `planned` → `in_progress` → `paused`/`blocked`/`recoverable` → `validating` → `auditing` → `archiving` → `syncing` → `completed`/`failed`

Each task tracks progress via `progress.yml` with per-agent weights, token accounting, provider status, and incident tracking. Both CLI and Web UI consume this single source of truth.

---

## AgentLab Guard / 守护系统

Concurrent safety and crash recovery for multi-agent workflows:

- **Atomic I/O**: all state writes use atomic write-then-rename (`atomic_io.py`)
- **File locks**: exclusive per-task locks prevent concurrent writes by multiple agents
- **Heartbeats**: periodic heartbeat files detect stale/crashed processes (120s timeout)
- **Crash recovery**: auto-detect stale locks and offer guided recovery
- **Transaction tracking**: every lock acquisition creates an auditable transaction record

Run `./agentlab.sh guard-status --project <Project> --task-id <task_id>` to inspect lock state.

---

## Provider Failover / 提供者故障切换

When a provider API fails, AgentLab can pause and switch to a fallback:

- Detects provider failures and records incidents in `progress.yml`
- Pauses task state with `paused_for_provider` flag
- Supports manual provider override to resume with a different model
- Incident history recorded for post-task review

---

## Codex Full-Driver Mode / Codex 全驱动模式

Codex can temporarily execute ALL AgentLab roles as an external driver while still writing every standard artifact locally. This allows consuming Codex quota without losing the ability to resume via API agents later.

Key artifact: `handoff_packet.yml` — machine-readable resume state for any model or human.

Three safe transitions: **Codex → Codex**, **Codex → API agents**, **Codex → human manual**.

Full spec: `docs/AGENTLAB_CODEX_FULL_DRIVER_OPERATION_CHAIN_SPEC.md`

---

## Task Discovery & Resume Index / 任务发现与恢复索引

Global task index with searchable metadata:

- `task_index.yml` — searchable registry of all tasks across all projects
- `task_card.yml` — per-task summary: status, route, cost, key decisions
- Task search by status, agent, risk level, budget mode
- Resume support: find paused/blocked tasks and continue from last checkpoint

CLI: `./agentlab.sh task-search --status paused`, `./agentlab.sh task-resume --project <P> --task-id <T>`

---

## Skill Lifecycle MVP / 技能生命周期 MVP

AgentLab now implements a local closed-loop skill lifecycle, active skill retrieval/injection, and post-task Trace-to-Skill candidate generation:

### Lifecycle States

```
pending_user_approval → approved → staging → validated → active → retired
                      ↘ rejected
```

### Filesystem Layout

```
skills/
  registry.yml          # Skill registry (status: local_lifecycle_mvp)
  staging/<skill_id>/   # Staged skills awaiting validation
    metadata.yml
    adapted_skill.md
    validation_plan.yml
    sandbox_report.yml
  active/<skill_id>/    # Active (promoted) skills
    SKILL.md
    metadata.yml
    validation_report.yml
    usage_ledger.yml
  retired/<skill_id>/   # Retired skills
    SKILL.md
    metadata.yml
    retired_at.yml
```

### CLI Commands

```
./agentlab.sh skill-list --project AgentLab
./agentlab.sh skill-request --project AgentLab --name demo --source manual://demo --purpose "test"
./agentlab.sh skill-approve --project AgentLab --request-id <id>
./agentlab.sh skill-reject --project AgentLab --request-id <id> --reason "..."
./agentlab.sh skill-stage --project AgentLab --request-id <id>
./agentlab.sh skill-validate --skill-id <id> --fake-sandbox
./agentlab.sh skill-promote --skill-id <id>
./agentlab.sh skill-retire --skill-id <id> --reason "obsolete"
./agentlab.sh skill-match --project AgentLab --task-id <task_id>
./agentlab.sh skill-inject --project AgentLab --task-id <task_id>
./agentlab.sh skill-usage --project AgentLab --task-id <task_id>
./agentlab.sh learning-review --project AgentLab --task-id <task_id>
./agentlab.sh skill-candidates --project AgentLab --task-id <task_id>
./agentlab.sh skill-candidate-approve --project AgentLab --task-id <task_id> --candidate-id <id>
```

### Active Skill Injection

`prepare --write-plan` and pipeline `PREPARE_PLAN` retrieve active skills from `skills/active/<skill_id>/metadata.yml`, record selected/rejected skills in `workflow_plan.yml`, write task-level `skill_usage.yml`, and append each selected active skill's `usage_ledger.yml`.

### Trace-to-Skill Learning

Pipeline completion and `learning-review` inspect task events and reports for reusable patterns such as blocked/resolved decisions, validation failures, recovery actions, repeated approvals, repo-specific repair procedures, and artifact contract workarounds. Matching patterns create `skill_candidates/*.yml`; approving a candidate creates a `self_learned` Skill Adoption Request that follows the same lifecycle.

### Implemented

- ✅ local skill lifecycle
- ✅ skill retrieval/injection MVP
- ✅ skill usage ledger
- ✅ post-task learning review
- ✅ skill candidate generation

### Not Yet Implemented

- ❌ real GitHub skill search
- ❌ real external package parsing
- ❌ real sandbox execution
- ❌ automatic external skill learning
- ❌ production-grade skill conflict resolution / retirement policy

---

## Feedback Loop Scaffold / 反馈闭环骨架

AgentLab has an MVP real-time feedback loop for event-driven task feedback and human intervention. Pipeline blocks produce decision cards and task events; the Web UI Decision Center reads those cards, exposes approve/reject/resume controls, and receives task events through Server-Sent Events with polling fallback.

- `task_events.jsonl` is the per-task event timeline.
- `decision_cards/*.yml` is the per-task pending approval queue.
- `config/feedback_policy.yml` defines fine-grained statuses, notification levels, and watchdog thresholds.
- `config/watchdog_policy.yml` defines stale-running, stale-event, waiting-approval, and stale-lock thresholds.
- `web_ui/server.py` exposes `/api/tasks/<task_id>/events`, `/events/stream`, `/decisions`, decision approve/reject, and task resume/pause/stop endpoints.
- `watchdog-scan` marks stale running tasks with `STALE_RUNNING`, refreshes `feedback_status.json`, and can create a recovery decision card.

CLI: `./agentlab.sh feedback-status --project AgentLab`, `./agentlab.sh task-event --project AgentLab --task-id <T> --event TASK_CREATED`, `./agentlab.sh watchdog-scan --project AgentLab`, `./agentlab.sh watchdog-status --project AgentLab --task-id <T>`

### Webhook Notifications

AgentLab can optionally push action-required and lifecycle events to external chat gateways such as OpenClaw or Hermes. Webhooks are disabled by default; endpoint URLs and signing secrets are read only from environment variables.

- `config/webhook_policy.yml` controls enabled endpoints, event allow-lists, retry count, signing, and redaction.
- Delivery logs are written to `projects/<Project>/runs/<task_id>/webhook_delivery_log.yml` or `projects/<Project>/webhook_delivery_log.yml` for project-level skill events.
- Dispatchable events include `ACTION_REQUIRED`, `BLOCKED`, `BUDGET_WARNING`, `STALE_RUNNING`, `FAILED_RECOVERABLE`, `COMPLETED`, `SKILL_REQUEST_PENDING`, `SKILL_CANDIDATE_READY`, and `SKILL_PROMOTED`.

CLI: `./agentlab.sh webhook-test --event ACTION_REQUIRED --project AgentLab --task-id <T>`, `./agentlab.sh webhook-status --project AgentLab --task-id <T>`, `./agentlab.sh webhook-redeliver --project AgentLab --task-id <T>`

Guide: `docs/WEBHOOK_INTEGRATION.md`

### MCP Tool Server

AgentLab exposes a thin optional MCP-style stdio tool server for external agents that need structured task, decision, skill, webhook, and watchdog operations.

- `agent_runtime/mcp_server.py` defines tool schemas, structured handlers, resources, and a minimal stdio JSON-RPC loop.
- `config/mcp_policy.yml` gates task creation, decision approval, skill approval, and stop-task operations.
- Tools include task status/events/report, decision approve/reject/resume, skill request/approval, active skill usage, webhook status, and watchdog scan.

Smoke: `python -m agent_runtime.mcp_server --list-tools`

Guide: `docs/MCP_INTEGRATION.md`

### Implemented

- ✅ task_events.jsonl
- ✅ decision_cards
- ✅ feedback_status
- ✅ Web UI Decision Center MVP
- ✅ SSE/polling real-time feedback MVP
- ✅ watchdog scan MVP
- ✅ webhook dispatcher MVP
- ✅ MCP-style tool server MVP

### Not Yet Implemented

- ❌ chat-native OpenClaw/Hermes/Telegram adapter
- ❌ full production MCP SDK certification
- ❌ long-running daemon hardening
- ❌ real GitHub skill discovery
- ❌ real sandbox execution
- ❌ external skill package parser
- ❌ production-grade daemon service manager

Roadmap: `docs/AGENTLAB_SKILL_FEEDBACK_ROADMAP.md`

---

## Terminal Chat / 终端对话

Direct CLI chat interface for quick agent interactions without a full task run:

```bash
./agentlab.sh chat --agent Supervisor --project <Project>
```

Supports single-turn queries with any configured agent/model, with cost tracking.

---

## Evaluation Suite / 评估套件

Built-in evaluation framework for validating AgentLab's own behavior:

- **Modes**: offline_first, mock_provider, api_smoke, full_api
- **Audits**: system audit, artifact completeness (≥90%), lifecycle pass rate (≥85%), recovery pass rate (≥80%), budget savings (≥30% vs monolithic), secret leak detection
- **Token estimation**: char/4 fallback with optional tiktoken
- **Cost tracking**: config-based pricing with override support

Run: `cd agent_runtime/evaluation && python eval_all.py`

---

## One-Command CLI / 一键 CLI

From the AgentLab root / 从 AgentLab 根目录：

```bash
# Initialize a new task / 初始化新任务
./agentlab.sh init-task --project <Project> --task-id task_0007

# Build workflow plan / 生成工作流计划
./agentlab.sh prepare --project <Project> --task-id task_0007 --write-plan

# Check task status / 查看任务状态
./agentlab.sh status --project <Project> --task-id task_0007

# Run a brain agent (dry-run by default, --execute to call API) / 运行大脑层 Agent
./agentlab.sh run-agent Supervisor --project <Project> --task-id task_0007 --execute

# Check brain governance / 查看大脑治理状态
./agentlab.sh brain-status --project <Project> --task-id task_0007

# Migration / backup readiness / 迁移与备份就绪检查
./agentlab.sh migration-doctor --project <Project>
./agentlab.sh migration-init --project <Project>
./agentlab.sh truenas-status --project <Project>
./agentlab.sh truenas-sync --project <Project> --task-id task_0007 --dry-run
./agentlab.sh backup-status --project <Project> --task-id task_0007

# List configured models/providers / 列出已配置的模型/提供者
./agentlab.sh models

# View execution policy / 查看执行策略
./agentlab.sh policy-status --project <Project>

# Log an event to ledgers / 记录事件
./agentlab.sh log-event --project <Project> --task-id task_0007 --agent Coder --summary "..." --files-changed "..."

# Request traversal permission / 请求遍历权限
./agentlab.sh request-traversal RepoScout --project <Project> --task-id task_0007 --scope full_repo --full-repo --reason "Need initial repo map"

# Request coder quota decision / 请求 Coder 配额决策
./agentlab.sh request-coder-quota --project <Project> --task-id task_0007 --reason "Codex quota may be insufficient"

# Check guard status / 查看守护状态
./agentlab.sh guard-status --project <Project> --task-id task_0007

# Scan stale locks / 扫描过期锁
./agentlab.sh guard-scan --project <Project>

# Search tasks / 搜索任务
./agentlab.sh task-search --project <Project> --status paused

# Resume a paused task / 恢复暂停的任务
./agentlab.sh task-resume --project <Project> --task-id task_0007

# System health check / 系统健康检查
./agentlab.sh doctor

# Terminal chat / 终端对话
./agentlab.sh chat --agent Supervisor --project <Project>

# Task purge + project docs / 任务清理 + 项目文档
./agentlab.sh task-purge --project <Project> --keep-days 7 --dry-run
./agentlab.sh task-purge --project <Project> --keep-days 7

# Codex full-driver commands / Codex 全驱动命令
./agentlab.sh codex-start --project <Project> --task-id task_0007 --mode full-driver
./agentlab.sh codex-handoff --project <Project> --task-id task_0007

# Local closure verification / 本地闭环验证
./agentlab.sh init-task --project AgentLab --task-id task_9999 --request-text "Demo"
./agentlab.sh prepare --project AgentLab --task-id task_9999 --write-plan
./agentlab.sh run-pipeline --project AgentLab --task-id task_9999 --dry-run
./agentlab.sh check --project AgentLab --task-id task_9999
./agentlab.sh ui
```

`run-agent` is dry-run by default. It calls the configured model API only when you pass `--execute`.

`run-agent` 默认 dry-run，仅当传入 `--execute` 时才调用模型 API。

---

## Driver Protocol / 驱动协议

Any external AI (Codex Plus, Claude, IDE assistants) can drive AgentLab as a thin relay.
Read `DRIVER_PROTOCOL.md` for the full 7-step protocol.

任何外部 AI（Codex Plus、Claude、IDE 助手）都可以作为轻量中继驱动 AgentLab。完整 7 步协议见 `DRIVER_PROTOCOL.md`。

Two execution modes for external AIs:
- **Coder-Only**: external AI only edits code and runs commands; AgentLab API agents handle planning, review, archiving
- **Full-Driver** (Codex): external AI emulates all 9 roles while writing all standard artifacts; resumable by API agents later

The key rule / 核心规则：
- **External AIs do NOT think — AgentLab's brain does.** / **外部 AI 不思考 — AgentLab 的大脑来思考。**
- External AIs only transcribe user requests, execute the Coder phase, and relay decisions. / 外部 AI 仅转录用户请求、执行 Coder 阶段、中继决策。
- If brain models are unavailable, AgentLab blocks and asks the user — no silent simulation. / 如果大脑模型不可用，AgentLab 阻止并询问用户——不允许静默模拟。

---

## Brain Governance / 大脑治理

- Token budgets per agent phase (warning at 90%, stop at 115%) / 每个 Agent 阶段的 Token 预算（90% 警告，115% 停止）
- Full-repo traversal requires explicit approval / 全仓库遍历需要显式批准
- Loop detection: 3+ repeated similar decisions → stop and replan / 循环检测：3 次以上重复相似决策 → 停止并重新规划
- Budget mode selection: brain_allocated / max_quality / frugal per task / 预算模式选择
- Project size classification: L1 (轻量) / L2 (标准) / L3 (重型) determines model tier
- Provider failover: auto-pause on API failure, record incident, allow manual resume with fallback model / 提供者故障切换
- Guard system: atomic I/O, file locks, heartbeats, crash recovery / 守护系统
- Harness status checks verify `AGENTS.md`, project memory freshness, task feedback artifacts, and repeated-feedback promotion points. / Harness 状态检查
- All decisions written to `brain_decisions.yml` / 所有决策写入 `brain_decisions.yml`
- User decisions written to `USER_DECISION_REQUIRED.md` / 用户决策写入 `USER_DECISION_REQUIRED.md`

Policy configs live in `config/`. Run:

```text
./agentlab.sh harness-status --project <Project> --task-id task_0007
./agentlab.sh guard-status --project <Project> --task-id task_0007
```

---

## Audit Trail Per Task / 每条任务的审计追踪

```
runs/task_xxxx/
├── user_request.md          # User's natural-language task / 用户自然语言任务
├── workflow_plan.yml        # Route + token budgets + validation gates / 路由 + 预算 + 门禁
├── lifecycle.yml            # Canonical lifecycle state machine / 规范生命周期状态机
├── progress.yml             # Per-agent progress, tokens, provider status / 各Agent进度
├── state.yml                # Task state machine / 任务状态机
├── task_card.yml            # Searchable task summary / 可搜索的任务摘要
├── supervisor_plan.md       # Scope, route, budget table, risks / 范围、路由、预算表、风险
├── reposcout_report.md      # Repository context / 仓库上下文
├── research_notes.md        # External research findings / 外部研究结果
├── interface_map.md         # Interface boundaries / 接口边界
├── codex_prompt.md          # Coder handoff prompt / Coder 交接提示词
├── implementation_report.md # Changed files, commands, backend / 变更文件、命令、后端
├── validation_report.md     # Tester/Auditor validation / 测试/审计验证
├── audit_report.md          # Diff audit findings / Diff 审计发现
├── verification_report.md   # Verifier completeness check / Verifier 完整性检查
├── archive_update.md        # Project memory updates / 项目记忆更新
├── brain_decisions.yml      # All governance decisions / 所有治理决策
├── cost_ledger.yml          # Token cost accounting / Token 成本记账
├── provider_incidents.yml   # Provider failure records / 提供者故障记录
├── handoff_packet.yml       # Machine-readable resume state / 可机读的恢复状态
├── self_check_report.yml    # Self-check before push / 推送前自查
├── artifact_manifest.yml    # Final artifact inventory / 最终产物清单
├── USER_DECISION_REQUIRED.md  # When user must decide / 需要用户决策时
├── task_snapshot.yml        # Task snapshot for checkpoint recovery / 任务快照用于检查点恢复
├── diffs/                   # Pre/post coder diffs / Coder 前后差异
├── checkpoints/             # Recovery checkpoints / 恢复检查点
├── command_logs/            # Commands run and outputs / 执行命令和输出
└── sync/                    # GitHub/Truenas sync reports / 同步报告
```

---

## Local Status UI / 本地状态界面

AgentLab has a dependency-free static status board / AgentLab 有一个零依赖的静态状态看板：

```text
web_ui/index.html
```

Shows agent state, route, provider, ownership, edit rights, token budget, progress percentage, lifecycle stage, provider status, and recent events. Task details panel links to code layer.

显示 Agent 状态、路由、提供者、所有权、编辑权限、Token 预算、进度百分比、生命周期阶段、提供者状态和最近事件。任务详情面板与代码层关联。

---

## GitHub Private Backup & Auto-Sync / GitHub 私有备份与自动同步

AgentLab supports guarded GitHub auto-sync with self-check before push:

- Private repository backup via `config/github_policy.yml`
- Pre-push rule self-check (`rule_self_check.py`) blocks push if artifacts are incomplete
- Sync history recorded in `agent_docs/10_SYNC_LEDGER.yml`
- TrueNAS silent merge backup support
- Post-commit auto-push hook (safe: blocked if `.env` or secrets staged)

---

## Task Purge & Project Documentation / 任务清理与项目文档

Archivist (T5) 的 bulk 文档整合模式提供自动任务归档和项目文档生成:

Archivist bulk mode provides automatic task archival and project documentation generation:

**Task Archival / 任务归档:**
- Auto-archive completed tasks older than `keep_days` (default 7 days) to `archive/`
- `keep: true` flag in `state.yml` protects tasks from archival
- Dry-run mode previews what would be archived without moving files

**Project Documentation / 项目文档生成:**
- `development_process.md` — 开发流程文档（整合所有任务的实现报告）
- `usage_guide.md` — 使用指南（CLI 命令参考、常见工作流）
- `CHANGELOG.md` — 项目更新日志（按任务自动维护）
- `task_index.md` — 任务索引（所有任务的状态和路由一览）

CLI / 命令行:
```bash
# Preview archival (dry-run) / 预览归档内容
./agentlab.sh task-purge --project <Project> --keep-days 7 --dry-run

# Execute archival + generate docs / 执行归档并生成文档
./agentlab.sh task-purge --project <Project> --keep-days 7
```

Generated docs are written to `projects/<Project>/docs/`. The archival report is saved as `runs/task_purge_report.yml`.

生成的文档写入 `projects/<Project>/docs/`。归档报告保存为 `runs/task_purge_report.yml`。

---

## Streaming Stereo Spatializer / 流式立体声空间化器

A non-AI streaming stereo-to-4.0 spatialization tool located in `streaming_stereo_spatializer/`. Converts stereo L/R audio into five spatial layers (Bass, Front Core, Side Width, Rear Ambience, High Air) rendered to logical 4.0 output. Supports multiple presets (natural, wide, vocal_safe, live, club, bypass, ms_baseline) with energy matching and clipping prevention.

非 AI 流式立体声转 4.0 空间化工具，位于 `streaming_stereo_spatializer/`。将立体声 L/R 音频转换为五层空间层（低频、前核、侧宽、后氛围、高空气），渲染为逻辑 4.0 输出。支持多种预设（自然、宽、人声安全、现场、俱乐部、旁通、M/S 基线），带有能量匹配和削波预防。

---

## Integration Tests / 集成测试

Two test suites validate AgentLab's own pipeline integrity:

| Test | Purpose |
|---|---|
| `test_artifact_gate.py` | Validates artifact completeness: verifies all required fields exist in workflow plan, progress, state, lifecycle, and audit reports |
| `test_task_closure.py` | End-to-end task closure test: init → prepare → pipeline dry-run → check final state |

Run with:
```bash
cd tests
python -m pytest test_artifact_gate.py test_task_closure.py -v
```

两份测试套件验证 AgentLab 自身管线完整性：产物门禁验证和任务闭环测试。

---

## Version Control / 版本控制

This repo is version-controlled on GitHub / 本仓库在 GitHub 上进行版本控制：

```text
https://github.com/Kidrage/AgentLab
```

Auto-push via post-commit hook / 通过 post-commit 钩子自动推送：

```bash
git add -A
git commit -m "描述此次修改 / Describe your change"
# → auto-pushes to origin main / 自动推送到 origin main
```

Use `git status` before committing to ensure no sensitive files (`.env`, credentials) are staged.

提交前用 `git status` 确认没有暂存敏感文件（`.env`、凭证）。

---

## Changelog / 更新日志

| Version / 版本 | Date / 日期 | Changes / 变更 |
|---|---|---|
| 2.3 | 2026-06-06 | Operational upload & evaluation hardening; Task Snapshot (`task_snapshot.py`) for checkpoint-based recovery; Memory Writer (`memory_writer.py`) for structured agent memory persistence; AO-SpatialAuthoring-Modular project docs (12 agent_docs + 2 task runs); Streaming Stereo Spatializer (`streaming_stereo_spatializer/`); Artifact Gate tests (`test_artifact_gate.py`) and Task Closure tests (`test_task_closure.py`); Web UI `server.py` refactor; sync report enhancements / 操作上传与评估强化；基于检查点的任务快照系统（`task_snapshot.py`）；结构化 Agent 记忆持久化（`memory_writer.py`）；AO-SpatialAuthoring-Modular 项目文档（12 agent_docs + 2 task runs）；Streaming Stereo Spatializer（`streaming_stereo_spatializer/`）；Artifact Gate 测试（`test_artifact_gate.py`）与 Task Closure 测试（`test_task_closure.py`）；Web UI `server.py` 重构；同步报告增强 |
| 2.2 | 2026-06-05 | Closure hardening — doctor command, canonical artifacts, cockpit API; Pipeline runner refactor (`pipeline_runner.py`); Artifact contract system (`artifact_contract.py`); Lifecycle graph state machine (`lifecycle_graph.py`); Progress tracker with per-agent weighting (`progress_tracker.py`); State store with atomic writes (`state_store.py`); Task index with searchable metadata (`task_index.py`); Bug report template; Evaluation runs for lifecycle, provider failover, self-check sync, system audit / 闭环加固 — doctor 命令、规范产物、Cockpit API；管线运行器重构（`pipeline_runner.py`）；产物契约系统（`artifact_contract.py`）；生命周期图状态机（`lifecycle_graph.py`）；带 Agent 权重的进度追踪器（`progress_tracker.py`）；原子写入的状态存储（`state_store.py`）；可搜索元数据的任务索引（`task_index.py`）；Bug 报告模板；生命周期、提供者故障切换、自查同步、系统审计评估运行 |
| 2.1 | 2026-06-01 | Agent refactoring: CodexPromptGenerator → PromptEngineer (qwen3.6-plus, stable coder handoff prompts); DocManager merged into Archivist (qwen3.6-plus, per-task archiving + bulk doc generation + task purge); 9-agent clean architecture with rationalized model assignments / Agent 重构：CodexPromptGenerator→PromptEngineer（qwen3.6-plus，稳定生成 Coder 执行提示词）；DocManager 合并入 Archivist（qwen3.6-plus，单任务归档+批量文档整合+任务清理）；9 Agent 精简架构，模型分配合理化 |
| 2.0 | 2026-05-31 | 9-agent tiered architecture (T1-T5), Model Tier v3 with Size×Risk×Budget routing, AgentLab Guard (atomic I/O + locks + heartbeat + crash recovery), Provider Failover with pause/resume, Lifecycle State Machine (14-node graph + checkpoints), Progress Tracker (progress.yml), Verifier agent, Codex Full-Driver Operation Chain, Task Discovery & Resume Index, Terminal Chat, Evaluation Suite, Rule Self-Check + Guarded GitHub Auto-Sync, Web UI task details panel, 22 config policies, 40+ runtime modules / 9 Agent 分层架构（T1-T5）、Model Tier v3 尺寸×风险×预算路由、AgentLab 守护（原子 IO + 锁 + 心跳 + 崩溃恢复）、提供者故障切换与暂停/恢复、生命周期状态机（14节点图 + 检查点）、进度追踪、Verifier 智能体、Codex 全驱动操作链、任务发现与恢复索引、终端对话、评估套件、规则自查 + 守卫式 GitHub 自动同步、Web UI 任务详情面板、22 个配置策略、40+ 运行时模块 |
| 1.0 | 2026-05-30 | Initial release: 8-agent multi-agent workflow, split-brain architecture (DeepSeek + Codex Plus), 5 route profiles, token budget governance, brain governor, loop detection, local status UI, driver protocol for external AI, auto-push git hook / 初始发布：8 Agent 多智能体工作流、双脑架构（DeepSeek + Codex Plus）、5 种路由配置、Token 预算治理、大脑治理、循环检测、本地状态界面、外部 AI 驱动协议、自动推送 Git 钩子 |
