# AgentLab / 智能体实验室

> Language / 语言:
> [English](docs/README.en-US.md) |
> [中文](docs/README.zh-CN.md)
>
> Standalone guides / 独立说明：
> [English guide](docs/README.en-US.md) ·
> [中文说明](docs/README.zh-CN.md)

AgentLab is a local-first AI Production OS and Project-to-Revenue OS under active development.
It is **not** a replacement for Codex, Claude Code, Cline, Hermes, OpenClaw, or other executor/front-end agents.
AgentLab is the backend truth source that keeps long-running projects governed, inspectable, recoverable, and evidence-backed.

AgentLab 是一个本地优先的 AI Production OS / Project-to-Revenue OS，仍在持续开发中。
它不是 Codex、Claude Code、Cline、Hermes、OpenClaw 或其他前端执行器的替代品。
AgentLab 的定位是后端事实源：让长期项目保持可治理、可检查、可恢复、可审计，并用证据闭环。

Repository / 仓库：`https://github.com/Kidrage/AgentLab` · branch `main`

Language preference / 语言偏好：`config/language_policy.yml` or `AGENTLAB_LANGUAGE` (`en-US` / `zh-CN`).

---

## What AgentLab Does / AgentLab 做什么

```text
user requirement / 用户需求
-> mission / task contract
-> project roadmap / 项目路线图
-> phase plan / 阶段计划
-> task packet / 任务包
-> local or external executor handoff / 本地或外部执行器交接
-> artifact and evidence ingestion / 产物与证据摄入
-> review / retry / recovery
-> phase acceptance / 阶段验收
-> project memory update / 项目记忆更新
-> delivery package / 交付包
-> future asset, production, revenue, and SOP loops
```

Default design is local-first and approval-gated. Real external execution, skill installation, network access, platform posting, and public server exposure stay disabled unless policy and explicit user approval allow them.

默认设计是本地优先、审批门控。真实外部执行、技能安装、网络访问、平台发布和公开服务绑定默认关闭，只有策略允许且用户明确批准后才可执行。

---

## Current Baseline / 当前基线（2026-06-29）

| Item / 项 | Value / 值 |
|---|---|
| Branch / 分支 | `main` |
| Local root / 本地根目录 | `Desktop/AgentLab` |
| Latest mainline / 最近主线 | `9c65d95` media generation routing · `2e8ff83` root project handoff |
| Test baseline / 测试基线 | `1906 passed, 2 skipped` (full pytest) |
| Product stage / 产品阶段 | M-series alignment (M0/M1 consolidation before M2/M3) |

### Recent Updates / 近期更新

- **Media generation routing / 媒体生成路由**：`media_generation_router.py` + `config/media_generation_backends.yml`
- **Domain-aware creative routing / 领域感知创作路由**：`config/domain_route_packs.yml` for longform fiction, research, codebase, and media tasks
- **CLI modularization / CLI 模块化**：worker, hygiene, capability, routing, external project, protocol, and role capability commands extracted
- **Repository handoff / 仓库级交接**：`./agentlab.sh repository-handoff --repo <path> --write` → `PROJECT_HANDOFF.md`
- **Executor refresh / 执行器更新**：`agy` as Coder, expanded Hermes model groups, updated worker invocation contracts
- **Creative project governance / 创作项目治理**：`project_artifact_index.yml`, per-project handoff, artifact stewardship gates

### Active Creative Projects / 活跃创作项目（本地，不入 GitHub）

| Project | Path | Notes |
|---|---|---|
| Crown_of_Ash | `projects/Crown_of_Ash/` | Fantasy longform: chapters, outlines, runs, project_brain |
| NovelGen | `projects/NovelGen/` | Novel generation pipeline and chapter output |
| novel-moon-in-seal | `projects/novel-moon-in-seal/` + `_shared/novel-moon-in-seal/` | Longform fiction + audio-drama assets |

These assets sync internally via TrueNAS and the 250 office runtime. They are **not** pushed to public GitHub.

这些项目资产通过 TrueNAS 与 250 办公区内部同步，不推送到公开 GitHub。

---

## Three-End Topology / 三端协作拓扑

```text
Local Mac (development source / 开发源)
  ├─ Git → GitHub (framework/code only / 仅框架代码)
  └─ rsync / truenas-sync → TrueNAS 10.147.17.hub (relay / 中转站)
        └─ SSH/rsync → 250 office 10.147.17.node (runtime workspace / 运行时工作区)
```

- **Scheme A (Git)**：`agent_runtime/`, `config/`, `tests/`, docs, acceptance fixtures
- **Scheme B (Rsync)**：`projects/` creative assets, `.agentlab/` runtime state, agent workspaces
- 250 remote / 250 远端：`ssh://admin@10.147.17.node:/home/admin/AgentLab`

Commercial project assets and credentials must never be pushed to external GitHub.

商业项目资产与凭证不得推送到外部 GitHub。

---

## M-Series Roadmap / M 系列路线图

AgentLab already has the P-series and S-series governance foundation. The next product mainline is M-series:

AgentLab 已通过 P 系列和 S 系列具备长期项目治理底座。下一条产品主线是 M 系列：

| Phase | Goal / 目标 |
|---|---|
| **M1** Project Governance Kernel | Long-running project governance + local CLI executor coordination / 长期项目治理与本地 CLI 执行器协作 |
| **M2** Operator OS | Transparent CLI/TUI/WebUI/assistant control plane / 透明操作控制面 |
| **M3** Project-to-Revenue OS | Business contracts, assets, production, revenue, CRM, SOP / 商业契约、资产、生产、收入、CRM、SOP |

Practical status: M-series alignment stage. Consolidate M0/M1 acceptance before M2/M3.

实际状态：M 系列对齐阶段。进入 M2/M3 前应先完成 M0/M1 验收收敛。

---

## 9-Agent Operating Model / 9 智能体运行模型

```text
T1 Brain / 大脑层:       Supervisor → Hermes (default) / DeepSeek API fallback
T2 Perception / 感知层:  RepoScout, Researcher, InterfaceMapper → Qwen
T3 Execution / 执行层:   Coder (agy / Claude Code), PromptEngineer → Qwen Coder
T4 Audit / 审核层:       TesterAuditor, Verifier → Qwen Flash/Plus / DeepSeek
T5 Archive / 归档层:     Archivist → Qwen Plus
```

Budget modes / 预算模式: `brain_allocated` (default), `max_quality`, `frugal`

Route profiles / 路由配置: `small_task`, `medium_task`, `interface_sensitive_task`, `research_sensitive_task`, `large_or_risky_task`, plus domain packs (`fiction_chapter_pipeline`, etc.)

Config / 配置：`config/agent_registry.yml`, `config/model_catalog.yml`, `config/domain_route_packs.yml`, `OPERATING_MODEL.md`

---

## Implemented Capabilities / 已实现能力

### Core Runtime / 核心运行时

- Local-first task state, project memory, run directories, evidence artifacts / 本地任务状态、项目记忆、运行目录、证据产物
- 14-node lifecycle with checkpoint/resume / 14 节点生命周期与检查点恢复
- Brain governance: token budgets, loop detection, provider failover / 大脑治理：预算、循环检测、故障切换
- Artifact evidence gate, CostLedger v2, BudgetGate / 产物证据门禁、成本账本、预算门
- Guard system: atomic I/O, file locks, heartbeats, crash recovery / 守护：原子 IO、锁、心跳、崩溃恢复
- Task index, discovery, resume, repository handoff / 任务索引、发现、恢复、仓库级交接

### P/S-Series Foundations / P/S 系列底座

- **P0**: CostLedger, RepoManifest, CloneGuard, ResourceLedger, Pipeline Runner
- **P1**: External skill registry (disabled by default), ECC scan-only, external agent handoff
- **P2**: 3E Reviewer, Retry Manager, Context Governance, Failure Recovery stack
- **S7**: Long project orchestrator (`project-brain-init`, `project-plan`, `project-next`, `phase-accept`)
- **S8**: Executor connector loop (task packets, evidence ingestion, phase acceptance)
- **S9**: Capability fabric (mock-first, permission-gated)
- **S10**: Offline generalization eval suite + CI gates
- **S11**: Ops console snapshot (read-only, local-only)
- **S12**: Service factory planning (quote, timeline, delivery skeleton)

### Skills, Feedback, Integration / 技能、反馈、集成

- Skill lifecycle MVP + Skill Vault + Trace-to-Skill learning / 技能生命周期 + 技能库 + 轨迹学习
- Feedback loop: `task_events.jsonl`, decision cards, watchdog, webhooks / 反馈闭环
- MCP stdio tool server, Cline STDIO wrapper / MCP 工具服务
- Static Web UI status board + task details / 静态 Web UI 看板

Full capability list / 完整能力列表：see [`docs/README.zh-CN.md`](docs/README.zh-CN.md) or [`docs/README.en-US.md`](docs/README.en-US.md)

---

## Project Structure / 项目结构

```text
AgentLab/
├── agent_runtime/       # Core runtime / 核心运行时
├── agent_templates/     # 9 agent role prompts / 9 个 Agent 提示词
├── config/              # YAML policies / YAML 策略
├── skills/              # Skill lifecycle registry / 技能生命周期
├── projects/            # Per-project memory + runs (local-only assets) / 项目记忆与运行
├── _shared/             # Shared creative assets (e.g. novel-moon-in-seal) / 共享创作资产
├── tests/               # Integration + acceptance tests / 集成与验收测试
├── acceptance_runs/     # Offline acceptance artifacts / 离线验收产物
├── web_ui/              # Static status dashboard / 静态状态看板
├── docs/                # Specs and standalone READMEs / 规范与独立说明
├── agentlab.sh          # One-command CLI entrypoint / 一键 CLI 入口
├── PROJECT_HANDOFF.md   # Root project status dashboard / 根级项目状态看板
├── DRIVER_PROTOCOL.md   # External AI driver protocol / 外部 AI 驱动协议
└── OPERATING_MODEL.md   # Multi-tier operating rules / 分层运行规则
```

---

## Important Commands / 常用命令

```bash
# Health / 健康检查
./agentlab.sh doctor
./agentlab.sh policy-status --project AgentLab
./agentlab.sh models

# Task lifecycle / 任务生命周期
./agentlab.sh init-task --project <Project> --task-id task_0007
./agentlab.sh prepare --project <Project> --task-id task_0007 --write-plan
./agentlab.sh run-pipeline --project <Project> --task-id task_0007 --dry-run
./agentlab.sh status --project <Project> --task-id task_0007

# Long project / 长期项目
./agentlab.sh project-brain-init --project <Project>
./agentlab.sh project-next --project <Project>
./agentlab.sh phase-accept --project <Project>

# Handoff / 交接
./agentlab.sh repository-handoff --repo . --write

# Sync / 同步
./agentlab.sh migration-doctor --project AgentLab
./agentlab.sh truenas-status --project AgentLab
./agentlab.sh truenas-sync --project AgentLab --task-id <task_id> --dry-run

# Skills / 技能
./agentlab.sh skill-list --project AgentLab
./agentlab.sh capability-list
./agentlab.sh skill-import-url --project AgentLab --url "https://raw.githubusercontent.com/anthropics/skills/main/skills/skill-creator/SKILL.md" --allow-network

# Evaluation / 评估
./agentlab.sh eval-generalization --out acceptance_runs/s10_generalization_eval
./agentlab.sh ops-console-status --project AgentLab --out acceptance_runs/s11_dashboard
```

`run-agent` is dry-run by default; pass `--execute` to call model APIs.
`run-agent` 默认 dry-run，传入 `--execute` 才调用模型 API。

---

## Safety Model / 安全模型

AgentLab stays conservative by default / AgentLab 默认保持保守：

- No automatic external tool execution / 不自动执行外部工具
- No automatic skill installation / 不自动安装技能
- No automatic MCP server launch / 不自动启动 MCP 服务
- No automatic web crawling or platform posting / 不自动爬网或平台发布
- No public bind by default / 默认不公开绑定服务
- No credentials in project memory or handoffs / 不在记忆或交接中记录凭证
- No accepting external results without evidence and review / 无证据与审查不接受外部结果

---

## Version Control / 版本控制

```text
https://github.com/Kidrage/AgentLab
```

Auto-push via post-commit hook. Check `git status` before committing — never stage `.env` or credentials.

通过 post-commit 钩子自动推送。提交前检查 `git status`，不要暂存 `.env` 或凭证。

---

## Changelog / 更新日志

| Version | Date | Changes |
|---|---|---|
| **3.0** | 2026-06-29 | M-series alignment README refresh; media generation routing; domain-aware creative writing routes; CLI modularization; root `PROJECT_HANDOFF.md`; repository handoff command; three-end sync docs; creative project governance / M 系列对齐 README 刷新；媒体生成路由；领域感知创作路由；CLI 模块化；根级项目交接；三端同步文档；创作项目治理 |
| 2.3 | 2026-06-06 | Task snapshot, memory writer, artifact gate tests, Web UI refactor |
| 2.2 | 2026-06-05 | Closure hardening: doctor, lifecycle graph, artifact contract, task index |
| 2.1 | 2026-06-01 | 9-agent refactor: PromptEngineer + Archivist consolidation |
| 2.0 | 2026-05-31 | 9-agent tiered architecture, Guard, Provider Failover, Codex Full-Driver |
| 1.0 | 2026-05-30 | Initial 8-agent workflow, split-brain architecture, driver protocol |

---

## Source Documents / 来源文档

- Standalone READMEs / 独立说明：[`docs/README.zh-CN.md`](docs/README.zh-CN.md) · [`docs/README.en-US.md`](docs/README.en-US.md)
- Mainline status / 主线状态：[`docs/MAINLINE_BASELINE_STATUS.md`](docs/MAINLINE_BASELINE_STATUS.md)
- M-series handoff / M 系列交接：[`docs/AGENTLAB_M_SERIES_MAINLINE_HANDOFF.md`](docs/AGENTLAB_M_SERIES_MAINLINE_HANDOFF.md)
- Driver protocol / 驱动协议：[`DRIVER_PROTOCOL.md`](DRIVER_PROTOCOL.md)
- OpenClaw integration / OpenClaw 集成：[`docs/OPENCLAW_LOCAL_INTEGRATION.md`](docs/OPENCLAW_LOCAL_INTEGRATION.md)
- Skill distillation / 技能蒸馏：[`docs/SKILL_DISTILLATION.md`](docs/SKILL_DISTILLATION.md)