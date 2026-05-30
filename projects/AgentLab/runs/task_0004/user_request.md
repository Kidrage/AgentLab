# 增强 Web UI 交互性

继续修改 web UI，要求补全互动性，这是用于管理 AgentLab 的 AI agents 任务流的一个 UI 界面，需要尽可能地完善模块，增加可交互性。参考同类产品（LangSmith、Weights & Biases、Linear、Airflow 等）的 UI 设计逻辑。

具体要求：
1. 多任务/项目管理 - 项目选择器、任务列表
2. Tab 式导航 - 总览 / Agent 面板 / 任务日志 / 成本分析 / 配置
3. 实时 Agent 状态面板 - 带进度条和动态更新
4. 可交互的 Agent 控制 - 启动/暂停/恢复/停止
5. 详细日志查看器 - 可筛选、折叠的事件日志
6. Token 成本仪表盘 - 用量图表
7. 用户决策弹窗 - 处理 USER_DECISION_REQUIRED
8. 深色/浅色主题切换
9. 键盘快捷键支持
10. 项目切换与任务创建表单
