# User Request — Task 0017 模型分层系统规划

**请求**: AgentLab 的大脑层模型选择紊乱，需要系统规划每个 agent 的模型分配。

**要求**:
1. 大脑层默认 deepseek-v4-pro（可替换为 qwen3-max）
2. 执行层由各类 Qwen 模型构成
3. 根据实际 agent 作用分配最优模型
4. 注重工作质量与性价比
5. 为外部 IDE 的 AI 留有可编辑窗口与引导