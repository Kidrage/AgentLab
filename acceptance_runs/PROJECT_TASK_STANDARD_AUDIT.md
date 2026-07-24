# 项目任务与存储标准审计

审计时间：2026-07-24。此报告只记录本地 metadata、权威指针和 runtime doctor 的
结果，不把候选正文或历史 prompt 当成事实。

## 结论

`Crown_of_Ash` 已收敛为一个 Runtime v2 Task authority、一个正式蓝本指针和一个
正式 fact authority 指针。`AgentLab` 的两个 legacy smoke/probe run 已通过 Runtime
v2 migration v3 验证（含 hash-verified provenance），随后连同六个 CLI、pytest 和
scratch run 一并从本地主生产树退休。`NovelGen` 已建立唯一 blueprint authority、静态项目 Agent 团队合同和
修改合同；通用 project-specific validator/sealer、Runtime v2 packet、append-only
prompt 和原子多 artifact publisher 均已实现。publisher 现在要求每个声明通过的领域
WorkItem 都有成功 Attempt，Producer/Verifier 输出已登记为不可变 ArtifactVersion 并
绑定 evidence，单独伪造 acceptance YAML 不能发布。`materialize-blueprint` 仍只允许
空项目初始化，不能用于覆盖已有蓝本。

| 项目 | 任务权威 | 当前正式内容 | 结论 |
| --- | --- | --- | --- |
| `Crown_of_Ash` | `runtime/tasks/task-crown-runtime-v2-first-prose-20260722/events.jsonl` | blueprint、fact authority、canonical shards、1–25 章卡；production manuscript 为空 | Runtime v2 doctor 通过；蓝本已重新 seal 并通过验证；尚未获准正式连载 |
| `NovelGen` | 两个 Runtime v2 账本：`blueprint_authority_normalization_20260724` 与 `narrative_authority_interface_activation_20260724` | 40 章 accepted production baseline、唯一 sealed blueprint authority、静态 agent team contract、修改合同、fact snapshot | validator/sealer/publisher 与 RAG doctor 通过；接口激活是 bootstrap 治理迁移，不伪装成已执行的专家生产任务；Project Truth 冲突尚未人工裁决，因此 Registry 仍关闭，后续启用前必须提交显式 migration manifest |
| `novel-moon-in-seal` | 无 | 无 | 旧验证工作区已从本地生产树移除；删除前完整备份到 TrueNAS Codex archive，且不再进入 RAG allowlist |
| `AgentLab` | 无当前 Task | 源码、配置、文档和 acceptance evidence | 2 个已验证 migration v3 的 smoke/probe Task 已备份到 TrueNAS 后退休；本地主树不再把开发烟测当生产任务 |
| demo/test projects | 无 active runtime | 非当前生产范围 | `test_proj` 旧 run 和空 `NovelGen/runs` 已清理；测试夹具只存在于测试临时目录 |

## 已验证的权威边界

- `Crown_of_Ash/project_artifact_index.yml` 对 `crown_blueprint_01` 和
  `crown_fact_authority_01` 均只有一个 `current` 记录。
- `governance doctor --project Crown_of_Ash`：pass，未发现未登记的 legacy fact root。
- `runtime-v2 doctor --project Crown_of_Ash`：pass，1 个 v2 Task、60 条 hash-chain
  events。
- migration v3 的测试和实际迁移均证明 legacy state/request snapshot path、SHA256
  与 provenance root 可在删除旧 runs 后独立通过 doctor；随后这两个 smoke/probe
  Task 按用户当前任务边界整体归档。当前 `runtime-v2 doctor --project AgentLab`：
  pass，0 Task。
- `NovelGen` 的 blueprint normalization Task 使用
  `canon_promotion/project_wide/canonical` 分类为 L3 且 admission-ready。其
  project-specific authority 已由独立 validator/sealer 封存，封存声明来自
  `project_brain/blueprint_validation_receipt.yml`，不从 Task 状态反推。
- 接口激活 Task 保留了当时的 3 条编译事件。它发生在 Runtime evidence 强制策略落地
  之前，只作为 bootstrap provenance；没有补造 Attempt 或把 Task 状态伪改为
  completed。其旧 publication command 不允许 idempotent replay；当前 truth 继续由
  seal receipt/index 验证，新 publisher 路径不存在这一豁免。
- 交付前逐项目重建结果：`AgentLab` 57 条、`Crown_of_Ash` 83 条、`NovelGen`
  384 条 project record，均写入 sealed project snapshot；全局 `knowledge doctor`
  为 PASS（8 spaces，38,794 records / 1,721 eligible）。
  未被 blueprint authority / artifact index 选择的 project brain 内容会被排除。
  审计期间发现并修复了
  `SourceCollector` 只识别 Crown 专用 blueprint schema、导致 NovelGen 假健康为
  0 条记录的问题；通用 project-specific authority 现在仅在全部 source artifact
  哈希匹配时进入索引，任一漂移仍整项目 fail-closed。
- `narrative validate-blueprint --project Crown_of_Ash --chapter-start 1 --chapter-end 25`：pass。
- `task list --project Crown_of_Ash --include-legacy` 仅显示该 v2 Task；不存在可读 legacy
  Task。

## 保留与删除规则

1. 任何新用户目标只能创建 Runtime v2 Task；章节、重试、复审和替代 worker 都是
   WorkItem/Attempt，不是新的 task directory。
2. `production/`、`project_brain/` 和 artifact index 是正式内容来源；候选、日志、
   archive 和 deliveries 永不自动回流。
3. `deliveries/` 只允许保存 hash-bound evidence package；其中的 `runs/` 目录是包内
   provenance，不是可调度 runtime。
4. 已关闭的 raw attempt logs 可用 `runtime-v2 compact-logs` 进行 hash-gated gzip
   收缩；本次 Crown 已压缩 16 个日志，收据在 runtime retention 目录。
5. `NovelGen` 和未来新小说不得直接复制 Crown 的人员、尺度或事实规则；每个项目使用
   自己的 authority、Agent contract、fact snapshot 和 acceptance rules。
6. 已注册蓝本不得用 `materialize-blueprint` 覆盖。修改必须先由
   `compile-task-packet` 建立 L3 Task，由 Supervisor 产出 Brain scope/execution plan，
   再由领域 Agent、Producer、Reviewer、Verifier 执行并绑定不可变 evidence，最后调用
   `publish-blueprint-change`。`--allow-registered-blueprint-drift` 仅是审计后的管理员
   恢复手段。
7. 已删除本地主树中的 `projects/AgentLab/archive/run_history/` 和
   `projects/novel-moon-in-seal/`；清理前通过 `rsync -ani --delete` 确认与
   `truenas:/mnt/hdd2/AgentLab_WorkSpace/AgentLab/agents/codex/archives/2026-07-24-workspace-convergence/`
   的备份一致。它们不再可被 current acceptance 或 RAG 当作兜底证据。
8. AgentLab 的两个 migration v3 smoke/probe Task 也已备份到同一归档的
   `agentlab-runtime-v2-retired/` 并通过 dry-run 一致性校验；当前本地 Task
   authority 为 Crown 1 个、NovelGen 2 个、AgentLab 0 个。

详见 [长篇叙事项目操作标准](../docs/NARRATIVE_PROJECT_OPERATING_STANDARD.zh-CN.md)。
