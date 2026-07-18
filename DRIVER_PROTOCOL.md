# AgentLab 外部 Worker 协议

本文件只定义外部 IDE/CLI worker 如何接入 AgentLab。跨端协作、安全、Git、
证据归属与 token 纪律以 `_shared/AGENT_PROTOCOL.md` 为准；角色、模型、命令和
路由分别以以下配置为准：

- `config/agent_role_bindings.yml`
- `config/agent_model_profiles.yml`
- `config/worker_invocation_contracts.yml`
- `config/routing_rules.yml`
- `config/production_packs.yml`
- `config/execution_modes.yml`

## 不变量

```text
AgentLab owns mission, route, role order, state, evidence, and promotion.
Worker shell owns only the scoped role assignment it receives.
```

- CLI 名称不是 AgentLab 角色，也不自动获得项目所有权。
- 同一 CLI 可承载多个角色，但每次只执行 task packet 声明的一个角色。
- 禁止任何 worker 模拟完整角色链、替 Supervisor 改路由或替审核角色自我验收。
- 角色后端只从 `agent_model_profiles.yml` 解析；不得从旧报告、提示词或 CLI
  名称猜测 provider/model。
- 不允许静默 fallback。只有 `model_capacity.yml` 声明的同角色容量路线可以切换，
  且必须写运行回执。
- 候选产物只写 `projects/<Project>/runs/<task_id>/`；正式产物只经审核、批准和
  Archivist promotion 写入 `projects/<Project>/production/`。

## 默认执行形态

`agentlab_orchestrated_cli` 是默认 driver：

```text
user request
-> mission contract
-> route decision
-> production pack
-> AgentLab role sessions
-> deterministic gates / independent review
-> handoff or approved promotion
```

AgentLab 可以让同一个 Hermes 会话使用其原生 subagents、plan/goal 或 kanban
能力来减少重复启动壳进程，但返回内容必须拆成 AgentLab 已分配的角色回执和产物。
壳内的 subagent 不会因此成为新的 AgentLab 角色，也不能改变 route。

## Driver 模式

| 模式 | AgentLab 行为 | Worker 边界 |
|---|---|---|
| `agentlab_orchestrated_cli` | 使用 `full_cli` 角色矩阵逐角色调度 | 每次一个受限角色 |
| `api_native` | 使用 `full_api` 角色矩阵逐角色调度 | API 返回一个角色产物 |
| `hybrid_ide` | AgentLab 规划/审核，显式 IDE worker 执行 Coder | 仅 Coder 阶段 |
| `langgraph` | 使用替代图执行引擎，角色矩阵仍由 AgentLab 解析 | 不改变角色权限 |

`codex_full_driver` 已退役，只允许读取历史 `workflow_plan.yml` 和 handoff；不得
创建新 run 或恢复调度。历史规范位于
`docs/archive/codex_full_driver_legacy_20260718/`。

## 标准入口

1. 在深读仓库前生成或刷新唯一权威 handoff：

   ```bash
   ./agentlab.sh repository-handoff --repo <repo> --write
   ```

2. 创建任务并生成确定性计划：

   ```bash
   ./agentlab.sh init-task --project <Project> --task-id <task_id> \
     --request-file <request_file>
   ./agentlab.sh prepare --project <Project> --task-id <task_id> --write-plan
   ```

3. 让 AgentLab 根据 route 调度；单角色人工诊断只能使用受控 role session：

   ```bash
   ./agentlab.sh role-session --role <Role> --worker <worker> \
     --project <Project> --task-id <task_id>
   ```

4. 用任务自身声明的 gates 验证，更新 state/handoff。不要套用固定的九角色或
   十四节点验收表。

## 外部接线层

当用户要求“让 AgentLab 内部完成”时，当前 Codex/IDE 会话是接线与验收层：

- 可以创建任务、启动 AgentLab、观察状态、检查真实产物和验证结果。
- 不得把自己的分析写成 Supervisor 结论。
- 不得把自己的编辑写成内部 Coder 产物。
- 只有用户明确把当前会话分配为外部 worker，且 task packet 授权对应角色和路径
  时，才执行该角色。
- 任务失败时报告 blocker 和证据；不得为了继续而换壳、换模型或冒充角色。

## Coder 与文件修改

- Coder 是否由 Claude、Codex、Hermes、API 或其他执行面承载，以当前 role profile
  为准。
- Coder 只修改 Supervisor/task packet 批准的文件；其余角色默认只写 run-local
  回执和候选产物。
- Coder 完成不等于任务完成。TesterAuditor/Verifier 必须独立读取实际 diff、命令
  结果和产物，不接受 Coder 自报作为通过证据。
- `AGENTLAB_EXTERNAL_CODER` 或 `EXTERNAL_CODER_READY` 只能开启明确的
  `hybrid_ide` Coder handoff，不能开启全链路接管。

## 审批、容量与暂停

- dry-run 不调用模型；execute/live 调用必须遵守任务合同和用户审批边界。
- OAuth/订阅余量低、quota exhausted、rate limited 或 model unavailable 时，先写
  capacity evidence，再按已登记的同角色 fallback、暂停或等待刷新处理。
- 无法取得精确额度时保持 unknown，不估算成事实。
- 涉及私有上下文外发时，审批必须明确项目、角色、provider、数据范围、候选边界、
  禁止密钥、禁止 production 和禁止未声明 fallback。

## 交接与验收

- 任务状态以 `state.yml`、`lifecycle.yml`、`workflow_plan.yml` 和 run-local receipts
  为准，不以聊天记录为准。
- `handoff_packet.yml` 必须从当前 route 计算 `next_agent`，不能写死角色顺序。
- 根仓库只保留 `PROJECT_HANDOFF.md`；旧 `.agentlab/HandOff.md`、
  `agent_docs/HandOff.md` 和根 `HandOff.md` 仅作只读发现源。
- 最终验收至少检查实际文件、Git diff、声明 gates、测试结果、provider/worker
  回执和 promotion 状态。

## AgentLab 自身维护

修 AgentLab 本体时，当前编码会话可以作为外部代码 worker，但必须：

1. 先确认没有生产任务或冲突锁。
2. 只修改批准范围，保留用户已有改动。
3. 用确定性测试证明行为，而不是启动生产任务“顺便验收”。
4. 将长期规则落在单一配置/协议，删除或归档重复提示词。
5. 完成后刷新 `PROJECT_HANDOFF.md`，检查 Git、推送和 CI。

## 历史兼容

`codex-start`、`codex-status`、`codex-handoff`、`codex-resume`、
`codex-verify-artifacts` 和 `continue-with-api` 暂时保留用于读取旧 run。它们不会
授予 Codex 路由权；`codex-start --mode full-driver` 必须拒绝。新任务使用标准
`prepare`、`run-pipeline`、`role-session`、状态和 handoff 命令。
