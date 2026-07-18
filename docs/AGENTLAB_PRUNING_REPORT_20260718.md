# AgentLab 剪枝与性能修复报告

日期：2026-07-18

## 结论

本轮已解决三类结构性问题：非代码任务误入代码管线、模型与壳配置多处复制、为了“合并壳调用”而新建的伪调度子系统。默认小说章节和文章任务现在只激活必需生产角色，heavy audit 只在批次或 promotion 门禁调度。

最终完整回归为 `2709 passed, 2 skipped`，用时 `366.11s`。修复前本轮同一工作树的首次全量回归为 `10 failed, 2700 passed, 2 skipped`，用时 `1540.71s`。稳定回归时间降低约 76%。

## 路由与生产成本

| 请求 | 默认 route | 模型生产角色 | 重路径 |
| --- | --- | --- | --- |
| 写 Crown 单章、续写、日更 | `narrative_light_chapter` | `Supervisor + Writer` | 不默认运行 |
| 通用文章、产品说明 | `article_light_draft` | `Supervisor + ArtifactProducer` | 不进入长篇治理 |
| 前 N 章审计、promotion 前验收 | `narrative_heavy_audit` | `Reviewer + Scribe + Verifier` | 按批次运行 |
| 代码修复 | 代码 route | `Coder + TesterAuditor` 等 | 与文本路由隔离 |

单章路径目标是一次 Writer provider 调用，连续性和交付格式先由本地 deterministic checks 检查。不再默认每章启动 Reviewer、Scribe、Verifier 和 Archivist。

## 壳调用剪枝

`cli_shell_coalescing*` 五个运行模块、两个专用测试文件和当前 acceptance 链已从主线移除。该子系统只会编译 synthetic packet，未被 `run-pipeline` 调用，也无法在 Reviewer 完成前安全合并 Scribe。历史证据保留在 `docs/archive/acceptance_legacy_20260718/cli_shell_coalescing/`。

当前边界是：

- 一个 AgentLab role-session 内可以使用 Hermes kanban、Claude agents/background 等壳原生功能。
- 有 lifecycle 依赖的 AgentLab 角色必须保持独立 receipt，不为了少启一次 CLI 而越过验收门。
- 当前生产 route 没有无依赖的同阶段多角色组，因此不实施跨角色 coalescing。

## 配置与报告收敛

- `config/agent_registry.yml` 只定义 role contract；`config/agent_model_profiles.yml` 是角色到 worker/provider/model 的权威矩阵。
- `config/execution_policy.yml` 不再复制 backend/model 选择。`model-doctor` 解析 135 个 profile，当前 `0 issues`。
- 22 个未接线 YAML spec 从活动 `config/` 移至 `docs/archive/config_specs_legacy_20260718/`；活动 config YAML 现为 121 个。
- acceptance report 刷新收敛为单向 DAG：`live_unblock -> capability -> goal -> objective -> hygiene`，collector 只运行一遍。单次 canonical collect 约 6.2 秒，而不是旧的多次互相重建。

## 运行时和测试收敛

- Config Center 使用 LibYAML `CSafeLoader`。完整配置层加载从约 `0.71s` 降到 `0.08s`。
- `config-list` 等重复 subprocess 合同测试已合并；测试文件从约 333 个降到 329 个，收集用例从 2734 个降到 2706 个。
- 媒体和 capability audit 通过 `resolve_run_dir` 透明读取 retention archive，不需要把旧 run 放回活动目录。
- Crown 当前大量章节 run 属于未完成的 1-200 候选链和审计证据，由 retention policy 显式保护；65 个旧 probe/smoke run 已归档。它们不应被全局 watchdog 当成活动任务。
- Crown 批量审计不再把 Agy/Gemini 写成唯一合法 Writer。当前章节必须由 `workflow_plan.yml`、Writer role-session guard 和 model execution chain 互相印证 worker/provider/model，且不得出现未声明 fallback；旧 Agy 章节只通过冻结的兼容凭据验真。
- 后台 Writer budget 现在真正贯穿 controller、narrative runtime 和 workflow plan。每章只构建一次 workflow plan，不再在同一 Writer 调用前重复解析配置。
- 10 章分批生成会从上一章种入 continuity sources 和累计 candidate facts。恢复时一旦发现 delivery 或 Writer provenance 无效，会从该章起重建整个后缀，并归档被替换证据，防止新旧章节混接。
- Detached controller/worker 显式继承 package 与历史 direct-module 两种 Python 搜索路径；后台 heavy audit 不再依赖交互式 `agentlab.sh` 恰好提供的导入环境。代码或配置修复后，可用带修复原因的 `background-job retry-blocked` 恢复同一持久 job，而不是复制任务或手改状态文件。

## 后台长任务

AgentLab 现在以 `projects/<project>/background_jobs/<job_id>/job_state.yml` 作为持久权威状态。Controller 只调度一个 action，worker 原子写入 `process_receipt.yml`，然后 controller 消费 receipt 并推进状态。会话退出后可通过 `background-job status` 继续查询。

后台 Crown 交付仍保持 candidate-only 边界：它会生成正文、ledger、批次 heavy audit 和最终 candidate package，但不会在无独立 promotion receipt 的情况下直接写 `production/manuscript`。这是生产安全门，不是任务卡死。

## 剩余边界

- 每章仍需一次 Writer CLI 会话。这是实际文本生成成本，不是重复壳调用。
- 每 10 章的 heavy audit 仍会启动独立审计角色。它是 promotion 证据成本，不进入单章默认路径。
- 当前 capability 快照为 `20 pass / 8 candidate / 0 fail`。8 个 candidate 主要是时序性 live/session 证据；Claude Writer session probe 未返回不代表 route/model 配置失败。
- 后台控制器当前只注册 Crown 长篇交付，不宣称所有 AgentLab 任务都已异步化。

## 验证

```text
python -m pytest -q --durations=40
2709 passed, 2 skipped, 11 warnings in 366.11s

./agentlab.sh model-doctor
resolved_profile_count: 135
issue_count: 0
status: pass
```

警告来自 local-search 缺失目录 fixture，是测试预期的可观测 warning，不是生产 provider 或文件破损。
