# 竞品研究笔记：AgentLab 同类产品分析

## 研究方法
基于已知的行业生态和实践，分析多 Agent 协作开发框架的代表性产品。

---

## 1. GPT-Engineer
**类型**：自然语言→代码生成
**核心优点**：
- 用户只需一句话描述，自动生成完整项目骨架
- 支持逐步澄清需求（交互式追问缺失信息）
- 文件级 diff 展示，变更透明

**可借用到 AgentLab**：
- 交互式需求澄清：Supervisor 在 intake 阶段可以主动询问缺失信息（当前是纯被动接收 user_request）
- 分步确认机制：在重大操作前暂停需要用户确认

---

## 2. MetaGPT
**类型**：多 Agent 角色扮演框架（SOP-based）
**核心优点**：
- 定义结构化 Agent 角色（PM、Architect、Engineer、QA）模拟软件公司
- 标准化工作流（SOPs），每个角色有明确的输入/输出文档
- 共享消息池，Agent 间通过结构化文档通信
- 支持记忆和知识检索（RAG）

**可借用到 AgentLab**：
- SOP 强制执行：Agent 间有规定的文档传递链路（AgentLab 已有类似概念但可以更严格）
- 结构化中间产物：如要求 Supervisor 输出 JSON/YAML 格式的任务分解（而不仅是 Markdown）
- 知识库/RAG：为 Researcher Agent 增加向量检索能力

---

## 3. AutoGPT
**类型**：自主 Agent 循环
**核心优点**：
- 自主循环执行（Plan → Execute → Observe → Replan）
- 支持长任务链，自动分解子任务
- 插件生态：浏览器、文件系统、代码执行器

**可借用到 AgentLab**：
- 子任务自动分解：Supervisor 将大任务拆成子任务链，逐个推进
- Agent 自我纠错循环：TesterAuditor 发现的问题自动触发 Coder 修复循环（当前需手动触发）
- 插件系统：Agent 功能通过插件扩展而非硬编码

---

## 4. Aider
**类型**：AI 结对编程工具
**核心优点**：
- 直接在终端中交互编辑代码，支持多文件 diff
- 极简设计：一条命令 + 一个 prompt
- 优秀的 token 效率：只发送相关文件上下文
- 自动 git commit 每个变更
- 支持多种 LLM 后端

**可借用到 AgentLab**：
- 自动 git commit：Coder 每次编辑后自动 commit（AgentLab 手动 log-event 可以改进）
- 上下文裁剪：RepoScout 可以精确识别相关文件而非全仓库扫描
- 多 LLM 后端支持（AgentLab 已有部分实现）

---

## 5. CrewAI
**类型**：多 Agent 协作编排
**核心优点**：
- 简洁的 Agent 定义（role + goal + backstory）
- Task 定义支持上下文传递和依赖关系
- 支持顺序执行和层级执行
- Agent 间对话可见

**可借用到 AgentLab**：
- Agent 间依赖管理：显式定义"TesterAuditor 依赖 Coder 完成"
- 层级执行：Supervisor 管理 sub-agent，可嵌套
- 对话可见性：Agent 间推理过程可见（AgentLab 当前以报告为主）

---

## 6. OpenDevin / SWE-Agent
**类型**：代码仓库级自主开发 Agent
**核心优点**：
- 直接操作完整代码仓库
- 集成终端、浏览器、文件编辑器
- 任务完成评估机制
- 沙箱执行环境

**可借用到 AgentLab**：
- 沙箱执行：Coder 在隔离环境中运行命令，防止破坏项目
- 任务评估器：TesterAuditor 自动运行测试套件验证（当前是手动验证）
- Docker/container 集成：

---

## 7. Devin (Cognition AI)
**类型**：全栈自主开发 AI
**核心优点**：
- 自主理解错误并修复
- 可视化开发过程（用户可观察 Agent 工作）
- 集成开发环境（IDE + 终端 + 浏览器）

**可借用到 AgentLab**：
- 可视化工作流：Web UI 展示当前 Agent 工作状态
- 错误自愈：Coder 遇到错误自动分析并修复
- 实时进度展示

---

## 8. TaskWeaver (Microsoft)
**类型**：数据驱动的 Agent 框架
**核心优点**：
- 结构化数据感知（DataFrame、表格等）
- 将用户请求转换为可执行代码
- 多轮对话式任务规划

**可借用到 AgentLab**：
- 会话状态保持：多个 Agent 协作保持上下文连贯
- 规划->代码映射：将自然语言规划映射为具体执行步骤

---

## 整合建议：AgentLab 待优化方向

| 优先级 | 优化方向 | 借鉴来源 | 改动难度 |
|--------|---------|---------|---------|
| P0 | **交互式需求澄清** — Supervisor 主动追问缺失信息 | GPT-Engineer | 低（改 Supervisor prompt） |
| P0 | **自动修复循环** — Tester 发现问题自动触发 Coder 修复 | AutoGPT, Devin | 中（修改 task_router 逻辑） |
| P1 | **SOP 强制执行** — 检查前置报告是否存在才允许后续 Agent | MetaGPT | 低（已有部分实现） |
| P1 | **Agent 间依赖 DAG** — 显式定义执行依赖 | CrewAI | 中（修改 workflow_plan schema） |
| P1 | **自动 git commit** — Coder 每次编辑后自动 commit | Aider | 低（post-commit hook 已有） |
| P2 | **沙箱执行** — Docker 环境运行 Coder | OpenDevin | 高 |
| P2 | **向量记忆/RAG** — Research Agent 检索知识库 | MetaGPT | 中 |
| P2 | **子任务链分解** — 大任务拆成子任务顺序执行 | AutoGPT | 高（需重构 workflow_plan） |
| P3 | **实时进度展示** — Web UI 显示当前 Agent 状态 | Devin | 中（web_ui 已有基础） |
| P3 | **插件生态** — 功能可插拔 | AutoGPT | 高 |

## 总结

AgentLab 当前已具备多 Agent 协作的核心骨架（路由、预算、审计、大脑治理），相比同类产品差异化优势在于：**双脑架构的保守安全策略**、**严格的 Token 预算治理**、**完整的审计追踪**。

最值得优先引入的改进：**交互式需求澄清**（让 Supervisor 更聪明地收集任务信息）和 **自动修复循环**（Tester→Coder 闭环），这两个改动成本低、收益高。