# AgentLab Projects

此目录存放 AgentLab 的项目运行时产物。

## 本地记忆策略

`projects/<ProjectName>/` 下的所有内容（`agent_docs/`, `runs/`, `repo/`,
`evaluation_runs/`, `task_index.yml` 等）均为**本地项目记忆**，
**不提交到 Git**，不在仓库间共享。

## Active content project protocol

长期内容项目的当前 active set 由 `config/content_project_governance.yml`
声明。当前只应默认发现：

- `NovelGen`
- `Crown_of_Ash`

这些项目内部使用统一事实源布局：

- `production/`: 唯一正式当前内容区。
- `project_artifact_index.yml`: 决定 artifact 的 current 版本。
- `project_brain/project_fact_snapshot.yml`: 决定世界观、角色、时间线等 durable facts。
- `candidates/<task_id>/`: 候选产物，默认 context pack 不读取为正式事实。
- `archive/`: 旧版本，只能通过 index 显式引用。
- `runs/<task_id>/`: 执行证据、日志、报告、任务包。

`*_rebuild`, `v2_*`, `legacy`, `_archive`, `archive_v*` 等并列目录不能靠目录名
成为事实源；必须在 `project_artifact_index.yml` 或
`project_brain/artifact_version_policy.yml` 中登记。

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
