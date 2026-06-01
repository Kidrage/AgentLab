# Phase 2 Plan — LangGraph 骨架增强 + Qwen3-Max 大脑切换

> 日期: 2026-05-31 | 执行者: Cline (DeepSeek) | 任务: task_0016

---

## 一、核心目标

1. **即时切换大脑模型**：将 AgentLab 的 BrainGovernor 节点从 DeepSeek 切换为阿里云 Qwen3-Max
2. **增强骨架能力**：基于 LangGraph 的 MVP 架构，增加 Phase 2 的 6 项关键能力
3. **保持兼容性**：确保切换不影响现有 Codex Plus 手动接管流程和影子模式报告输出

---

## 二、Qwen3-Max 大脑切换

### 1. 配置更新
```bash
# config/model_providers.yml 新增 Qwen3-Max 配置
qwen3:
  type: openai_compatible
  base_url: "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
  api_key: "env:DASHSCOPE_API_KEY"
  default_model: "qwen3-max"
```

### 2. 执行策略调整
```bash
# config/execution_policy.yml 更新大脑路由规则
brain_policy:
  required_provider: "qwen3"   # 从 deepseek 改为 qwen3
  deepseek_required_for_all_agentlab_tasks: false  # 允许 fallback
```

### 3. LLM 调用适配
```python
# llm_provider.py 新增 Qwen3 专属逻辑
def _classify_provider_error(exc: Exception) -> str:
    text = str(exc).lower()
    if "quota" in text or "balance" in text or "credit" in text or "insufficient" in text:
        return "quota_exceeded"
    if "rate limit" in text or "too many requests" in text:
        return "rate_limited"
    if "forbidden" in text or "authorization" in text:
        return "unauthorized"
    return "provider_error"
```

---

## 三、Phase 2 骨架增强路线图

### 增强 1：条件路由 (Conditional Edges)
```python
# langgraph_workflow.py 新增 should_skip_research 函数
def should_skip_research(state: AgentLabState) -> str:
    """根据 RepoScout 报告内容动态决定是否跳过 Researcher"""
    if state.get("reports", {}).get("RepoScout", "").endswith("sufficient"):
        return "coder"
    return "researcher"

# 在 builder 中添加条件边
builder.add_conditional_edges("RepoScout", should_skip_research, ["researcher", "coder"])
```

### 增强 2：人工审核闸门 (Human-in-the-loop)
```python
# langgraph_workflow.py 新增 interrupt_mechanism
def coder_node(state: AgentLabState) -> dict:
    changes = generate_changes(state)
    # 在修改文件前暂停，等待人工审批
    approval = interrupt(f"即将修改 {len(changes)} 个文件。继续吗？")
    if approval.get("decision") != "approve":
        return {"errors": ["User rejected changes"]}
    apply_changes(changes)
    return {"files_changed": changes}
```

### 增强 3：嵌套子任务 (Subgraph)
```python
# langgraph_workflow.py 新增 Coder Subgraph
coder_subgraph = StateGraph(CoderSubState)
coder_subgraph.add_node("plan", plan_changes)
coder_subgraph.add_node("edit", edit_files)
coder_subgraph.add_node("verify", verify_compiles)
coder_subgraph.add_conditional_edges("verify", should_retry, {
    "pass": END,
    "retry": "plan"
})

# 挂接到主流水线
builder.add_node("Coder", coder_subgraph.compile())
```

### 增强 4：流式进度 (Streaming)
```bash
# CLI 增加流式模式支持
./agentlab.sh run-pipeline --task-id task_0016 --stream
```

```python
# langgraph_runner.py 新增 stream 支持
for event in app.stream(initial_state, config, stream_mode="updates"):
    node_name = list(event.keys())[0]
    print(f"Completed: {node_name}")
    # 实时显示进度条、推送通知等
```

### 增强 5：LangSmith 可观测性
```bash
# requirements.txt 新增依赖
langsmith>=0.1.0
```

```python
# langgraph_workflow.py 启用 LangSmith 跟踪
tracer = LangChainTracer(project_name="AgentLab_Task_0016")
config = {"configurable": {"thread_id": f"{plan.project}_{plan.task_id}"}, "callbacks": [tracer]}
final_state = app.invoke(initial_state, config)
```

### 增强 6：并行执行 (Fan-out)
```python
# langgraph_workflow.py 新增并行分支
def fanout_after_supervisor(state):
    return [
        Send("RepoScout", state),
        Send("Researcher", state),
    ]

builder.add_conditional_edges("Supervisor", fanout_after_supervisor, ["RepoScout", "Researcher"])
```

---

## 四、实施计划

### 第一阶段（已完成）：LangGraph 基础骨架
- 状态管理
- 一键流水线
- 影子模式兼容

### 第二阶段（本计划）：流程智能化
- [ ] 第 1 周：Qwen3-Max 集成 + 基础性能验证
- [ ] 第 2 周：条件路由 + 人工审核闸门
- [ ] 第 3 周：嵌套子任务 + 流式进度
- [ ] 第 4 周：LangSmith 集成 + 并行执行

### 第三阶段（规划）：生产级增强
- 持久化 Checkpoint
- 自动化测试套件
- 异常重试策略
- 分布式执行支持

---

## 五、风险与应对

| 风险 | 影响 | 应对措施 |
|---|---|---|
| Qwen3-Max API 不兼容 | LLM 调用失败 | 保持 DeepSeek fallback 通道 |
| LangGraph Subgraph 稳定性 | 嵌套状态管理复杂 | 先在 Coder 节点试点 |
| 流式输出与终端交互冲突 | 进度显示混乱 | 开发专用 Web UI 显示 |
| LangSmith 集成成本高 | 调试能力缺失 | 先用内置 logging |
| 并行执行文件冲突 | 数据竞争风险 | 加强状态锁机制 |

---

## 六、验收标准

| 检查项 | 标准 |
|---|---|
| Qwen3-Max 调用 | 通过 `run-pipeline` 成功调用 Qwen3-Max |
| 条件路由 | 根据 RepoScout 报告内容动态跳过 Researcher |
| 人工审核 | 修改前暂停并等待用户输入 |
| 子任务循环 | Coder 节点内部 plan → edit → verify 循环 |
| 流式进度 | 终端显示每个节点完成状态 |
| 并行执行 | RepoScout 和 Researcher 同时运行 |

---

## 七、后续步骤

1. 创建 task_0016 工作区
2. 修改 model_providers.yml 添加 Qwen3-Max 配置
3. 修改 execution_policy.yml 切换大脑提供者
4. 扩展 langgraph_workflow.py 添加条件路由
5. 实现 Subgraph 支持
6. 添加流式输出和并行执行
7. 生成 Phase 2 实施报告