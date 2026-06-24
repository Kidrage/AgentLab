# AgentLab M2 主线修复阶段总结报告 (M2-0 to M2-11)

## 1. 概述 (Overview)

在 AgentLab 的 M2 阶段中，我们成功完成了基础 Runtime 的彻底重构与扩展。从底层环境检测、路由引擎升级，到全局控制流的可观测性及配置中心改造，最终构建了强大的 TUI（终端用户界面）与 WebUI 大盘监控面板。M2 主线的核心目标是将早期实验性的 Agent 协同机制，转化为一套工程化、具备严格管控、支持多执行器（Multi-Worker）协作的 **Agent 操作系统**。

## 2. 核心模块与里程碑总结 (Milestones)

### M2-0: Runtime Hygiene & Safety Baseline (运行时卫生与安全基线)
建立统一的环境安全底线。
- 新增 `agent_runtime/run_task.py`，构建标准化入口。
- 实现安全边界检查，限制了非受信任的本地操作与资源占用。

### M2-1 ~ M2-1.7: Local Worker Registry & Capability Engine (本地执行器注册与能力引擎)
将各种不同的 AI 工具（如 Claude Code, Aider, OpenDevin, Cursor）统一抽象为 “执行器” (Worker)。
- 构建了 `Worker Registry`，实现自动化发现（Agent Doctor）、安装与心跳检测。
- 引入 **CLI 拦截校验**（CLI Invocation Contract Validator），保证执行器命令合法。
- 新增 **缓存感知引擎** (Cache-Aware Engine) 与 **MCP 技能网关** (Capability Broker)。

### M2-2 & M2-3: 9-Role Matrix & Performance Ledger (角色矩阵与绩效账本)
- **能力矩阵（9-Role Requirements）**：将任务细分为 Supervisor, RepoScout, Coder, TesterAuditor 等九大角色，并与具体的 Worker 能力建立映射。
- **绩效账本（Performance Ledger）**：引入基于历史任务执行结果的胜率/失败率记录，作为智能调度的量化依据。

### M2-4 & M2-5: Role Assignment Router v2 & Config Center v2 (动态路由调度与配置中心)
- **Role Assignment Router v2**：替代硬编码的角色绑定，转为基于策略（Tier, Cost, Capability, History）进行动态动态博弈路由选型。
- **Config Center v2**：构建了多层级、可聚合的 YAML 配置文件体系，并实现了运行时动态重载与严格验证。

### M2-6 & M2-7: Cost & Approval System & Observability (成本管控、审批系统与可观测性)
- **审批拦截门（Approval Gate）**：高危或超出预算的操作触发审批流，支持 CLI 层面的挂起（suspend）与唤醒。
- **可观测时间线（Timeline & Observability）**：分离 stdout 与机器级数据流，将事件追踪转化为标准 JSONL (`timeline.jsonl`) 以支持分析回放。

### M2-8 & M2-9: Control Panel & Assistant Modes (控制台面板与 AI 助理交互)
- **全局控制中心（Control Panel）**：支持一键开关 Worker、禁用某项技能或调整全局并发能力。
- **智能交互终端（Assistant Modes）**：引入 `./agentlab.sh ask` 等助理命令，通过查询 `state.yml` 结合大模型给出具有项目状态“锚定”（Grounded）且无幻觉的决策解释。

### M2-10 & M2-11: TUI & WebUI (终端面板与前端仪表盘)
将运行时的所有控制抽象为了直观的操作大盘。
- **M2-10 TUI**：通过 `rich` / `textual` 构建的无外设可视化终端（运行 `./agentlab.sh tui`），支持快捷键与表单级监控。
- **M2-11 WebUI**：基于 Python 标准库实现的轻量级无依赖本地浏览器仪表盘（运行 `./agentlab.sh webui`），通过 `127.0.0.1` 安全沙箱提供详尽的项目图表监控与操作审计界面。

---

## 3. 架构演进与技术亮点 (Architecture Highlights)

1. **协议层与执行层剥离**：彻底将 `Router`（决策）、`Provider`（大语言模型通信）和 `Worker`（具体终端命令）进行了解耦。
2. **纯粹的本地状态驱动 (State-Driven)**：采用 `.agentlab/` 以及 `projects/*/tasks/*/state.yml` 驱动控制流，任何时候挂起、崩溃都能精准恢复。
3. **安全设计原则 (Security-First)**：所有暴露的外部服务（包括 WebUI）严格绑定 Localhost，通过数据脱敏（Redaction）切断密钥在日志、UI 层的外泄风险。

## 4. 下一阶段指引 (Next Steps: M2-12)
目前的架构底座已经为上层目标驱动（Goal-Driven）协同做好了准备。
- **M2-12 / M2-12.5 (Goal / Mainline Command Bridge)**：桥接核心运行时机制与外部调度桥，打通基于长期目标（Goal）的全自动、无人值守的并发派发流程。
