# AgentLab / 智能体实验室

语言：[English](README.en-US.md) | [中文](README.zh-CN.md)

AgentLab 是一个本地优先的 AI Production OS / Project-to-Revenue OS，仍在持续开发中。它不是 Codex、Claude Code、Cline、Hermes、OpenClaw 或其他执行器/前端 Agent 的替代品。AgentLab 的定位是后端事实源：让长期项目保持可治理、可检查、可恢复、可审计，并用证据闭环。

当前仓库：`Kidrage/AgentLab` 的 `main` 分支。

## AgentLab 做什么

AgentLab 把粗略需求转成受治理的项目工作流：

```text
用户需求
-> mission / task contract
-> 项目路线图
-> 阶段计划
-> 任务包
-> 本地或外部执行器 handoff
-> 产物与证据摄入
-> review / retry / recovery
-> 阶段验收
-> 项目记忆更新
-> 交付包
-> 未来的资产、生产、收入、SOP 闭环
```

默认设计是本地优先、审批门控。真实外部执行、外部技能安装、网络访问、平台发布、公开服务绑定都默认关闭，只有在策略允许并经过用户明确批准后才可执行。

## 当前阶段

AgentLab 已经通过 P 系列和 S 系列工作具备长期项目治理底座。下一条产品主线是 M 系列：

- `M1 Project Governance Kernel`：正式化长期项目治理和本地 CLI 执行器协作。
- `M2 Operator OS / Transparent Control Plane`：通过 CLI/TUI/WebUI/assistant 模式透明化配置、审批、成本、观测和操作控制。
- `M3 Project-to-Revenue OS`：加入商业契约、资产血缘、生产管线、市场/渠道情报、分析、收入记录、合规、CRM 和 SOP 学习。

实际状态：AgentLab 正处在 M-series 对齐阶段。S7/S8 等底座能力已经实现很多，但在进入 M2/M3 之前，仍应先完成 M0/M1 的正式验收收敛。

## 已实现能力

### 核心运行时与治理

- 本地优先的任务状态、项目记忆、运行目录和证据产物。
- 规范任务生命周期，支持 checkpoint 和 resume。
- 9 Agent 分层运行模型：Supervisor、RepoScout、Researcher、InterfaceMapper、PromptEngineer、Coder、TesterAuditor、Verifier、Archivist。
- small、medium、interface-sensitive、research-sensitive、large/risky 等任务路由。
- 大脑治理：provider/model 策略、token 预算、路由感知执行。
- Budget Planner、BudgetGate、CostLedger v2、定价和成本追踪。
- Artifact Evidence Gate 和规范产物契约校验。
- 原子状态存储、进度追踪、任务索引、任务发现、任务恢复命令。
- 文件锁、过期锁恢复、崩溃安全任务处理。
- provider failover、provider 状态检查和模型配置诊断。

### CLI 与本地操作

- 一键入口：`./agentlab.sh`。
- 健康检查：`./agentlab.sh doctor`。
- 策略与模型检查：`policy-status`、`models`、`providers`、`model-doctor`。
- 任务操作：`init-task`、`task-list`、`task-open`、`task-map`、`task-artifacts`、`progress`、`pause`、`resume`。
- 管线操作：`run-agent`、`run-pipeline`、`run-next`、`lifecycle-status`、`artifact-check`。
- 本地 terminal chat，以及 Codex full-driver handoff/resume 辅助命令。
- project ops 命令：路由检查、仓库卫生检查、任务压缩、agent contribution 汇总。
- 备份、迁移、TrueNAS、sync 状态命令。

### P0 核心基础设施

- CostLedger v2、Cost Pricing、BudgetGate、Budget Planner。
- RepoManifest、CloneGuard、ResourceLedger。
- Artifact Evidence Gate。
- Pipeline Runner 和 Cost Tracker。

### P1 外部集成

- 外部技能注册表，默认禁用。
- ECC inventory scan-only 工作流。
- 面向 Codex/Cline/ECC 等工具的外部 agent handoff 产物，不自动执行。
- AnySearch adapter 默认禁用。
- CodeGraph adapter 仅本地/dry-run。
- Search provider base 和 local URL reader。

安全姿态：

- 外部技能默认不启用。
- 测试中不执行外部技能。
- 外部 agent 只做 handoff，且需要审批。
- 外部成本默认 unknown，除非用户明确报告。
- 外部结果必须有证据，不能直接视为通过。

### P2 Review、Retry、Governance、Recovery

- 3E Reviewer、review models、review policy。
- Retry Manager、retry policy、provider scorecard。
- 用于 governance-aware 路由更新的 patch builder/applier。
- Context Governance 和 context pack 生成。
- P2 Closure Runner 和 Capability Map。
- 性能、成本、路由反馈治理模块。
- Failure Recovery 栈：failure event、classifier、diagnosis、recovery plan、verdict、retry policy、human review、resume policy、closure、closure feedback、redaction。
- Recovery CLI：`failure-diagnose`、`failure-status`、`recovery-plan`、`recovery-smoke`、`recovery-approve`、`recovery-reject`、`recovery-stop`、`recovery-status`、`recovery-feedback`。

### S7 长项目编排器

- 确定性的 project brain 生成，不调用 LLM、不联网、不派发外部执行器。
- Roadmap、milestone graph、phase plan、summary、snapshot、acceptance history、next actions。
- CLI：`project-brain-init`、`project-plan`、`project-next`、`phase-accept`。
- Phase acceptance 可推动 accept、retry、redesign、split、rollback、ask-user 决策。

### S8 执行器连接闭环

- 阶段感知 executor task packet。
- 面向本地 CLI 或手动/外部执行器的 connector contract 和 handoff markdown。
- Mock executor 支持和 evidence ingestion。
- 外部执行器结果只是证据，必须通过 phase acceptance 才能接受。
- CLI：`executor-task-create`、`executor-result-ingest`、`executor-review`。

### S9 Capability Fabric

- 确定性、mock-first 的 capability registry。
- 内置 capability：filesystem、shell、git、web search、browser fetch、document/media understanding、database、GitHub ops、IDE handoff、OpenClaw notify。
- Permission gate 覆盖 missing、disabled、approval-required、shell、network、write、external 能力。
- Capability gap decision card。
- Mock-only vision/audio/document result contract。
- Capability fabric 不执行外部工具、不安装模型、不安装包。

### S10 泛化评估与 CI Gates

- Offline-only generalization evaluation suite。
- Fixture domain：docs、CLI、capability gap、recovery、project brain、mock search/repo workflow。
- 本地 CI gate policy：text integrity、compileall、focused tests、generalization suite、CLI help。
- 套件中不调用模型、web、browser、media、OCR、database、GitHub 或外部 agent。

### S11 Ops Console

- 本地-only、read-only 的 operations console snapshot。
- Snapshot 覆盖 project overview、project brain、roadmap、phase、task packet、skill、capability、recovery、evidence、budget、resource ledger。
- dry-run server plan，策略会拒绝公开 bind 地址。
- secrets 和 private paths 会被 redacted。
- CLI core 不依赖 UI。

### S12 Productization And Service Factory

- 本地优先的 service factory planning。
- 粗略客户需求可匹配到 service catalog entry。
- 确定性的 quote estimate、timeline estimate、risk notes、delivery package skeleton。
- 服务类型包括 repo cleanup、bug fix plan、longform blueprint、company research、document summary、spreadsheet cleanup、local file organization、audio analysis plan、multimodal review、personal automation workflow。
- 生成的交付包分离 final summary、acceptance history、risks、reproduction commands、next steps、artifacts 和 evidence。
- 不自动执行外部任务、不联网、不安装 capability、不真实执行服务。

### Skills 与学习

- Skill lifecycle MVP：request、approve、stage、validate、promote、retire、match、inject、usage tracking。
- Project Memory 到 Skill Draft 的蒸馏。
- 本地 Central Skill Vault 生命周期。
- Trace-to-Skill learning review 和候选技能 approve/reject。
- 外部技能发现仍是手动、默认禁用、审批门控。

### Web UI 与状态界面

- 零依赖静态状态板。
- 任务详情面板连接运行时产物。
- S11 方向的本地 ops console snapshot。
- CLI 仍是最可靠的一等控制面。

### 测试与完整性

- Artifact gate 和 task closure 集成测试。
- P1/P2/S7/S8/S9/S10/S11/S12 acceptance artifacts。
- Text integrity audit 用于发现多行文件压缩、markdown fence 损坏、private path 泄漏、raw 文件损坏。
- `doctor` 命令检查 Python、bash syntax、py_compile、config parsing、目录布局、UI 文件、artifact contract 和 API key readiness。

## 常用命令

```bash
./agentlab.sh --help
./agentlab.sh doctor
./agentlab.sh policy-status --project AgentLab
./agentlab.sh models
./agentlab.sh run-pipeline --help
./agentlab.sh project-next --project AgentLab
./agentlab.sh capability-list
./agentlab.sh eval-generalization --out acceptance_runs/s10_generalization_eval
./agentlab.sh ops-console-status --project AgentLab --out acceptance_runs/s11_dashboard
./agentlab.sh service-factory-plan --prompt "规划一个本地文件整理助手" --out /tmp/agentlab_service_demo
```

## 未来更新计划

### M0 Preflight / Baseline Lock

- 生成 current-state report：branch、commit、remote、CI、test、compileall、text integrity、tags、dirty files。
- 创建 `docs/M_SERIES_SCOPE.md`。
- 冻结范围：M1 是治理，M2 是操作控制，M3 是商业/资产/收入闭环。
- 跑 compileall、pytest、CLI help、run-pipeline help、text integrity audit。

### M1 Project Governance Kernel

目标：让 AgentLab 可靠管理长期项目，并协调本地 CLI 或 handoff 执行器。

计划工作：

- M1-1 External Project Registry + Capability Mapping。
- M1-2 Mission Compiler v2。
- M1-3 Project Workflow Templates v2。
- M1-4 Project Brain v1 consolidation。
- M1-5 Executor Connector Loop v1 consolidation。
- M1-6 Document / Code / Media Ingestion v1 contracts。
- M1-7 Phase Acceptance v1 consolidation。
- M1-8 Recovery / Replanning v2。
- M1-9 Context Compression v1。
- M1-10 Generalization Demo Suite。

M1 验收：

- 粗略项目 prompt 可以编译成 mission contract。
- 可以生成 project workflow。
- Project brain 可持久化。
- Task packet 可交给本地 CLI/handoff executor。
- Mock executor result 可摄入。
- Phase acceptance 可选择 accept、retry、redesign、split、rollback、ask user。
- Context compression 能防止长期项目记忆崩塌。
- Document/code/media ingestion contract 存在。
- 四个 offline generalization demo 通过。

### M2 Operator OS / Transparent Control Plane

目标：让 AgentLab 容易检查、配置、暂停、恢复、批准、拒绝和成本控制。

计划工作：

- Config Center。
- Cost System v2。
- Event Timeline / Observability。
- TUI。
- WebUI。
- AgentLab Assistant Modes。
- Skill / Capability / Executor Control Panel。
- Operator Acceptance Demo。

M2 验收：

- 配置透明且分层。
- 成本估算、追踪、告警、归因、review 可见。
- 项目事件进入 timeline。
- TUI 和 WebUI 可用，但不削弱 CLI 可靠性。
- Assistant modes 可以解释 roadmap、phase status、next action。
- Skills、capabilities、executors 可检查、可控制。
- Operator demo 通过。

### M3 Project-to-Revenue OS

目标：把项目生产连接到资产、交付、渠道、收入、合规、客户和 SOP 学习。

计划工作：

- Business Contract。
- Asset Registry + Lineage。
- Production Pipeline Templates。
- Market / Channel Intelligence。
- Analytics + Revenue Ledger。
- Compliance / Risk Brain。
- CRM / Client Delivery Loop。
- SOP / Skill Factory 2.0。
- End-to-end Project-to-Revenue demo projects。

M3 验收：

- Business contract 存在。
- Asset 与 lineage 可追踪。
- Production pipeline 存在。
- Market/channel intelligence 结构化，并受策略约束。
- Analytics 和 revenue ledger 存在。
- Compliance/risk brain 存在。
- CRM/client delivery loop 存在。
- SOP/skill factory 产出 candidates。
- 三个 offline P2R demo 通过。

### v1.0 Release Target

- M1、M2、M3 全部通过。
- full pytest 通过。
- compileall 通过。
- text integrity 通过。
- README 和 docs 清楚说明 AgentLab 是 local-first AI Production OS / Project-to-Revenue OS。
- 安装、quickstart、安全模型、架构、示例文档完整。
- 无 private path 泄漏。
- 默认不启用 unsafe external execution。
- 新用户可以复现 demo projects。

## 安全模型

AgentLab 默认保持保守：

- 不自动执行外部工具。
- 不自动安装技能。
- 不自动启动 MCP server。
- 不自动 web crawling。
- 不自动平台发布或上传。
- 不自动安装依赖。
- 默认不公开 bind 服务。
- 不在项目记忆、产物或 handoff 中记录 credentials。
- 没有证据和明确 review，不接受外部结果。

## 来源文档

- 主 README：[`../README.md`](../README.md)
- 主线状态：[`MAINLINE_BASELINE_STATUS.md`](MAINLINE_BASELINE_STATUS.md)
- 外部 agent handoff：[`EXTERNAL_AGENT_HANDOFF.md`](EXTERNAL_AGENT_HANDOFF.md)
- P2 acceptance/retry loop：[`P2_ACCEPTANCE_RETRY_LOOP.md`](P2_ACCEPTANCE_RETRY_LOOP.md)
- S7 orchestrator：[`S7_LONG_PROJECT_ORCHESTRATOR.md`](S7_LONG_PROJECT_ORCHESTRATOR.md)
- S8 executor connector：[`S8_EXECUTOR_CONNECTOR_LOOP.md`](S8_EXECUTOR_CONNECTOR_LOOP.md)
- S9 capability fabric：[`S9_CAPABILITY_FABRIC.md`](S9_CAPABILITY_FABRIC.md)
- S10 eval suite：[`S10_GENERALIZATION_EVAL_SUITE.md`](S10_GENERALIZATION_EVAL_SUITE.md)
- S11 ops console：[`S11_OPS_CONSOLE.md`](S11_OPS_CONSOLE.md)
- S12 productization：[`S12_PRODUCTIZATION.md`](S12_PRODUCTIZATION.md)
