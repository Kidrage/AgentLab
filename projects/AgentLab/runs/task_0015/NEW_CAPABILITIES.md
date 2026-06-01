# LangGraph 骨架替换后：新特性与新能力

> 基于 task_0014 调研 & task_0015 MVP 实施
> 文档日期: 2026-05-31

---

## 概述

AgentLab 原先的流水线是一个**手工编排的线性序列**：用户逐次调用
`./agentlab.sh run-agent Supervisor` → `run-agent RepoScout` → ...
每个 agent 独立执行，之间通过**文件系统**（Markdown 报告文件）传递上下文。

替换为 LangGraph `StateGraph` 后，骨架获得了以下**全新的结构性能力**：

---

## 一、已实现（MVP）

### 1.1 内存在 State — 一站式状态总览

**之前**: 下游 agent 需要手动读取上游的报告文件来获取上下文。
```python
# old: 分散在多个文件中
run_dir / "supervisor_plan.md"
run_dir / "reposcout_report.md"
run_dir / "implementation_report.md"
...
```

**现在**: 所有 agent 共享同一个 `AgentLabState` TypedDict，在内存中流转。
```python
class AgentLabState(TypedDict, total=False):
    project: str
    task_id: str
    reports: Annotated[dict, merge_dicts]          # 所有 agent 报告汇聚
    token_usage: Annotated[dict, merge_dicts]       # 各 agent token 统计
    brain_decisions: Annotated[list, add]            # 决策日志累积
    files_changed: Annotated[list, add]              # 文件变更追踪
    validation_passed: Optional[bool]                # 验证结果
    errors: Annotated[list, add]                     # 错误聚合
    current_phase: str                               # 当前阶段
```

**价值**:
- 任何 agent 可以查看 `state["reports"]` 获取**所有上游 agent 的完整输出**，不需要逐个读文件
- `state["token_usage"]` 实时追踪每个 agent 的 token 消耗
- `state["errors"]` 自动聚合所有 agent 的错误信息

### 1.2 自动 State 合并 — Reducer 机制

**之前**: 没有任何状态合并机制 — 如果一个 agent 想追加信息到已有数据，只能手动读写文件。

**现在**: LangGraph 的 `Annotated[type, reducer]` 机制自动处理多节点写入冲突：
```python
reports: Annotated[dict, merge_dicts]          # 自动合并字典
brain_decisions: Annotated[list, add]          # 自动追加列表
files_changed: Annotated[list, add]            # 自动追加
errors: Annotated[list, add]                   # 自动追加
```

对比一下传统的写法：
```python
# old: 手动合并
existing_reports = yaml.safe_load(...)
existing_reports["Coder"] = "implementation_report.md"
yaml.dump(existing_reports, ...)

# new: LangGraph 自动处理
return {"reports": {"Coder": "implementation_report.md"}}  # reducer 自动 merge
```

### 1.3 一键启动完整流水线 — `run-pipeline`

**之前**: 需要手动逐个调用每个 agent：
```bash
./agentlab.sh run-agent Supervisor --task-id task_0001 --execute
./agentlab.sh run-agent RepoScout --task-id task_0001 --execute
./agentlab.sh run-agent Researcher --task-id task_0001 --execute
./agentlab.sh run-agent Coder --task-id task_0001 --execute
./agentlab.sh run-agent TesterAuditor --task-id task_0001 --execute
./agentlab.sh run-agent Verifier --task-id task_0001 --execute
./agentlab.sh run-agent Archivist --task-id task_0001 --execute
```

**现在**: 一条命令跑完整个流水线：
```bash
./agentlab.sh run-pipeline --task-id task_0001 --execution-backend langgraph
```

**输出示例**:
```
[LangGraph] Starting pipeline: Supervisor → RepoScout → Researcher → Coder → TesterAuditor → Verifier → Archivist
[LangGraph] Run dir: projects/AgentLab/runs/task_0001/

  [Supervisor] Running LLM model...
  [RepoScout] Running LLM model...
  [Researcher] Running LLM model...
  [Coder] Running LLM model...
  [TesterAuditor] Running LLM model...
  [Verifier] Running LLM model...
  [Archivist] Running LLM model...

[LangGraph] Pipeline complete.
[LangGraph] Phase: archiving
[LangGraph] Reports generated: 7
[LangGraph] Files changed: 3
[LangGraph] Validation passed: True
[LangGraph] Total tokens used: 45210
```

### 1.4 自动 Checkpoint — 故障恢复能力

**之前**: pipeline 中断后需要手动判断哪些 agent 已执行，从断点继续。

**现在**: LangGraph 的 `InMemorySaver`（或未来的 `SqliteSaver`）在每步后自动保存状态快照。
```python
checkpointer = InMemorySaver()
app = builder.compile(checkpointer=checkpointer)
# 如果在 Coder 阶段崩溃，状态已保存到 checkpoint
# 重跑时会从 Coder 阶段继续，而不是从头开始
```

### 1.5 声明式图拓扑 — 图就是文档

**之前**: agent 执行顺序隐藏在 shell 命令历史中。

**现在**: 图拓扑就是活文档：
```python
builder.add_edge("Supervisor", "RepoScout")
builder.add_edge("RepoScout", "Researcher")
builder.add_edge("Researcher", "Coder")
builder.add_edge("Coder", "TesterAuditor")
builder.add_edge("TesterAuditor", "Verifier")
builder.add_edge("Verifier", "Archivist")
builder.add_edge("Archivist", END)
```

一目了然，可直接导出让非技术人员理解。新增/删除 agent 只需改一行。

### 1.6 影子模式 — 零破坏性迁移

LangGraph 流水线**仍然写入所有文件系统报告**：
```
projects/AgentLab/runs/task_0015/
  ├── supervisor_plan.md          ← LangGraph node 写入
  ├── reposcout_report.md         ← LangGraph node 写入
  ├── implementation_report.md    ← LangGraph node 写入
  ├── ...
  ├── workflow_plan.yml
  ├── brain_decisions.yml
  └── state.yml
```

所有现有的 CLI 命令（`status`, `brain-status`, `harness-status` 等）继续正常工作。

---

## 二、已设计但未启用（Phase 2-3 规划）

### 2.1 条件路由 — 运行时动态分支

当前 TaskRouter 在**编译时**根据关键词确定 agent 列表。未来可以改为**运行时条件边**：

```python
def should_skip_research(state: AgentLabState) -> str:
    """如果 RepoScout 报告已包含足够的调研信息，跳过 Researcher."""
    if state.get("reports", {}).get("RepoScout", "").endswith("sufficient"):
        return "coder"          # 直接跳到 Coder
    return "researcher"         # 正常执行 Researcher

builder.add_conditional_edges(
    "RepoScout",
    should_skip_research,
    {"researcher": "Researcher", "coder": "Coder"}
)
```

**价值**: 减少不必要的 LLM 调用，节省 token 成本。

### 2.2 Human-in-the-Loop — 优雅的人工审核

**之前**: `USER_DECISION_REQUIRED.md` 文件机制 — 需要人工发现并手动处理。

**将来**: LangGraph 原生 `interrupt()` 机制：
```python
from langgraph.types import interrupt

def coder_node(state: AgentLabState) -> dict:
    changes = generate_changes(state)
    # 在修改文件前暂停，等待人工审批
    approval = interrupt(f"即将修改 {len(changes)} 个文件。继续吗？")
    if approval.get("decision") != "approve":
        return {"errors": ["User rejected changes"]}
    apply_changes(changes)
    return {"files_changed": changes}
```

**价值**: 在关键步骤（大范围修改、外部 API 调用、数据库迁移）实现可编程安全闸门。

### 2.3 Subgraph — 嵌套子任务

复杂任务中，单个 agent 可能受益于内部 multi-step 循环。例如 Coder 的 "plan → edit → verify → retry" 循环：

```python
coder_subgraph = StateGraph(CoderSubState)
coder_subgraph.add_node("plan", plan_changes)
coder_subgraph.add_node("edit", edit_files)
coder_subgraph.add_node("verify", verify_compiles)
coder_subgraph.add_conditional_edges("verify", should_retry, {
    "pass": END,
    "retry": "plan"    # 循环直到通过
})

# 作为子图挂到主流水线
builder.add_node("Coder", coder_subgraph.compile())
```

**价值**: 提升单个 agent 的输出质量，减少人工修正轮次。

### 2.4 Stream 流式输出 — 实时进度

```python
for event in app.stream(initial_state, config, stream_mode="updates"):
    node_name = list(event.keys())[0]
    print(f"Completed: {node_name}")
    # 实时显示进度条、推送通知等
```

**价值**: 长时间运行的大任务可以有可见的进度反馈。

### 2.5 LangSmith 可观测性 — 分布式追踪

LangGraph 原生支持 LangSmith 集成，提供：
- 图执行轨迹可视化
- 每个 node 的输入/输出快照
- Token 消耗拆解
- 延迟热点分析

**价值**: 从 "盲盒" 式执行变为完全透明的可调试系统。

### 2.6 并行 Fan-out — 加速流水线

某些 agent 不彼此依赖时可以并行执行：
```python
from langgraph.types import Send

def fanout_after_supervisor(state):
    return [
        Send("RepoScout", state),
        Send("Researcher", state),
    ]  # RepoScout 和 Researcher 并行执行

builder.add_conditional_edges("Supervisor", fanout_after_supervisor, ["RepoScout", "Researcher"])
```

**价值**: 大任务执行时间减半。

---

## 三、对比总结

| 能力 | 之前 (文件系统流水线) | 现在 (LangGraph MVP) | 将来 (Phase 2-3) |
|---|---|---|---|
| State 传递 | 文件系统.md 文件 | TypedDict 内存状态 | ← |
| 状态合并 | 手动 YAML 读写 | Reducer 自动合并 | ← |
| Pipeline 执行 | 逐次手动调用 | `run-pipeline` 一键启动 | + Stream 进度 |
| 故障恢复 | 手动判断断点 | Checkpoint 自动恢复 | + Sqlite 持久化 |
| Agent 编排 | 隐藏于 shell 历史 | 声明式图拓扑 (活文档) | ← |
| 动态路由 | ❌ | ❌ (MVP 不做) | ✅ 条件边 |
| Human-in-the-loop | MD 文件机制 | ❌ (MVP 不做) | ✅ `interrupt()` |
| 嵌套子任务 | ❌ | ❌ | ✅ Subgraph |
| 并行执行 | ❌ | ❌ | ✅ Fan-out (Send) |
| 可观测性 | brain_decisions.yml | ← | + LangSmith 可视化 |
| 文件系统兼容 | ✅ | ✅ (影子模式) | ✅ (保留) |

---

## 四、使用指南

### 安装
```bash
cd agent_runtime
pip install langgraph>=1.2
```

### 运行
```bash
# 1. 初始化任务
./agentlab.sh init-task --task-id task_0015 --project AgentLab --request-text "测试 LangGraph 流水线"

# 2. 准备计划
./agentlab.sh prepare --task-id task_0015 --project AgentLab --write-plan

# 3. 一键跑通
./agentlab.sh run-pipeline --task-id task_0015 --project AgentLab

# 4. 查看结果
./agentlab.sh status --task-id task_0015 --project AgentLab
./agentlab.sh brain-status --task-id task_0015 --project AgentLab
```

### 回退
```bash
# 传统方式仍可用
./agentlab.sh run-agent Supervisor --task-id task_0015 --project AgentLab --execute