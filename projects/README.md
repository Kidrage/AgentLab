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

## 项目边界与路由

AgentLab 自身开发只使用 `projects/AgentLab/`。普通用户任务必须先经过
`./agentlab.sh project-route --mission-contract <path>`：

- `creative_longform`、`research`、`business`、`document_processing`、
  `audio_music`、`multimodal`、`data_analysis` 默认新建独立项目。
- 明确写着修 AgentLab、ProjectOps、repo hygiene、mainline 的任务才进入
  `projects/AgentLab/`。
- 含糊任务必须产生 `ambiguous_requires_user_decision`，不能静默塞进
  AgentLab 大项目。

## 任务归档与 compact

任务生命周期至少区分 `active`、`closed`、`compacted`、`archived`。任务结束后
运行：

```bash
./agentlab.sh task-compact --project <ProjectName> --task-id <task_id>
```

默认后续 agent 先读 `runs/<task_id>/task_compact/`，不要反复读取 raw logs 或
长 handoff。compact 目录包含最终状态、artifact index、memory promotions、
unresolved items、reusable patterns、cost summary 和 agent contribution summary。

## Agent contribution ledger

每个参与 agent 应记录轻量贡献：

```bash
./agentlab.sh agent-contributions --project <ProjectName> --task <task_id> \
  --agent-id qa_lead --role qa --summary "verified final artifacts" --accepted
```

这份 ledger 用于 `project-status` 和 `task-compact`，帮助用户看见谁读了什么、
产出了什么、哪些结果被采纳，避免多 agent 协作变成黑箱。

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
