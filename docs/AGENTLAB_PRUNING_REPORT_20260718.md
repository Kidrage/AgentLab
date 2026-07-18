# AgentLab 剪枝与内部稳定性修复报告

日期：2026-07-18

## 结论

本轮仅修 AgentLab 内部，不运行 Crown、媒体、trusted runner 或任何 live
provider 生产。最终进程检查没有发现 AgentLab 后台生产任务。

修复后的核心边界是：AgentLab 自己拥有 route、lifecycle、memory、artifact 和
promotion 治理；CLI 壳只执行一个有边界的 role session。小说章节和普通文章走轻
路径，heavy audit 审计已有候选，不再默认参与每次正文生成。

最终完整回归：`2736 passed, 2 skipped, 11 warnings in 208.35s`。本轮较早的
稳定基线为 `2714 passed, 2 skipped, 11 warnings in 549.10s`，同机单次全量回归
时间降低约 62%。

## 权威配置

| 关注点 | 唯一权威 | 明确不负责 |
| --- | --- | --- |
| route 及角色顺序 | `config/routing_rules.yml` | 模型、壳命令 |
| 每类产物的角色合同、门禁和生命周期 | `config/production_packs.yml` | route 选择 |
| role 到 worker/provider/model | `config/agent_model_profiles.yml` | 生命周期 |
| workflow driver 到 agent backend mode | `config/execution_modes.yml` | 逐角色模型 |
| role 与 worker 的允许关系 | `config/agent_role_bindings.yml` | route 覆盖 |
| worker 调用方式 | `config/worker_invocation_contracts.yml` | 业务生产链 |

`model-doctor` 解析 135 个 profile，结果为 `0 issues`；`protocol-doctor` 完成
108 项检查，结果为 `0 failed`。route 不再携带 worker-specific invocation
override，因此 Qwen、Hermes、Claude 或 Codex 壳合同不会被业务 route 强塞给另一个
已解析 worker。

## 生产路径

| 请求 | 默认 route | 活跃生产角色 | 边界 |
| --- | --- | --- | --- |
| 小说单章、续写、日更 | `narrative_light_chapter` | `Supervisor + Writer` | candidate-only |
| 普通文章、产品说明 | `article_light_draft` | `Supervisor + ArtifactProducer` | 不进入长篇治理 |
| 阶段审计、promotion 前验收 | `narrative_heavy_audit` | `Supervisor + Reviewer + Scribe + Verifier` | 审计已有文本 |
| 代码实现 | 对应代码 route | route 配置的代码角色 | 与文本路径隔离 |

旧 `fiction_chapter_pipeline` 仅保留只读兼容，不再默认选择。Writer 的轻量 skill
只加载会影响本章正确性的结构化记忆，并在 run 内记录 skill usage；完整
`story-long-write` 保留为 source/reference，不再每章全量注入。

## 删除与归档

- 删除未接入真实 pipeline 的 role coalescing 子系统；壳可以在单个 role session
  内使用自己的 subagent、board 或 session，但不能合并跨 lifecycle gate 的角色。
- 退役 `codex_full_driver` 活动模板、手工 Codex 配额/交接分支、旧 role registry、
  未使用的 Aider plan adapter 和未注册 agent templates。
- 归档会改写 workflow/lifecycle、读取 rebuild 事实并直写旧正文目录的
  `scripts/write_chapters.py`，以及项目专用 `reader_server.py`；它们不再是活动入口。
- 收缩根 README、操作模型、能力说明、acceptance 文档和历史计划；历史正文放入
  `docs/archive/`，活动文档不再复制易漂移的模型矩阵、测试数字或 acceptance 快照。
- Web UI 删除浏览器本地伪模型切换、伪额度和固定 DeepSeek/Codex/Qwen 状态，改为显示
  `workflow_plan.yml` 已解析的真实 role profile。

## 记忆、产物与交接

- 根仓库唯一可写交接是 `PROJECT_HANDOFF.md`；旧 `HandOff.md` 路径仅可读发现。
- canonical handoff 使用 `Working root: .`，不提交本机绝对路径。
- 项目正式产物统一进入 `projects/<Project>/production/`；候选只在 run 内，archive
  进入项目自己的 `archive/`。Writer、脚本或外部壳不能直接 promotion。
- 项目对话日志改为中性的 `08_WORKER_DIALOGUE_LOG.md`，不再把 Codex 写成任务宿主。
- active skill 目录不再积累可变 usage ledger；历史 ledger 已归档，后续 usage 为
  run-local evidence。

## 测试治理

- 活动顶层测试模块 329 个，最终收集 2738 个用例。
- `tests/fixtures` 从 pytest 自动收集边界排除，fixture 仓库里的 `test_*.py` 仅作为
  输入数据。
- AST fingerprint gate 阻止完全重复的测试实现；相似但验证不同 route、边界或失败
  合同的测试不为减少文件数而强行合并。
- YAML/config 读取按声明依赖加载并缓存不可变快照，对调用方返回隔离副本。
- 默认全量测试不会启动 live provider、私有 production、promotion 或网络生产任务。

详细规则见 `docs/TEST_SUITE_GOVERNANCE.md`。

## 最终验证

```text
python3 -m pytest --collect-only -q
2738 tests collected

python3 -m pytest -q --durations=40
2736 passed, 2 skipped, 11 warnings in 208.35s

./agentlab.sh model-doctor
status: pass; resolved_profile_count: 135; issue_count: 0

./agentlab.sh protocol-doctor
status: pass; checks: 108; failed: 0

./agentlab.sh repo-hygiene-check --root .
PASS; hard violations: 0; warnings: 0

python3 scripts/audit_text_integrity.py --fail-on-suspicious
PASS; files scanned: 1425; suspicious files: 0
```

11 个 warning 来自 local-search 缺失目录 fixture，属于测试刻意验证的可观测告警。
本轮未配置或同步 250 工作区，也未执行任何生产模型调用。
