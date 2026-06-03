# AgentLab 使用指南

> 自动生成于 2026-06-01T03:59:57.250490+00:00  |  DocManager Agent (T5)

## 快速开始

```bash
./agentlab.sh init-task --project {project} --task-id task_XXXX
./agentlab.sh prepare --project {project} --task-id task_XXXX --write-plan
./agentlab.sh run-agent Supervisor --project {project} --task-id task_XXXX --execute
```

## CLI 命令参考

| 命令 | 用途 |
|---|---|
| `init-task` | 初始化新任务 |
| `prepare` | 生成工作流计划 |
| `status` | 查看任务状态 |
| `run-agent` | 运行 Agent (dry-run / --execute) |
| `brain-status` | 查看大脑治理状态 |
| `guard-status` | 查看守护状态 |
| `task-search` | 搜索任务 |
| `chat` | 终端对话 |
| `task-purge` | 归档清理 + 生成文档 |

## 项目配置

配置文件位于 `projects/AgentLab/project_config.yml`。
全局策略位于 `config/` 目录。

## 常见工作流

### 新功能开发
1. 创建任务: `./agentlab.sh init-task`
2. 生成计划: `./agentlab.sh prepare --write-plan`
3. 运行大脑Agent: `./agentlab.sh run-agent Supervisor --execute`
4. 运行Coder: `./agentlab.sh run-agent Coder --execute`
5. 验证审计: `./agentlab.sh run-agent TesterAuditor --execute`

### 任务清理
```bash
# 预览清理内容 (dry-run)
./agentlab.sh task-purge --project {project} --keep-days 7 --dry-run

# 执行清理 + 生成文档
./agentlab.sh task-purge --project {project} --keep-days 7
```