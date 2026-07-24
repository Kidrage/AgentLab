# 项目任务与存储标准审计

审计时间：2026-07-24。此报告只记录本地 metadata、权威指针和 runtime doctor 的
结果，不把候选正文或历史 prompt 当成事实。

## 结论

当前活动工作区与 RAG scope 已收敛为 `AgentLab` 和 `Crown_of_Ash` 两个项目；
活动叙事项目只有 `Crown_of_Ash`。`Crown_of_Ash` 保持一个 Runtime v2 Task
authority、一个正式蓝本指针和一个正式 fact authority 指针。其余九个旧项目目录已于
2026-07-25 移到可恢复的本机废纸篓归档包，不再进入项目发现、任务治理或 RAG。
`NovelGen` 的嵌套 Git 元数据随目录完整保留，但其旧 production、task 与 RAG shard
均不是当前事实。恢复任一旧项目必须经过显式还原、allowlist 准入、权威迁移和全量重建。

| 项目 | 任务权威 | 当前正式内容 | 结论 |
| --- | --- | --- | --- |
| `Crown_of_Ash` | `runtime/tasks/task-crown-runtime-v2-first-prose-20260722/events.jsonl` | blueprint、fact authority、canonical shards、1–25 章卡；production manuscript 为空 | Runtime v2 doctor 通过；蓝本已重新 seal 并通过验证；尚未获准正式连载 |
| `AgentLab` | 无当前 Task | 源码、配置、文档和 acceptance evidence | 2 个已验证 migration v3 的 smoke/probe Task 已备份到 TrueNAS 后退休；本地主树不再把开发烟测当生产任务 |
| 已退出项目 | 无 active runtime | 无当前正式事实入口 | `AgentLab_System`、`NovelGen`、`ProductDocs`、五个 demo 与 `test_proj` 已移出 `projects/`；旧目录只在可恢复归档包中保留 |

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
- 交付前逐项目重建结果：`AgentLab` 57 条、`Crown_of_Ash` 83 条 active project
  record，均写入 sealed project snapshot；全局 `knowledge doctor` 为 PASS
  （5 spaces，37,660 records / 1,552 eligible）。清理与模型治理 checkpoint
  build receipt 为
  `kbuild_70736396536b702c82605a654633d3e023a2aa617dac4ba4d31f6f14aed6b4cb`，
  index snapshot 为
  `idx_8d1a34ae6b4abee0518695e4b14868558a567e27ce2e33896bb1537450b712b4`。
  `project.AgentLab_System`、`project.NovelGen` 与
  `project.novel-moon-in-seal` 已退休，共享 domain shard 已清除 627 条退出项目记录。
  未被 blueprint authority / artifact index 选择的 project brain 内容会被排除。
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
5. 未来新小说不得直接复制 Crown 的人员、尺度或事实规则；每个项目使用自己的
   authority、Agent contract、fact snapshot 和 acceptance rules。
6. 已注册蓝本不得用 `materialize-blueprint` 覆盖。修改必须先由
   `compile-task-packet` 建立 L3 Task，由 Supervisor 产出 Brain scope/execution plan，
   再由领域 Agent、Producer、Reviewer、Verifier 执行并绑定不可变 evidence，最后调用
   `publish-blueprint-change`。`--allow-registered-blueprint-drift` 仅是审计后的管理员
   恢复手段。
7. 已删除本地主树中的 `projects/AgentLab/archive/run_history/` 和
   `projects/novel-moon-in-seal/`；清理前通过 `rsync -ani --delete` 确认与
   `truenas:/mnt/hdd2/AgentLab_WorkSpace/AgentLab/agents/codex/archives/2026-07-24-workspace-convergence/`
   的备份一致。它们不再可被 current acceptance 或 RAG 当作兜底证据。
8. 当前本地 Task authority 为 Crown 1 个、AgentLab 0 个；退出项目的 task 不可由
   当前 workspace 调度。
9. 本次退出目录位于当前用户的
   `~/.Trash/AgentLab_projects_cleanup_20260725-013259/`，可恢复但不
   是 source of truth。确认不再需要后可由用户在 Finder 中清空废纸篓。
10. 全量回归暴露旧 CLI 测试会把 `DemoProject`、四个 `demo_*` 和 `test_proj`
    写回真实 `projects/`。这些测试产物已移入同一废纸篓归档包的
    `test_artifacts_after_*` 子目录；`m1-demo` 与 `activation-plan` 现均提供显式
    `--root`，相关测试固定使用 pytest 临时根。修复后的定向回归结束后，真实
    `projects/` 仍严格只有 AgentLab 与 Crown。最终全量回归为
    3,437 passed / 2 skipped / 11 warnings，回归结束后目录约束仍成立。

详见 [长篇叙事项目操作标准](../docs/NARRATIVE_PROJECT_OPERATING_STANDARD.zh-CN.md)。
