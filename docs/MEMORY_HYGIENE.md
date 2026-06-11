# AgentLab Memory Hygiene

本文档说明 AgentLab 仓库的本地记忆管理与公开知识共享策略。

## 核心原则

1. **项目记忆是本地资源，不提交到 Git。**
   `projects/<ProjectName>/` 下的所有 `agent_docs/`, `runs/`,
   `repo/`, `evaluation_runs/` 等目录均为本地运行时产物，
   由 `.gitignore` 忽略。

2. **公开可复用知识必须消毒为 Skill 包。**
   如某个项目发现了可复用的模式、修复流程、配置策略等，
   应将其提炼为 `skills/` 下的 sanitized skill package，
   而不是直接提交 `projects/` 原始数据。

3. **示例属于 `examples/`，不属于 `projects/`。**
   需要演示 AgentLab 用法的示例项目请放在 `examples/` 目录下。

## .gitignore 规则

仓库根目录的 `.gitignore` 已配置以下忽略规则：

- `projects/*` — 忽略所有项目目录内容
- `!projects/README.md` — 保留说明文件
- `!projects/.gitkeep` — 保留目录占位
- `**/agent_docs/` — 忽略所有项目记忆文档
- `**/runs/` — 忽略所有任务运行记录
- `**/*.local.bak/` — 忽略本地备份
- `*.key`, `*.pem`, `*.p12`, `*.pfx` — 忽略密钥
- `.env`, `.env.*` — 忽略环境变量（`.env.example` 除外）
- `task_index.yml`, `cost_ledger.yml`, `state.yml` 等运行时产物

## 禁止跟踪的文件模式

以下文件模式**绝不应当被 Git 跟踪**：

- `projects/*/agent_docs/**`
- `projects/*/runs/**`
- `projects/*/repo/**`
- `projects/*/evaluation_runs/**`
- `*.local.bak`
- `.env`
- `*.pem`
- `*.key`

可用 `scripts/check_forbidden_tracked_files.sh` 检查。

## 历史记录

- 2026-06-11: 清理了 `projects/` 下所有已跟踪的本地项目记忆，
  更新 `.gitignore`，添加本文档。