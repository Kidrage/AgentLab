# LangGraph 开源调研 & AgentLab 整合评估报告

> 调研日期: 2026-05-31 | 任务: task_0014 | 执行者: DeepSeek (Supervisor/Researcher)

---

## 一、LangGraph 开源概况

### 1.1 基本信息

| 维度 | 数据 |
|---|---|
| 仓库 | [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) |
| Stars | **33,416** |
| Forks | 5,644 |
| Open Issues | 548 |
| License | **MIT** (商业友好) |
| 语言 | Python |
| 创建时间 | 2023-08-09 |
| 最新版本 | **1.2.2** (2026-05-26) |
| 总发布数 | 267 (极高频迭代) |
| Python 要求 | >=3.10 |

### 1.2 生态定位

LangGraph 定位为 **low-level orchestration framework for building stateful agents**。
它是 LangChain 生态的底层编排引擎，上层有:
- **Deep Agents**: 高级 agent 构建包 (planning + subagents + file system)
- **LangChain**: 组件集成层
- **LangSmith**: 可观测性 & 部署平台

LangGraph 灵感来源于 Google Pregel 和 Apache Beam，公开接口借鉴 NetworkX。

### 1.3 核心依赖

```
langchain-core >= 1.4.0       # 核心抽象 (Runnable, BaseMessage 等)
langgraph-checkpoint >= 4.1.0  # 检查点/持久化
langgraph-prebuilt >= 1.1.0    # 预构建 agent 模式
langgraph-sdk >= 0.3.0         # LangSmith 部署 SDK
pydantic >= 2.7.4              # 数据验证 (与 AgentLab 一致)
xxhash >= 3.5.0                # 高性能哈希
```

### 1.4 核心架构概念

```
StateGraph (Builder)          # 声明式图构建器
  ├── State Schema            # TypedDict + Annotated[type, reducer]
  ├── Nodes                   # State → Partial<State> 的函数
  ├── Edges                   # 固定边 / 条件边
  ├── Channels                # 状态通道 (LastValue, BinaryOp, Ephemeral...)
  └── Managed Values          # 托管值 (如长期记忆)
       │
       ▼ .compile()
CompiledStateGraph (Pregel)   # 基于 Pregel 的执行引擎
  ├── invoke() / ainvoke()
  ├── stream() / astream()
  ├── Checkpointer            # 持久化状态快照
  ├── Interrupt               # Human-in-the-loop
  └── Memory (short-term + long-term)
```

关键抽象:
- **StateGraph**: 声明式 builder，节点通过读写共享 State 通信
- **State = TypedDict + Reducer**: 每个 key 可标注 reducer 函数来合并多节点写入
- **Pregel Runtime**: 基于超步 (superstep) 的批量同步执行模型
- **Checkpoint**: 每次超步后自动持久化状态，支持故障恢复
- **Interrupt**: 在任意节点暂停执行，等待人工审核/修改状态后继续
- **Command/Send**: 动态路由，支持并行 fan-out

---

## 二、AgentLab 当前架构回顾

### 2.1 执行模型 (线性流水线)

```
Supervisor → RepoScout → Researcher → InterfaceMapper
     → Coder → TesterAuditor → Verifier → Archivist
```

- 每个 agent 角色是一个 LLM 调用，生成 Markdown 报告文件
- 下游 agent 通过读取上游报告文件获取上下文
- **状态传递介质: 文件系统** (`projects/<Project>/runs/<task_id>/`)
- Coder 可通过 `apply_patch` 机制修改源代码

### 2.2 核心组件

| 组件 | 职责 | 文件 |
|---|---|---|
| WorkflowPlan | 任务计划 (Pydantic) | `schemas.py` |
| TaskRouter | 关键词路由 (small/medium/large) | `task_router.py` |
| BrainGovernor | Token 预算 + 循环检测 + 遍历决策 | `brain_governor.py` |
| AgentRunner | LLM 调用 + Patch 应用 | `agent_runner.py` |
| BudgetPlanner | Token 预算估算 | `budget_planner.py` |
| StateStore | 文件系统状态读写 | `state_store.py` |
| CostTracker | 成本流水账 | `cost_tracker.py` |

### 2.3 核心数据模型

```python
WorkflowPlan:   project, task_id, route, token_budgets, included_agents
TaskState:      current_agent, completed_agents, reports, status
AgentRoute:     task_size, agents[], rationale, skipped_agents
BrainDecision:  decision_type, decision, approved_scope, token_budget
TokenBudget:    phase, estimated_*, warning_threshold, stop_threshold
```

---

## 三、概念映射分析

### 3.1 核心映射表

| LangGraph 概念 | AgentLab 当前实现 | 映射难度 | 说明 |
|---|---|---|---|
| **StateGraph** | WorkflowPlan + TaskState | 🟡 中 | 需要将 YAML 文件系统状态迁移为 TypedDict State |
| **State Schema** | 无统一 schema | 🔴 高 | 核心设计工作：定义 AgentLab 的 State 结构 |
| **Nodes** | Agent 角色 (Supervisor, Coder...) | 🟢 低 | 天然 1:1 映射 |
| **Edges (固定)** | AgentRoute.agents[] 顺序 | 🟢 低 | 当前线性流水线直接用固定边 |
| **Edges (条件)** | 无 (TaskRouter 仅预编译时路由) | 🟡 中 | 引入条件边后可在运行时动态分支 |
| **Channels + Reducer** | 无 (agent 间无状态合并) | 🟡 中 | 需设计每个 state key 的合并策略 |
| **Checkpoint** | 文件系统报告文件 | 🟢 低 | LangGraph 内置 InMemorySaver / SqliteSaver |
| **Memory** | agent_docs/ 项目记忆 | 🟡 中 | LangGraph Store API 可承载长期记忆 |
| **Interrupt (HITL)** | `USER_DECISION_REQUIRED.md` | 🟢 低 | 语义完美匹配，LangGraph 更优雅 |
| **Pregel Runtime** | brain_governor 遍历决策 | 🔴 高 | 执行引擎完全不同，但可替换 |
| **Stream** | 无 | 🟢 低 | 增值功能，可逐步流式输出 agent 进度 |
| **Subgraph** | 无 | 🟢 低 | 可用于嵌套子任务 (如 Researcher 内部多轮搜索) |
| **LangSmith** | `brain_decisions.yml` + `cost_ledger.yml` | 🟢 低 | 可观测性大幅升级 |

### 3.2 难度总结

- 🔴 高难度 (2项): State Schema 设计、Pregel Runtime 替换
- 🟡 中等难度 (4项): StateGraph 组装、条件边、Reducer、长期 Memory
- 🟢 低难度 (7项): Nodes、固定边、Checkpoint、Interrupt、Stream、Subgraph、LangSmith

**加权平均: 整合难度 = 中等偏低 (~4/10)**

---

## 四、整合方案设想

### 4.1 最小可行集成 (MVP)

保留 AgentLab 的业务语义，用 LangGraph 替换编排层：

```python
from langgraph.graph import StateGraph
from langgraph.checkpoint.memory import InMemorySaver
from typing_extensions import TypedDict, Annotated
from operator import add

class AgentLabState(TypedDict):
    # 任务元信息
    project: str
    task_id: str
    execution_backend: str

    # Agent 报告 (每个 agent 追加)
    reports: Annotated[dict, lambda a, b: {**a, **b}]

    # Brain 决策日志
    brain_decisions: Annotated[list, add]

    # Token 追踪
    token_usage: Annotated[dict, lambda a, b: {**a, **b}]
    budgets: dict

    # 文件变更追踪
    files_changed: Annotated[list, add]

    # 人工决策标记
    user_decision_pending: bool
    user_decision: str

    # 执行状态
    current_phase: str  # "planning" | "coding" | "auditing" | "complete"
    errors: Annotated[list, add]

def supervisor_node(state: AgentLabState) -> dict:
    """调用 LLM 生成 supervisor_plan.md，写入 state['reports']"""
    ...

def coder_node(state: AgentLabState) -> dict:
    """调用 LLM 生成实现代码，通过 apply_patch 修改源文件"""
    ...

# 构建图
builder = StateGraph(AgentLabState)
builder.add_node("supervisor", supervisor_node)
builder.add_node("reposcout", reposcout_node)
builder.add_node("researcher", researcher_node)
builder.add_node("coder", coder_node)
builder.add_node("tester", tester_node)
builder.add_node("verifier", verifier_node)
builder.add_node("archivist", archivist_node)

# 线性流水线 (MVP)
builder.add_edge("supervisor", "reposcout")
builder.add_edge("reposcout", "researcher")
builder.add_edge("researcher", "coder")
builder.add_edge("coder", "tester")
builder.add_edge("tester", "verifier")
builder.add_edge("verifier", "archivist")
builder.add_edge("archivist", END)

# 可选: 条件中断 (人工审核)
builder.add_conditional_edges("coder", should_interrupt, {
    "continue": "tester",
    "pause": "human_review"
})

checkpointer = InMemorySaver()
app = builder.compile(checkpointer=checkpointer)

# 执行
result = app.invoke({"project": "AgentLab", "task_id": "0014"})
```

### 4.2 迁移路径建议

**Phase 1 — 影子模式 (2-3天)**
- 在现有 AgentLab 旁搭建 LangGraph 等价流水线
- 双写结果 (文件系统 + LangGraph State)
- 验证语义一致性

**Phase 2 — 替换编排层 (3-5天)**
- 将 `agent_runner.py` 重构为 LangGraph node 函数
- 用 LangGraph Checkpoint 替换文件系统状态传递
- 保留文件系统报告输出 (兼容现有工具链)

**Phase 3 — 启用高级特性 (按需)**
- 条件路由: TaskRouter 动态分支
- Human-in-the-loop: 用 `interrupt()` 替换 `USER_DECISION_REQUIRED.md`
- Stream: 实时输出 agent 进度
- Subgraph: 嵌套子任务 (如 Coder 内部的 plan→edit→verify 循环)
- LangSmith 集成: 可观测性

### 4.3 兼容性分析

| 维度 | 兼容性 | 说明 |
|---|---|---|
| Python 版本 | ✅ | AgentLab 已有 .venv, LangGraph 需要 >=3.10 |
| Pydantic | ✅ | 双方都使用 Pydantic v2 |
| LLM Provider | ⚠️ | LangGraph 通过 langchain-core 调用 LLM，需适配 AgentLab 的多 provider 机制 |
| 文件系统 | ✅ | 可保留文件系统输出作为 side effect |
| 配置系统 | ✅ | LangGraph 不侵入配置层 |
| Agent 模板 | ✅ | agent_templates/*.md 可保持不变 |

---

## 五、工程分工判断

### 5.1 本任务（调研+评估）适合谁？

**结论: DeepSeek (Cline) 更适合**

理由:

| 评判维度 | DeepSeek (Cline) | Codex | 分析 |
|---|---|---|---|
| 架构理解 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | 需要同时理解两个系统的抽象层，做概念映射 |
| 权衡决策 | ⭐⭐⭐⭐⭐ | ⭐⭐ | 需要判断哪些 LangGraph 功能引入、哪些不引入、MVP 范围 |
| 调研报告质量 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | 需要结构化写作、对比分析 |
| 代码探索 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 双方都能读代码，Codex 更偏编辑 |

### 5.2 后续实施阶段适合谁？

| 阶段 | 推荐执行者 | 原因 |
|---|---|---|
| State Schema 设计 | DeepSeek | 架构设计，需权衡 reducer 策略 |
| 图拓扑设计 (nodes/edges) | DeepSeek | 规划型工作 |
| 单个 node 函数实现 | **Codex** | 大量重复性编码 |
| langchain-core 适配层 | **Codex** | 需要写大量胶水代码 |
| 测试 & 验证 | **Codex** | 写测试、跑测试 |
| 文档更新 | DeepSeek | 需要理解全局变更 |

### 5.3 推荐分工模式

```
DeepSeek (Supervisor/Architect):
  - 设计 AgentLabState schema
  - 设计图拓扑
  - 定义每个 node 的输入/输出契约
  - Review Codex 生成的代码
  - 写架构文档

Codex (Coder):
  - 实现 node 函数骨架
  - 实现 langchain-core provider 适配
  - 写单元测试
  - 写迁移脚本
```

---

## 六、风险与建议

### 6.1 关键风险

| 风险 | 严重度 | 缓解措施 |
|---|---|---|
| langchain-core 依赖太重 | 🟡 中 | LangGraph 可脱离 LangChain 独立使用；仅引入必要的 langchain-core 子包 |
| Pregel 执行模型学习曲线 | 🟡 中 | MVP 阶段只用线性图，渐进引入高级特性 |
| LLM Provider 适配 | 🟡 中 | 通过 langchain-core 的 ChatModel 接口统一，AgentLab 现有 provider 配置可注入 |
| 版本迭代快 (267 releases) | 🟢 低 | 锁定 `langgraph>=1.2,<1.3`，定期跟进 changelog |
| 社区 lock-in | 🟢 低 | MIT 协议，核心抽象 (StateGraph + Pregel) 稳定，可 fork |

### 6.2 建议

1. **立即采用**: LangGraph 是 AgentLab 骨架的合适基础层。其 `StateGraph` + `Node` + `Checkpoint` 模型与 AgentLab 的 agent 流水线天然契合。

2. **渐进迁移**: 不要一次性重写。先在影子模式下验证概念，再逐步替换。

3. **保持 AgentLab 简洁性**: 不要引入 LangGraph 的全部功能。MVP 阶段只用:
   - `StateGraph` + 固定边 (线性流水线)
   - `InMemorySaver` 检查点
   - 保留文件系统报告作为 side effect
   - 暂不用: 条件边、Subgraph、LangSmith、Stream

4. **DeepSeek 主导设计，Codex 执行编码**: 遵循 AgentLab 的 brain/coder 分工模型，本任务由 DeepSeek 完成调研与方案设计，实施阶段由 Codex 落地代码。

---

## 七、参考资源

- LangGraph 源码: `langgraph/graph/state.py` (StateGraph + CompiledStateGraph)
- LangGraph 文档: https://docs.langchain.com/oss/python/langgraph/overview
- AgentLab 核心: `agent_runtime/schemas.py`, `agent_runner.py`, `brain_governor.py`
- 相关任务: task_0009 (初次架构), task_0010-0013 (迭代优化)