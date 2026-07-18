# AgentLab 任务执行框架

## 结论

AgentLab 当前是“合同编译器 + 路由器 + 单任务 pipeline + provider executor +
产物门禁”的治理系统。普通任务仍由同步 pipeline 执行；长篇 Crown 任务新增了
一个不调用模型的 receipt 控制器，用来在交互会话退出后继续收取结果、运行本地
检查并决定下一步。它不是第二套写作系统，也不会自行写正文。

## 六层结构

1. **Mission compiler**：把用户请求编译成 mission contract，识别代码、小说轻写、
   文章轻写、重审计等 route。
2. **Route / production-pack compiler**：声明需要的角色、产物、预算和门禁。小说单章
   默认走 `narrative_light_chapter`，不是代码 pipeline。
3. **Per-task pipeline**：每个任务写入
   `projects/<project>/runs/<task_id>/`。canonical graph 有 26 个节点，route 只激活
   必需节点；小说轻路径当前激活 9 个。
4. **Provider executor**：按角色、worker、模型和 CLI contract 调用 provider，并写
   model execution receipt；禁止未声明 fallback。
5. **Artifact / acceptance layer**：验证候选产物、continuity、lineage、candidate 与
   production 边界。Writer 不能直接 promotion。
6. **Project background controller**：只处理持久状态、worker process receipt、重试、
   capacity wait、pause/resume 和终态反馈。

## 单任务状态

| 文件 | 职责 |
| --- | --- |
| `state.yml` | 任务整体执行状态 |
| `lifecycle.yml` | pipeline 节点与 checkpoint 状态 |
| `progress.yml` | 给 UI/操作者看的 route、角色、provider、阶段和百分比投影 |
| `task_events.jsonl` | 只追加的事件历史 |
| `feedback_status.json` | 从上述事实派生的“是否需要操作”投影 |

`state.yml` 与 `lifecycle.yml` 驱动执行；其余文件是投影，不得反向覆盖权威状态。

## 长任务状态机

权威文件是
`projects/<project>/background_jobs/<job_id>/job_state.yml`：

```text
queued -> preflight -> generating_batch -> deterministic_check
       -> awaiting_heavy_audit -> heavy_auditing -> batch_sealed -> queued

heavy_auditing -> rewrite_required -> rewriting
               -> deterministic_reaudit -> batch_sealed

any nonterminal state -> paused -> exact previous state
provider capacity      -> capacity_wait -> same action after reset
worker crash           -> failed_recoverable -> bounded retry
last batch             -> final_acceptance -> completed
unrecoverable issue    -> blocked
```

`paused` 不会杀死已经启动的 worker。当前 attempt 完成后，receipt 仍会被消费一次，
计算出的下一状态保存在 `paused_from_status`，只有显式 `resume` 才继续调度。

## 离线结果如何触发检查

1. Controller 写 `action_request.yml`，启动一个 detached worker，然后自身可退出。
2. Worker 只执行一个动作，并原子写 `process_receipt.yml`；异常也必须写失败 receipt。
3. Controller 下一次 tick 通过 idempotency key 消费该 receipt，更新 `job_state.yml`。
4. 生成成功后先调度本地 deterministic audit；只有通过且到达 cadence 才调 heavy audit。
5. capacity 用尽时保存可观测的 reset time，恢复后重试同一动作，不静默换模型。
6. `completed` / `blocked` 写 `operator_feedback.yml`；完成时另写
   `completion_receipt.yml`，可复用 webhook 通知外部界面。

机器可读合同见 `config/background_job_policy.yml`。当前后台实现只注册 Crown 长篇
交付；通用 job registry 尚未实现，不能把它宣称为所有任务都已后台化。

## 验收报告 DAG

Current acceptance 只允许以下单向刷新顺序：

```text
trusted request/status/preflight
        |
        v
live_unblock_plan
        |
        v
capability_acceptance
        |
        v
goal_completion_audit
        |
        v
objective_requirement_audit
        |
        v
acceptance_report_hygiene
```

`trusted-live-runner-collect` 每次只按该顺序刷新一遍。下游报告不得回头重建上游，
readiness 不得读 objective，capability 不得通过 live plan 再读自己。所有
status/preflight/collect 必须与当前 request ID 一致，否则只能为 candidate/stale，
不能沿用历史 pass。

## Run retention

默认运行目录仍是 `projects/<project>/runs/<task_id>/`。终态 probe、smoke 和历史
验收 run 可按 `config/run_retention_policy.yml` 移入
`projects/<project>/archive/run_history/<batch_id>/runs/`。审计器通过
`resolve_run_dir` 先查活动 run，再精确查归档 run；归档证据只读，不会被恢复成
活动任务。

## 当前主要成本

- 每章仍单开一个 Writer CLI 会话；这是当前最大的模型调用固定成本。
- heavy audit 仍使用完整审计 pipeline，但只应按批次或 promotion 前运行。
- 历史 Crown run 通过 retention archive 与活动候选链分离；watchdog、索引器和备份器必须忽略终态/无状态目录。
- Config Center 使用 LibYAML `CSafeLoader`，本轮完整配置层加载从约 0.71 秒降到 0.08 秒；acceptance collector 只刷新报告 DAG 一遍。
- `.agents/workspaces` 是本地 CLI home，不是项目源码；禁止进入 Git、Relay 同步、
  repository ingestion 或 HandOff inventory。
- Hermes 角色 profile 必须轻量 clone；不得使用 `--clone-all` 复制 Node/LSP/skills。
