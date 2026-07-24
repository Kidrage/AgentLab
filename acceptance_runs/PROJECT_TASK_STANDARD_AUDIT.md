# 项目任务与存储标准审计

审计时间：2026-07-24。此报告只记录本地 metadata、权威指针和 runtime doctor 的
结果，不把候选正文或历史 prompt 当成事实。

## 结论

`Crown_of_Ash` 已收敛为一个 Runtime v2 Task authority、一个正式蓝本指针和一个
正式 fact authority 指针。`AgentLab` 的两个 legacy smoke/probe run 已通过 Runtime
v2 migration v3 验证（含 hash-verified provenance），随后连同六个 CLI、pytest 和
scratch run 一并从本地主生产树退休。`NovelGen` 已建立唯一 blueprint authority、项目 Agent 团队和
修改合同，但通用 project-specific blueprint validator/sealer 尚未实现，因此新正文
继续 fail-closed。已有 production 的原子多 artifact 蓝本替换接口同样尚未实现；
`materialize-blueprint` 仅允许空项目初始化，不能用于覆盖已有蓝本。

| 项目 | 任务权威 | 当前正式内容 | 结论 |
| --- | --- | --- | --- |
| `Crown_of_Ash` | `runtime/tasks/task-crown-runtime-v2-first-prose-20260722/events.jsonl` | blueprint、fact authority、canonical shards、1–25 章卡；production manuscript 为空 | Runtime v2 doctor 通过；蓝本已重新 seal 并通过验证；尚未获准正式连载 |
| `NovelGen` | `runtime/tasks/blueprint_authority_normalization_20260724/events.jsonl` | 40 章 accepted production baseline、唯一 blueprint authority、agent team、修改合同 | L3 输入分类已通过；任务尚待 generic validator/sealer 与正式 review evidence，故 blueprint 为 `registered_pending_generic_validation`，禁止新增正文 |
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
  `canon_promotion/project_wide/canonical` 分类为 L3 且 admission-ready；任务未完成，
  不构成“已封存”声明。
- RAG 全量重建后：`AgentLab` 58 条 project record、`Crown_of_Ash` 83 条、
  `NovelGen` 378 条；`knowledge doctor` 为 PASS。NovelGen 未被 blueprint authority
  哈希绑定的 `project_fact_snapshot.yml` 已明确排除。审计期间发现并修复了
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
5. `NovelGen` 和未来新小说不得直接复制 Crown 的人员、尺度或事实规则；NovelGen
   已有自己的 authority/Agent contract，但在 generic validator/sealer 和 review
   evidence 完成前，不能将 `registered` 冒充 `sealed`。
6. 已注册蓝本不得用 `materialize-blueprint` 覆盖。当前缺少
   `atomic_existing_blueprint_replacement` 公共接口；任何修改只能先停留在 Runtime v2
   candidate，`--allow-registered-blueprint-drift` 仅是审计后的管理员恢复手段。
7. 已删除本地主树中的 `projects/AgentLab/archive/run_history/` 和
   `projects/novel-moon-in-seal/`；清理前通过 `rsync -ani --delete` 确认与
   `truenas:/mnt/hdd2/AgentLab_WorkSpace/AgentLab/agents/codex/archives/2026-07-24-workspace-convergence/`
   的备份一致。它们不再可被 current acceptance 或 RAG 当作兜底证据。
8. AgentLab 的两个 migration v3 smoke/probe Task 也已备份到同一归档的
   `agentlab-runtime-v2-retired/` 并通过 dry-run 一致性校验；当前可调度 Task
   authority 只剩 Crown 与 NovelGen 各一个。

详见 [长篇叙事项目操作标准](../docs/NARRATIVE_PROJECT_OPERATING_STANDARD.zh-CN.md)。
