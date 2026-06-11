# AgentLab Projects

此目录存放 AgentLab 的项目运行时产物。

## 本地记忆策略

`projects/<ProjectName>/` 下的所有内容（`agent_docs/`, `runs/`, `repo/`,
`evaluation_runs/`, `task_index.yml` 等）均为**本地项目记忆**，
**不提交到 Git**，不在仓库间共享。

这些文件包含：
- 任务运行记录（`runs/`）
- 项目记忆文档（`agent_docs/`）
- 本地仓库镜像（`repo/` 或 `repo.local.bak/`）
- 评估记录（`evaluation_runs/`）
- 成本记录、进度追踪、事件日志

## 公开可复用知识

如需将项目中发现的知识公开共享，应将其提炼为**消毒后的 Skill 包**
存入 `skills/` 目录，而非直接提交 `projects/` 中的原始文件。

Skill 包应：
- 不包含用户特定数据
- 不包含凭证或密钥
- 遵循 `skills/registry.yml` 的生命周期
- 包含清晰的 `SKILL.md` with frontmatter

## 示例

如需提供项目使用示例，请使用 `examples/` 目录而非 `projects/`。