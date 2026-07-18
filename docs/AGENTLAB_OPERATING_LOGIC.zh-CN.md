# AgentLab 当前运行逻辑

本文件是中文概览，不复制模型表、CLI 命令模板、验收计数或 provider 会话状态。
详细权威关系见根目录 `OPERATING_MODEL.md`。

## 权威分层

```text
agent_registry.yml             角色与模板
routing_rules.yml              路线成员与顺序
production_packs.yml           领域生命周期、产物、记忆、质量门
execution_modes.yml            AgentLab 工作流 driver
agent_model_profiles.yml       各角色执行壳与模型
worker_invocation_contracts.yml 精确壳命令
model_capacity.yml             已声明容量 fallback
```

文档、Web UI、历史报告和 CLI 名字都不能覆盖这些配置。

## 一次任务如何运行

```text
用户意图
 -> mission contract
 -> 最小安全路线 + production pack
 -> workflow plan（解析角色、壳、模型、预算、输入输出、质量门）
 -> Supervisor
 -> 当前路线需要的角色
 -> 本地确定性检查 / 独立审查
 -> run-local receipt 与事件
 -> candidate 完成，或明确 paused / blocked / recoverable
 -> 独立审批与 promotion
```

AgentLab 是工作流宿主。Hermes、Claude Code、Codex、Agy、Grok、Qwen 等只是
可替换 worker 壳。壳可以在一个已分配角色内部使用自身 subagents，但必须把结果
收回该角色 receipt；不得吞并整条 AgentLab 路线。

## 任务类型

- 代码任务按风险选择轻、中、接口敏感、研究敏感或重型路线。
- 小说单章/续写默认走 narrative light，只产候选正文和最小连续性闭环。
- 小说多章使用有界 batch；阶段审计走 heavy audit，审计已有正文而非默认重写。
- 普通文章走 article light，不继承长期小说治理。
- 图像/视频走 media 路线，生成者不能验收自己的视觉产物。
- 长文本、附件或仓库观察可走只读路线，不制造生产角色。

精确路线以 `config/routing_rules.yml` 为准。旧
`fiction_chapter_pipeline` 只兼容读取历史计划，不参与新任务默认选择。

## 状态与离线反馈

每个任务的可恢复状态都在 `projects/<Project>/runs/<task_id>/`：

- `workflow_plan.yml`：解析后的完整计划；
- `state.yml`：当前状态、当前角色和已完成角色；
- `lifecycle.yml`：节点状态与依赖；
- `progress.yml`：面向 operator 的进度与 heartbeat；
- `task_events.jsonl`：追加式事件流；
- `decision_cards/`：人工审批或恢复选择；
- 角色报告与 receipts：真实完成证据。

Web UI、后续 Codex 对话和 daemon 都从这些文件重建状态，不依赖旧会话文本。
watchdog 只识别 stale/blocked 等反馈并生成事件或 decision card，不代替路由器执行
工作。daemon 状态写入 `.agentlab_runtime/daemon/`，不会成为项目事实源。

## 产物边界

```text
runs/<task_id>/                 过程、状态和证据
runs/<task_id>/artifacts/       本任务候选产物
production/                    已晋升正式产物
archive/                       被替换正式产物
```

候选完成不等于 production。晋升必须检查 lineage、声明路径、审查/审批证据、旧版
归档回执，并更新项目 artifact index。新小说设定还必须进入 state transition
proposal，不能只藏在正文。

## 成本与 fallback

默认使用最小角色数和必要模型调用；能由本地确定性检查完成的工作不调用模型。
OAuth/订阅额度按壳原生 usage/status 结果记录。低容量只能触发
`model_capacity.yml` 中已声明的同角色路线，或暂停等待刷新；禁止静默换壳、换模型
或改成 API 计费。

## 当前验收怎么查

当前结论只读取：

`acceptance_runs/agentlab_capability_acceptance/current.yml`

细项继续追踪该文件引用的 receipts/reports。本文不会复制 `overall_status`、计数、
临时 blocker 或 selected live command，因此重新验收时不需要同步改写架构文档。
`external_acceptance_readiness.yml` 是旧消费者兼容输出，不是新的权威入口。

历史累计版本保存在
`docs/archive/acceptance_docs_legacy_20260718/AGENTLAB_OPERATING_LOGIC.zh-CN.md`。
