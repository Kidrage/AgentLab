# Implementation Report — Task 0015 LangGraph 骨架替换 MVP

> 日期: 2026-05-31 | 执行者: Cline (DeepSeek) | 任务: task_0015

---

## 变更清单

### 新增文件

| 文件 | 说明 | 行数 |
|---|---|---|
| `agent_runtime/langgraph_schema.py` | AgentLabState TypedDict 定义 + reducer helpers | 76 |
| `agent_runtime/langgraph_workflow.py` | StateGraph builder + 8个 agent node 工厂 + runner | 248 |

### 修改文件

| 文件 | 变更 | 说明 |
|---|---|---|
| `agent_runtime/run_task.py` | +49 行 | 新增 `run-pipeline` CLI 命令 |
| `agent_runtime/requirements.txt` | +2 行 | 添加 `langgraph>=1.2` 和 `langgraph-checkpoint>=4.1` |

### 文档文件

| 文件 | 说明 |
|---|---|
| `projects/AgentLab/runs/task_0015/user_request.md` | 任务说明 |
| `projects/AgentLab/runs/task_0015/NEW_CAPABILITIES.md` | 新特性详解（330+ 行） |
| `projects/AgentLab/runs/task_0015/implementation_report.md` | 本文件 |

---

## 架构设计

### 核心抽象

```
┌──────────────────────────────────────────────┐
│              AgentLabState                    │
│  (TypedDict + Annotated reducers)            │
│                                              │
│  project, task_id, run_dir, ...              │
│  reports: Annotated[dict, merge]             │
│  token_usage: Annotated[dict, merge]          │
│  brain_decisions: Annotated[list, add]       │
│  files_changed: Annotated[list, add]         │
│  errors: Annotated[list, add]                │
└──────────────┬───────────────────────────────┘
               │ flows through
               ▼
┌──────────────────────────────────────────────┐
│           StateGraph (builder)               │
│                                              │
│  Supervisor ─► RepoScout ─► Researcher       │
│       ─► Coder ─► Tester ─► Verifier ─► End │
│                                              │
│  Compile with InMemorySaver (checkpoint)     │
└──────────────┬───────────────────────────────┘
               │ .invoke()
               ▼
┌──────────────────────────────────────────────┐
│           CompiledStateGraph (Pregel)         │
│  • Executes nodes in supersteps              │
│  • Auto-persists checkpoints                 │
│  • Applies reducers to merge state updates   │
│  • Writes file system reports (side effect)  │
└──────────────────────────────────────────────┘
```

### Node 工厂模式

每个 agent node 通过 `_make_agent_node(agent_name, phase_label)` 工厂创建，复用现有 `agent_runner.run_agent_model()` 的 LLM 调用逻辑：

```python
def _make_agent_node(agent_name: str, phase_label: str):
    def node_fn(state: AgentLabState, config=None) -> dict:
        plan = WorkflowPlan(**state["workflow_plan"])
        output_path = report_path_for_agent(plan, agent_name)
        result = run_agent_model(agentlab_root, plan, agent_name, output_path, ...)
        return {
            "current_phase": phase_label,
            "reports": {agent_name: str(output_path)},
            "token_usage": {agent_name: {"total": result.total_tokens}},
            ...
        }
    return node_fn
```

### 向后兼容

- 所有 LLM 调用仍通过 `agent_runner.run_agent_model()` → `llm_provider.generate_text()`
- 文件系统报告 100% 保留，作为 LangGraph 的 side effect
- 现有 CLI 命令（`init-task`, `prepare`, `run-agent`, `status` 等）完全不变
- `run-pipeline` 是可选的**新增**命令，不影响旧工作流

---

## 验证结果

### 语法检查
```bash
$ python3 -c "from agent_runtime.langgraph_schema import AgentLabState; print('OK')"
OK

$ python3 -c "import ast; ast.parse(open('agent_runtime/langgraph_workflow.py').read()); print('OK')"
OK

$ python3 -c "import ast; ast.parse(open('agent_runtime/run_task.py').read()); print('OK')"
OK
```

### 结构确认

| 检查项 | 状态 |
|---|---|
| AgentLabState 包含 20 个字段 | ✅ |
| 包含 8 个 agent node 函数 | ✅ |
| 包含 3 个 reducer helpers | ✅ |
| `build_agentlab_graph()` 编译成功 | ✅ (语法级) |
| `run_agentlab_graph()` 包含完整 pre/post 逻辑 | ✅ |
| `run-pipeline` CLI 命令已注册 | ✅ |
| requirements.txt 已更新 | ✅ |

### 未执行完整端到端测试

因 LangGraph 未在本地 venv 安装，完整 pipeline 执行需要：
```bash
cd agent_runtime
pip install langgraph>=1.2
./agentlab.sh run-pipeline --task-id task_0015 --project AgentLab
```

---

## 已知限制

1. **MVP 无实际执行**: 所有 node 函数调用 `run_agent_model` 需要有效的 LLM API key，在无网络环境下会进入 fallback/blocked 状态
2. **InMemorySaver**: 进程重启后 checkpoint 丢失，Phase 2 应替换为 SqliteSaver
3. **单线程执行**: MVP 用同步 `invoke()`，Phase 2 可用 `astream()` 支持流式
4. **无重试策略**: 若某个 agent node 失败，整个 pipeline 中止。Phase 2 可加 RetryPolicy

---

## 文件位置汇总

```
AgentLab/
├── agent_runtime/
│   ├── langgraph_schema.py          ← NEW: State schema
│   ├── langgraph_workflow.py        ← NEW: Graph builder + runner
│   ├── run_task.py                  ← MODIFIED: +run-pipeline command
│   └── requirements.txt             ← MODIFIED: +langgraph deps
└── projects/AgentLab/runs/task_0015/
    ├── user_request.md              ← NEW
    ├── NEW_CAPABILITIES.md          ← NEW: 新特性详解
    └── implementation_report.md     ← NEW: 本文件