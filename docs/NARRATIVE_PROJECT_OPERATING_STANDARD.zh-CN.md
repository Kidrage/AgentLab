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
| `NovelGen` | 40 章 accepted baseline；已注册唯一 project-specific blueprint authority、Agent team 与修改合同，但 generic validator/sealer 尚未实现 | `project_artifact_index.yml` 指向的 `production/blueprint_authority.yml`、`production/agent_team.yml`、`production/narrative_modification_contract.yml`、manuscript/bible/outlines 与 fact snapshot | blueprint 当前是 `registered_pending_generic_validation`；根目录旧内容、历史 runs、runtime 候选与 archive 均非当前事实，且不得新增正文 |
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

### 2. 修改已有故事蓝本

当前版本尚未暴露“已有 production 的原子多 artifact 替换”公共接口。用户修改请求仍
必须建立 Runtime v2 Task，并产出带旧版本哈希、预期新版本哈希、影响分析和审批证据的
candidate；但在该接口实现前不得把 candidate 晋升到 production，也不得通过手工覆盖
文件来规避门禁。此缺口登记为 `atomic_existing_blueprint_replacement`，是 Crown 正式
连载和通用 project-specific blueprint profile 的共同阻塞项。

`seal-blueprint --allow-registered-blueprint-drift` 只供灾难恢复/管理员对“已经由外部
审计并授权的变更”重建哈希与 receipt；它不是用户修改接口，也不证明替换动作本身原子、
可回滚或具备完整 lineage。没有通过 seal 的蓝本不能生成正文。

### 3. 注入一章或一批正文请求

正文请求先成为 Runtime v2 Task，而不是新建一个章节目录：

```bash
./agentlab.sh task create --project Crown_of_Ash --task-id <stable-task-id> \
  --title "第 026 章候选" --goal "<用户的本章目标、改动、禁区和验收条件>" \
  --input-profile-json '<由 Supervisor 产生的已验证 profile>' \
  --idempotency-key <unique-key>
```

随后为同一 Task 建立 Writer、领域专家、Reviewer 与 Verifier WorkItem，并把所选
`blueprint_authority`、`fact_authority`、章节卡、前章哈希和 RAG snapshot 绑定进 Attempt
receipt。用户可随时追加“改写第几章/保持什么不变”的目标，但不能通过修改旧 prompt 或
旧候选来改变已验收事实。

`narrative prepare-chapter` / `narrative review` 仍是 legacy `runs/` 兼容接口；它们不
能创建新的 v2 Task，也不能成为新长篇生产入口。当前 Crown Runtime v2 首章验证使用的
是受约束的 v2 Attempt 记录。把 legacy chapter helper 完整替换为 v2 packet 入口是
长篇生产启动前必须完成的 M3.1 项。

### 4. 全局人物、世界观或关系改动

全局改动必须先进入独立 Task 的 change proposal。Character / World / Timeline Agent
只写自己的候选范围；Writer 没有直接写 `world_rules`、角色 canonical state 或正式
manuscript 的权限。通过审查后，未来的原子 promotion 接口必须：

1. 更新候选 fact authority 或 canonical fragment；
2. 校验该改动的 source hash、受影响章节卡与 state projection；
3. 用 `narrative commit-fact-authority --project <Project>` 提交唯一事实 authority；
4. 通过尚待实现的原子替换接口重新 seal blueprint、更新 artifact index 与 project fact snapshot；
5. 重新构建该项目 RAG，再允许后续章节 Task 使用新事实。

因此“伊莎贝拉设定改一次”会形成一条有哈希的 authority revision，而不是在多个
人物文档、prompt 和正文之间留下相互矛盾的版本。

当前 `commit-fact-authority` 只能提交其既有单一事实 authority 边界，不能替代蓝本或
人物多 artifact 的原子更新；对应接口未完成时，全局改动只能停留在 candidate。

### 5. 正式输出位置

- 正式正文：`projects/<Project>/production/manuscript/`
- 正式设定/蓝本：`production/bible/`、`production/outlines/`、`production/canonical/`、
  `production/blueprint_authority.yml`、`production/fact_authority.yml`
- 当前选择指针：`project_artifact_index.yml`
- 项目事实投影：`project_brain/project_fact_snapshot.yml`
- 候选及执行证据：`runtime/tasks/<task_id>/`
- 被替换正式版本：`archive/<artifact_id>/<version>/`
- 仅溯源的不可写交付包：`deliveries/<package-id>/`

桌面目录只能是显式导出的阅读副本，不能被写回为事实源。

## 四、团队模板与未来项目准入

一个新长篇项目至少注册以下 Project Agents：World Architect、Character Keeper、
Timeline Keeper、Plot/Mystery Keeper、Writer、Reviewer。项目启用 Agent Organization
Layer 后，Agent manifest 的 `write_scope` 必须与上表的事实边界一致；Reviewer 只负责
整体质量，不替代领域 Agent 的长期状态职责。

新项目必须先完成 Project Truth 迁移或全新初始化，才能启用动态 Agent 团队；旧项目
不自动迁移。NovelGen 已建立非 Crown 专用的 project-specific authority 与团队合同，
下一道硬门是实现通用 blueprint profile validator/sealer、生成首批 chapter cards 并
补齐 L3 review evidence；不能把 Crown 的人物/尺度规则复制过去。

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

通用 `narrative-blueprint-authority/v1` 可在 `registered_pending_generic_validation`
阶段用于构建审计/校验所需的派生 RAG，但采集器会验证 artifact index、每个声明的
`source_artifacts` 路径和 SHA256；任一不匹配会把该项目的正式索引结果置空。这个能力
不会自动采集 authority 未声明且未绑定哈希的 `project_brain` 文件。这个能力不等于
正文生产许可：只有未来 generic validator/sealer 将状态晋升为
`validated_sealed`，正文门才可打开。
