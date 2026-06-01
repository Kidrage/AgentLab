# Task 0015 — LangGraph 骨架替换 MVP 实施

基于 task_0014 调研结论，将 AgentLab 的 agent 流水线骨架迁移到 LangGraph
StateGraph，同时保持文件系统报告输出（影子模式兼容）。

## 目标
1. 创建 `AgentLabState` TypedDict schema（带 reducer）
2. 创建 `langgraph_workflow.py` — StateGraph builder + agent node 函数工厂
3. 在 CLI 中新增 `run-pipeline` 命令（`--backend langgraph`）
4. 保留文件系统报告输出（影子模式兼容现有工具链）

## 非目标（MVP 不做）
- 条件路由（动态分支）
- Stream 流式输出
- LangSmith 集成
- Subgraph 嵌套子任务
- Human-in-the-loop interrupt()

## 验收标准
- `./agentlab.sh run-pipeline --task-id task_0015` 能跑通完整流水线
- 所有 agent 报告正常写入 `runs/task_0015/` 目录
- State 追踪 reports、token_usage、brain_decisions、files_changed