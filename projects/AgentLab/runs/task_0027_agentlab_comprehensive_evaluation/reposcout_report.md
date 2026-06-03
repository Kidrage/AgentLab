# AgentLab 全面评估 — RepoScout 仓库结构报告

## 仓库总览

AgentLab 是一个本地优先、半托管的个人 Agentic 软件开发工作流系统。

### 目录结构
```
AgentLab/
├── agent_runtime/       # 核心运行时（46 个 Python 模块 + evaluation 目录）
├── agent_templates/     # 9 个 Agent 角色提示词模板 (.md)
├── config/              # 22+ YAML 策略配置
├── projects/            # 项目实例（每个项目含 agent_docs/ 记忆系统）
├── web_ui/              # 静态状态看板
├── scripts/             # Git 钩子
├── docs/                # 设计文档
├── agentlab.sh          # CLI 入口脚本
└── AGENTS.md, DRIVER_PROTOCOL.md, OPERATING_MODEL.md
```

### 核心模块依赖图
```
agentlab.sh
  └─ agent_runtime/
      ├── run_task.py          # 任务入口
      ├── agent_runner.py      # Agent 执行引擎
      ├── llm_provider.py      # LLM 提供者抽象
      ├── pipeline_runner.py   # 流水线编排
      ├── brain_governor.py    # 大脑治理
      ├── budget_planner.py    # 预算规划
      ├── task_router.py       # 任务路由
      ├── task_index.py        # 任务索引
      ├── task_search.py       # 任务搜索
      ├── task_card.py         # 任务卡片
      ├── task_purge.py        # 任务清理
      ├── lifecycle_graph.py   # 生命周期状态机
      ├── progress_tracker.py  # 进度追踪
      ├── guard.py             # 守护系统（锁/心跳）
      ├── atomic_io.py         # 原子 IO
      ├── provider_guard.py    # 提供者故障切换
      ├── incident_manager.py  # 事件管理
      ├── state_store.py       # 状态存储
      ├── config_loader.py     # 配置加载
      ├── policies.py          # 策略引擎
      ├── cost_tracker.py      # 成本追踪
      ├── handoff_builder.py   # 交接包
      ├── patch_applicator.py  # 补丁应用
      ├── chat_router.py       # 终端对话
      ├── terminal_chat.py     # 终端聊天
      ├── workflow_plan.py     # 工作流规划
      ├── schemas.py           # 数据模式
      ├── langgraph_schema.py  # 图模式
      ├── langgraph_workflow.py# 图工作流
      ├── tools_fs.py          # 文件系统工具
      ├── tools_git.py         # Git 工具
      ├── workspace_scanner.py # 工作区扫描
      ├── codex_artifact_validator.py # 产物验证
      ├── rule_self_check.py   # 规则自查
      ├── github_sync.py       # GitHub 同步
      ├── github_client.py     # GitHub 客户端
      ├── git_utils.py         # Git 工具
      ├── api_continuation.py  # API 延续
      ├── fake_provider.py     # Mock 提供者
      ├── aider_adapter.py     # Aider 适配器
      └── agents_def.py        # Agent 定义