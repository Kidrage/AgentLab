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

This AgentLab uses a split-brain workflow / 本 AgentLab 采用双脑工作流：

```text
DeepSeek API = low-cost management and reasoning / 低成本管理与推理层
Codex Plus   = real code generation, file edits, and command execution / 实际代码生成、文件编辑和命令执行
```

DeepSeek is required for planning, task decomposition, architecture notes, code review, error analysis, and Codex prompt generation whenever AgentLab is active, including simulations and small tasks. Codex Plus performs actual source edits and project commands. See `OPERATING_MODEL.md`.

DeepSeek 负责规划、任务分解、架构笔记、代码审查、错误分析和 Codex 提示词生成——只要 AgentLab 激活就必须使用，包括模拟和小任务。Codex Plus 执行实际的源码编辑和项目命令。详见 `OPERATING_MODEL.md`。

---

## Project Structure / 项目结构

```text
AgentLab/
├── agent_runtime/          # Core runtime: CLI, brain governor, task router, LLM provider
│                           # 核心运行时：CLI、大脑治理、任务路由、LLM 提供者
├── agent_templates/        # 8 agent role prompts and report formats
│                           # 8 个 Agent 角色提示词和报告格式
├── config/                 # YAML policies: routing, budget, models, validation gates
│                           # YAML 策略：路由、预算、模型、验证门禁
├── projects/               # Per-project memory docs and task run records
│                           # 每个项目的记忆文档和任务运行记录
├── web_ui/                 # Static status dashboard (zero dependencies)
│                           # 静态状态看板（零依赖）
├── scripts/                # Git hooks and automation
│                           # Git 钩子和自动化脚本
├── agentlab.sh             # One-command CLI entrypoint
│                           # 一键 CLI 入口
├── DRIVER_PROTOCOL.md      # Protocol for external AIs to drive AgentLab
│                           # 外部 AI 驱动 AgentLab 的协议
└── OPERATING_MODEL.md      # Split-brain operating rules
                            # 双脑运行规则
```

---

## 8 Agents / 8 个智能体

| Agent / 智能体 | Role / 角色 | Provider / 提供者 | Permissions / 权限 |
|---|---|---|---|
| **Supervisor** | 协调范围、路由、Token 预算、停止规则 | DeepSeek | 只读 |
| **RepoScout** | 仓库结构扫描和上下文映射 | DeepSeek | 只读 + shell 检查 |
| **Researcher** | 外部信息/文档研究 | DeepSeek | 只读 + 可浏览 |
| **InterfaceMapper** | 接口、契约、边界映射 | DeepSeek | 只读 + shell 检查 |
| **Coder** | 实际代码编辑、文件变更、项目命令 | **Codex Plus** | 可写源码 + 可执行 |
| **CodexPromptGenerator** | 为 Codex 生成实现提示词 | DeepSeek | 只读 |
| **TesterAuditor** | 验证实际行为 + diff 审计 | DeepSeek | shell 验证命令 |
| **Archivist** | 项目记忆归档和延续性更新 | DeepSeek | 可写 agent_docs |

Configuration / 配置入口: `config/agent_registry.yml` | Templates / 模板: `agent_templates/*.md`

---

## Task Routing / 任务路由

5 route profiles based on keyword heuristics / 5 种基于关键词启发式的路由配置：

| Route / 路由 | Trigger / 触发条件 | Agents / 智能体 |
|---|---|---|
| `small_task` | Default / 默认 (<800 chars) | Supervisor → Coder → TesterAuditor |
| `medium_task` | >800 chars / 字符 | +RepoScout +Archivist |
| `interface_sensitive_task` | api/schema/protocol/db/ui 等 | +InterfaceMapper |
| `research_sensitive_task` | latest/docs/pricing/regulation 等 | +Researcher |
| `large_or_risky_task` | architecture/refactor/security 或 >2500 chars | 全 7 个 agent / all 7 agents |

Principle: **smallest safe route** / 原则：**最小安全路线**。

---

## One-Command CLI / 一键 CLI

From the AgentLab root / 从 AgentLab 根目录：

```bash
# Initialize a new task / 初始化新任务
./agentlab.sh init-task --project <Project> --task-id task_0007

# Build workflow plan (local only, no API call) / 生成工作流计划（纯本地，不调 API）
./agentlab.sh prepare --project <Project> --task-id task_0007 --write-plan

# Check task status / 查看任务状态
./agentlab.sh status --project <Project> --task-id task_0007

# Run a brain agent (dry-run by default, --execute to call API) / 运行大脑层 Agent
./agentlab.sh run-agent Supervisor --project <Project> --task-id task_0007 --execute

# Check brain governance (token budgets per agent) / 查看大脑治理状态
./agentlab.sh brain-status --project <Project> --task-id task_0007

# List configured models/providers / 列出已配置的模型/提供者
./agentlab.sh models

# View execution policy / 查看执行策略
./agentlab.sh policy-status --project <Project>

# Log an event to development/dialogue/cost ledgers / 记录事件
./agentlab.sh log-event --project <Project> --task-id task_0007 --agent Coder --summary "..." --files-changed "..."

# Request traversal permission from brain governor / 请求大脑遍历权限
./agentlab.sh request-traversal RepoScout --project <Project> --task-id task_0007 --scope full_repo --full-repo --reason "Need initial repo map"

# Request coder quota decision / 请求 Coder 配额决策
./agentlab.sh request-coder-quota --project <Project> --task-id task_0007 --reason "Codex quota may be insufficient"
```

`run-agent` is dry-run by default. It calls the configured model API only when you pass `--execute`.

`run-agent` 默认 dry-run，仅当传入 `--execute` 时才调用模型 API。

---

## Driver Protocol / 驱动协议

Any external AI (Codex Plus, Claude, IDE assistants) can drive AgentLab as a thin relay.
Read `DRIVER_PROTOCOL.md` for the full 7-step protocol.

任何外部 AI（Codex Plus、Claude、IDE 助手）都可以作为轻量中继驱动 AgentLab。完整 7 步协议见 `DRIVER_PROTOCOL.md`。

The key rule / 核心规则：
- **External AIs do NOT think — AgentLab's brain (DeepSeek) does.** / **外部 AI 不思考 — AgentLab 的大脑（DeepSeek）来思考。**
- External AIs only transcribe user requests, execute the Coder phase, and relay decisions. / 外部 AI 仅转录用户请求、执行 Coder 阶段、中继决策。
- If DeepSeek is unavailable, AgentLab blocks and asks the user — no silent simulation. / 如果 DeepSeek 不可用，AgentLab 阻止并询问用户——不允许静默模拟。

---

## Brain Governance / 大脑治理

- Token budgets per agent phase (warning at 90%, stop at 115%) / 每个 Agent 阶段的 Token 预算（90% 警告，115% 停止）
- Full-repo traversal requires explicit approval / 全仓库遍历需要显式批准
- Loop detection: 3+ repeated similar decisions → stop and replan / 循环检测：3 次以上重复相似决策 → 停止并重新规划
- All decisions written to `brain_decisions.yml` / 所有决策写入 `brain_decisions.yml`
- User decisions written to `USER_DECISION_REQUIRED.md` / 用户决策写入 `USER_DECISION_REQUIRED.md`

---

## Audit Trail Per Task / 每条任务的审计追踪

```
runs/task_xxxx/
├── user_request.md          # User's natural-language task / 用户自然语言任务
├── workflow_plan.yml        # Route + token budgets + validation gates / 路由 + 预算 + 门禁
├── supervisor_plan.md       # Scope, route, budget table, risks / 范围、路由、预算表、风险
├── reposcout_report.md      # Repository context / 仓库上下文
├── research_notes.md        # External research findings / 外部研究结果
├── interface_map.md         # Interface boundaries / 接口边界
├── implementation_report.md # Changed files, commands, backend / 变更文件、命令、后端
├── validation_report.md     # Tester/Auditor validation / 测试/审计验证
├── audit_report.md          # Diff audit findings / Diff 审计发现
├── archive_update.md        # Project memory updates / 项目记忆更新
├── brain_decisions.yml      # All governance decisions / 所有治理决策
├── cost_ledger.yml          # Token cost accounting / Token 成本记账
├── state.yml                # Task state machine / 任务状态机
└── USER_DECISION_REQUIRED.md  # When user must decide / 需要用户决策时
```

---

## Local Status UI / 本地状态界面

AgentLab has a dependency-free static status board / AgentLab 有一个零依赖的静态状态看板：

```text
web_ui/index.html
```

Shows agent state, route, provider, ownership, edit rights, token budget, and recent events.

显示 Agent 状态、路由、提供者、所有权、编辑权限、Token 预算和最近事件。

---

## Version Control / 版本控制

This repo is version-controlled on GitHub / 本仓库在 GitHub 上进行版本控制：

```text
https://github.com/Kidrage/AgentLab
```

After any meaningful change, commit and push (auto-push via post-commit hook) / 每次有意义的修改后提交并推送（通过 post-commit 钩子自动推送）：

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
| 1.0 | 2026-05-30 | Initial release: 8-agent multi-agent workflow, split-brain architecture (DeepSeek + Codex Plus), 5 route profiles, token budget governance, brain governor, loop detection, local status UI, driver protocol for external AI, auto-push git hook / 初始发布：8 Agent 多智能体工作流、双脑架构（DeepSeek + Codex Plus）、5 种路由配置、Token 预算治理、大脑治理、循环检测、本地状态界面、外部 AI 驱动协议、自动推送 Git 钩子 |