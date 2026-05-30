# User Request

## 自然语言任务描述
调查 AgentLab 在云端部署的可行性。AgentLab 目前是一个本地优先的 CLI + Web UI 工具，
需要分析是否可以在云服务器上运行（如 AWS、阿里云、VPS 等），以及智能体架构是否需要适配。

## 约束条件（用户明确说的）
- 只做调查分析，不做实际开发
- 重点关注：能否云端运行、架构需要哪些变化、有哪些可行方案
- 输出修改方针建议

## 当前系统背景
- AgentLab 是本地 Python CLI 工具（agentlab.sh → run_task.py）
- Web UI 用 pywebview 做桌面窗口 + 后端 server.py
- 大脑层用 DeepSeek API，Coder 阶段默认由 Codex Plus 手动接管
- 配置文件在 config/ 目录，运行时数据在 projects/ 目录
- 依赖 .env 存放 API key