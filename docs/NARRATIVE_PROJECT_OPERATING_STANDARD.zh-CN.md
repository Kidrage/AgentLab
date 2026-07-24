# 长篇叙事项目操作标准

本文件规定长篇叙事项目如何保持“当前唯一真相”、如何接收修改，以及在什么条件下
允许生成正文。它补充而不替代以下机器可读权威：

- `config/content_project_governance.yml`：项目层事实根与归档边界；
- `config/task_input_tiers.yml`、`config/task_runtime_v2.yml`：Task Runtime v2 的准入与门；
- `projects/<Project>/project_artifact_index.yml`：每个正式 artifact 的唯一 current 指针；
- `projects/<Project>/runtime/tasks/<task_id>/events.jsonl`：一个业务目标的不可变执行账本。

## 一、唯一性规则

```text
用户请求
  -> Runtime v2 Task（一个可独立验收的目标）
  -> candidate / staged artifact（可多版、不可当事实）
  -> 通过审查、lineage 与审批
  -> production/ + project_artifact_index.yml 的唯一 current 指针
  -> archive/ 或 sealed deliveries/ 的只读溯源材料
```

同一 `artifact_id` 只能有一个 `current`。`runs/`、`candidates/`、旧目录、尝试日志、
审阅草稿和桌面导出都不是当前事实；它们不能覆盖 `production/`、`project_brain/` 或
artifact index。已选择的历史依据应保留在可哈希的 sealed `deliveries/` 或 `archive/`，
但永远不被 Writer 当作当前内容。

Task 也只允许一个权威：`runtime/tasks/<task_id>/events.jsonl`。章节、重试、复审与
备选生成是同一 Task 下的 WorkItem / Attempt，不得另起同目标的 `runs/task_*` 目录。
`runtime/task_index.yml` 和 `projections/` 可重建，不能手工修成“真相”。

## 二、当前项目状态

| 项目 | 现状 | 可当正式事实的入口 | 不可误用的内容 |
| --- | --- | --- | --- |
| `Crown_of_Ash` | 已有已封存的 1,980 章蓝本与 1–25 章卡；production 正文仍为空，因此尚未进入正式连载 | `production/blueprint_authority.yml`、`production/fact_authority.yml`、`production/canonical/`、`production/chapter_cards/` 与 `project_artifact_index.yml` | Runtime v2 的 chapter-001 是候选；所有历史 runs 及 sealed delivery 内的原 runs 仅作溯源 |
| `NovelGen` | 40 章 accepted baseline；project-specific blueprint 已通过通用 validator/sealer，修改合同与 fact snapshot 已用 bootstrap 原子接口发布 | `project_artifact_index.yml` 唯一选择的 `production/blueprint_authority.yml`、静态 Agent team contract、修改合同、manuscript/bible/outlines 与 fact snapshot | blueprint 为 `validated_sealed`；根目录旧内容、runtime 候选与 archive 均非当前事实；Project Truth/Registry 迁移尚待显式冲突裁决，新正文 Task 在此之前不会获得 Agent manifest 绑定 |
| `novel-moon-in-seal` | 旧验证工作区已从本地主生产树移除，并备份到 TrueNAS Codex archive | 无本地正式事实入口 | 不在 RAG allowlist；不得作为新小说的 production、模板或 current evidence |

`Crown_of_Ash` 的蓝本校验必须通过后才可编译 Writer context。它采用 fail-closed：
组件哈希、事实投影、章节卡或 required provenance 任一漂移都会阻断正文任务。Crown 的
sealed delivery provenance 位于 `deliveries/`，是为了避免恢复废弃的 task runtime；它
只证明来源，不是正文或设定的并列版本。

## 三、用户可操作接口

### 1. 新建故事蓝本

不要直接编辑 `production/`。先建立一个 Runtime v2 Task，把用户的故事要求、篇幅、
分卷、题材禁区、人物边界和验收规则写入目标；蓝本团队在该 Task 下产出
`runs/<legacy-task>/artifacts/blueprint_bundle.yml` 的兼容候选或对应 v2 artifact version。
`materialize-blueprint` 只用于 production 尚不存在或为空的新项目初始化；命令会先在
临时目录验证候选，再原子安装。它不是已有蓝本的更新接口：

```bash
./agentlab.sh narrative materialize-blueprint --project Crown_of_Ash --bundle <project-local-candidate-bundle>
./agentlab.sh narrative seal-blueprint --project Crown_of_Ash
./agentlab.sh narrative validate-blueprint --project Crown_of_Ash --chapter-start 1 --chapter-end 25
```

通用 `seal-blueprint` 也是一次性的 bootstrap 接口，只把已经登记且通过校验的初始
production 蓝本变成 sealed truth。它记录的 `source_task` 是初始化归因，不是假装
存在某个 Runtime artifact；artifact index 会明确写入实际
`production/blueprint_authority.yml` 与
`provenance_kind: bootstrap_in_place_validation`。蓝本 sealed 后的任何内容修改都必须
走下一节的 Runtime v2 transaction publisher。

### 2. 修改已有故事蓝本

已有 production 的修改使用通用 transaction 接口。候选与 acceptance receipt 必须在
同一个 Runtime v2 Task 的 `artifacts/` 下，manifest 必须绑定旧 authority/index SHA256、
每个候选源 SHA256、目标 artifact id、领域审查与 Verifier 结果：

```bash
./agentlab.sh narrative compile-task-packet --project <Project> \
  --task-id <task-id> --request <structured-request.yml>
./agentlab.sh narrative publish-blueprint-change --project <Project> \
  --manifest <runtime-task>/artifacts/blueprint_change_set.yml \
  --acceptance-receipt <runtime-task>/artifacts/blueprint_acceptance_receipt.yml
```

publisher 在持有项目锁后先做 CAS、在隔离 stage 中校验完整项目视图，再把旧 artifact
复制到 `archive/narrative_blueprints/<transaction-id>/`。production 逐项安装期间旧
artifact index 会因哈希不匹配而 fail-closed；只有全部安装和验证通过后才最后原子切换
`project_artifact_index.yml`。进程内失败立即回滚；硬中断留下的 transaction backup
会在下次调用时恢复。项目 RAG 同步成功后才以一次性创建方式写入不可变 publication
receipt；同步或 receipt 创建失败同样恢复旧 production 与 index。相同 idempotency
key 只能重放同一 manifest，重放不会修改既有 receipt。若 RAG 已同步而后续步骤失败，
回滚会把项目与领域 namespace 标记为 stale，强制下一次正式使用前重建，避免新索引继续
伪装成旧 truth。重放还会重新验证完整 Runtime evidence、acceptance hash、SYNCED 状态
及当前知识快照；一次性 receipt 被改写后会 fail-closed。

文件形式的 `reviews: pass` 不构成验收。packet 会先创建 `brain-plan`，Supervisor
必须以 Runtime trace 固化 `brain_scope_decision` 和 `execution_plan`；之后每个
required WorkItem 都必须是 `accepted` 且至少有一个可复验的成功 Attempt。变更 manifest
必须由 `artifact-producer` 的输出登记为不可变 ArtifactVersion，acceptance receipt
必须由 `verifier` 的输出登记；二者都必须绑定当前输入/RAG evidence，且输出 SHA256
完全一致。缺少任一账本证据，publisher 在写 production 前拒绝。

`seal-blueprint --allow-registered-blueprint-drift` 仍只供 Crown 管理恢复；普通修改必须
走 `publish-blueprint-change`。没有匹配 seal receipt 的蓝本不能生成正文。
`publish-blueprint-change` 同时接受 `blueprint_change` 与
`global_character_change` packet；两者使用同一组 CAS、Runtime evidence、归档和原子
切换保证。

### 3. 注入一章或一批正文请求

正文请求先成为 Runtime v2 Task，而不是新建一个章节目录。推荐入口会自动创建领域
Supervisor、领域专家、Writer、Reviewer、Verifier DAG，并绑定 blueprint、artifact index、fact snapshot、
manuscript baseline 与 Writer RAG snapshot：

```bash
./agentlab.sh narrative compile-task-packet --project <Project> \
  --task-id <stable-task-id> --request <structured-request.yml>
./agentlab.sh narrative append-task-instruction --project <Project> \
  --task-id <same-task-id> --instruction-id <next-id> \
  --request <structured-request.yml>
```

request 必须包含 `change_kind`、`requested_delta`、`target_scope`、
`preserve_invariants`、`allowed_retcons`、`acceptance_rules` 和 `idempotency_key`。
每次追加都成为 `USER_INSTRUCTION_APPENDED` 哈希链事件；旧 prompt 不可覆盖。若蓝本、
fact snapshot 或 RAG snapshot 已变化，旧 Task 拒绝追加并要求编译新 Task。
追加只允许发生在执行尚未开始时；一旦已有领域 trace、Attempt、ArtifactVersion 或
EvidenceRecord，就必须编译一个 replacement Task。publisher 还会检查全部成功 Attempt、
领域 trace 与候选证据均晚于最后一条用户指令，防止绕过公开入口后用旧证据发布新要求。

`narrative prepare-chapter` / `narrative review` 仍是 legacy `runs/` 兼容接口；它们不
能创建新的 v2 Task，也不能成为新长篇生产入口。当前 Crown Runtime v2 首章验证使用的
是受约束的 v2 Attempt 记录。新项目不得再把 legacy helper 当作生产入口。

当前通用接口只完成正文候选的 Runtime v2 编译与执行证据绑定；把
`manuscript_candidate/` 中某一版本提升为 `production/manuscript/` 的
chapter-specific immutable release bridge 尚未接入这条 packet 流程。既有 Candidate
Set promotion 是独立的旧发布面，不能被当作该桥已经实现。该缺口关闭前，新章节可以
生产和复审候选，但不得宣称已经成为 current manuscript。

### 4. 全局人物、世界观或关系改动

全局改动必须先进入独立 Task 的 change proposal。Character / World / Timeline Agent
只写自己的候选范围；Writer 没有直接写 `world_rules`、角色 canonical state 或正式
manuscript 的权限。通过审查后，原子 promotion 接口必须：

1. 更新候选 fact authority 或 canonical fragment；
2. 校验该改动的 source hash、受影响章节卡与 state projection；
3. 用 `narrative commit-fact-authority --project <Project>` 提交唯一事实 authority；
4. 通过 `publish-blueprint-change` 重新 seal blueprint、更新 artifact index 与 project fact snapshot；
5. 重新构建该项目 RAG，再允许后续章节 Task 使用新事实。

因此“伊莎贝拉设定改一次”会形成一条有哈希的 authority revision，而不是在多个
人物文档、prompt 和正文之间留下相互矛盾的版本。

`commit-fact-authority` 只提交既有单一事实 authority；人物多 artifact 更新统一走
blueprint transaction。尚未产品化的是跨人物/章节/伏笔的 impact graph，而不是发布
原子性；在 impact evidence 不完整时 promotion 仍会阻断。

### 5. 正式输出位置

- 正式正文：`projects/<Project>/production/manuscript/`
- 正式设定/蓝本：`production/bible/`、`production/outlines/`、`production/canonical/`、
  `production/blueprint_authority.yml`、`production/fact_authority.yml`
- 当前选择指针：`project_artifact_index.yml`
- 项目事实投影：`project_brain/project_fact_snapshot.yml`
- 候选及执行证据：`runtime/tasks/<task_id>/`
- 被替换正式版本：`archive/narrative_blueprints/<transaction-id>/<original-path>`
- 仅溯源的不可写交付包：`deliveries/<package-id>/`

桌面目录只能是显式导出的阅读副本，不能被写回为事实源。

## 四、团队模板与未来项目准入

一个新长篇项目至少注册以下 Project Agents：Supervisor、World Architect、Character
Keeper、Timeline Keeper、Plot/Mystery Keeper、Blueprint Producer、Writer、Reviewer
与 Checker/Verifier。项目启用 Agent Organization Layer 后，packet 编译器会在创建
Task 前把每个 WorkItem 绑定到当前 truth snapshot、manifest revision 与 contract hash；
团队缺员或 Agent 非 active 时不会留下半创建 Task。Agent manifest 的 `write_scope`
必须与上表的事实边界一致；Reviewer 只负责整体质量，不替代领域 Agent 的长期状态职责。

新项目必须先完成 Project Truth 迁移或全新初始化，才能启用动态 Agent 团队；旧项目
不自动迁移。NovelGen 已建立非 Crown 专用的 project-specific authority 与静态团队
合同，但它当前仍是 `project_truth_mode: legacy`、`enable_project_agents: false`；
自动冲突扫描要求人工 migration manifest，因此不得把它描述为已启用 Registry 的 M3
项目。通用 blueprint profile、Runtime v2 packet、Agent-bound 编译器和原子 publisher
已由隔离的 enabled-project 测试覆盖；新项目仍须生成自己的 chapter contracts、显式
Project Truth 迁移和 L3 review evidence，不能复制 Crown 的人物/尺度规则。

## 五、RAG 边界与启动门

RAG 是派生索引，不是 source of truth。每次正式 blueprint、fact authority、章节卡、
project brain 或 AgentLab 治理逻辑变更后执行：

```bash
./agentlab.sh knowledge build --project <Project>
./agentlab.sh knowledge doctor
```

只有 project allowlist 内的项目可持久化其 project RAG；candidate、attempt log、旧
runs、archive 和桌面导出默认不会变成可检索的当前事实。`knowledge doctor`、
`runtime-v2 doctor`、`narrative validate-blueprint` 和必要的 content promotion gate 都
通过，才可启动下一批正文。

通用 `narrative-blueprint-authority/v1` 的采集器会验证 artifact index、每个声明的
`source_artifacts` 路径和 SHA256；任一不匹配会把该项目的正式索引结果置空。未被
artifact index 选择的 `project_brain` 文件不会自动进入事实空间。正文 packet 还会
验证 sealed receipt 与 Writer RAG snapshot 中的 authority、修改合同、fact snapshot
哈希完全一致；`registered_pending_generic_validation` 只允许修复/审计，不能生产正文。
