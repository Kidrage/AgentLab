# AgentLab 整体逻辑图

更新日期：2026-07-18

这份文档是 AgentLab 当前定位、agent 职责、生产链和验收状态的中文总图。机器可读事实源是：

- `acceptance_runs/agentlab_capability_acceptance/current.yml`
- `acceptance_runs/agentlab_capability_acceptance/production_chain_audit.yml`
- `acceptance_runs/agentlab_capability_acceptance/agent_role_chain_audit.yml`
- `acceptance_runs/agentlab_capability_acceptance/live_unblock_plan.yml`
- `acceptance_runs/agentlab_capability_acceptance/internal_live_readiness.yml`
- `acceptance_runs/agentlab_capability_acceptance/external_acceptance_readiness.yml`（旧消费者兼容文件；canonical report type 仍是 `agentlab_internal_live_readiness`）
- `acceptance_runs/agentlab_capability_acceptance/role_session_acceptance_handoff.md`
- `acceptance_runs/agentlab_capability_acceptance/goal_completion_audit.yml`
- `docs/AGENTLAB_CAPABILITY_ACCEPTANCE_MATRIX.md`

## 1. 当前定位

AgentLab 仍然首先是一个强代码系统。它的核心优势是长期软件项目治理：

- 任务合约；
- 仓库上下文；
- scoped implementation；
- 验证证据；
- review/audit；
- project memory；
- archive/promotion；
- cost/resource ledger；
- recovery/replanning。

但 AgentLab 不是“所有任务都套代码壳”的系统。代码壳只是 `code_factory` 生产包。非代码生成任务应该复用 AgentLab 的状态治理和生命周期，而不是继承 repo scout、interface map、implementation report、patch diff、source-write policy 这些代码专属假设。

当前主链路是：

```text
user_request
-> mission_contract
-> route_decision
-> production_pack
-> lifecycle_nodes
-> agent required inputs/outputs
-> validation_gates
-> artifact_contract
-> memory/promotion policy
```

关键边界：

```text
Model Provider != Executor
Agent Harness != Project Owner
AgentLab = Project OS / Truth Source / Governance Layer
Host/Codex Sandbox Approval != AgentLab Role / Worker / Workflow Node
```

AgentLab 可以把具体执行委托给 Codex、Claude Code、OpenClaw、Hermes、Agy、本地 CLI 或直接模型 API，但项目真相必须留在 AgentLab：workflow plan、project brain、evidence ledger、cost ledger、approval gate、final delivery state。

Codex 是 AgentLab 外部的建设、修复与审计 worker，不是 AgentLab FrontDesk。需要接单与路由时，canonical FrontDesk 是 Hermes CLI + DeepSeek V4 Pro；验证已声明的 pipeline 时可以直接进入 `direct_closed_loop`，完全不创建 FrontDesk session。两种路径都不能绕过 role binding、run-local receipt、validation 与 promotion gate。

Full CLI 模式下，AgentLab 治理的对象首先是 CLI 壳能力与交付契约，而不是重新搭建一套内部工作壳。`config/cli_workflow_shells.yml` 现在记录 shell governance policy：每个 CLI 壳接入前要审 common capabilities、unique capabilities、efficiency_gains、delivery_contract、risk_controls，并明确 shell state 不等于 project memory。当前 full_cli 壳集合是 `agy,claude_code,codex,grok,hermes,qwen`；`cli_workflow_shell_absorption` 机器验收显示 `families=10`、`full_cli_shells=agy,claude_code,codex,grok,hermes,qwen`、`media_kernel=hermes_workflow_shell`。API 模式的规则相反：direct API 模型不自带成熟本地工作壳，因此 `full_api` 由 AgentLab 自己提供 task packet execution、tool routing、memory discipline、validation 和 receipt collection。

更完整的 CLI 壳目标是：AgentLab 不只是把 `hermes`、`claude`、`grok` 当 provider 命令调用，而是把它们当本地 workflow runtime 治理。一个 Hermes 壳如果已有 kanban、sessions、tools、MCP、skills、gateway、dashboard 等命令面，AgentLab 应先登记这些 native command surfaces，再决定哪些可用于 role-session 内部协作。一个 Claude Code 壳如果提供 `agents`、`--agent/--agents`、`--background`、`project`、`ultrareview`、worktree、MCP/plugin/settings 等能力，AgentLab 应把这些能力纳入 Coder/Reviewer 等角色的执行契约。

当前 `cli_native_command_surface_governance` 只验收真实运行边界：Hermes 的 kanban 和 Claude 的 agents/background 等命令面已登记，可在一个受限 AgentLab role-session 内作为壳原生协作能力使用。AgentLab 不再为这些壳复制一套 subagent、board 或 session 框架。

不同 AgentLab 角色之间仍由 lifecycle gate 隔开。例如 Reviewer 的回执和产物必须先落盘并通过本地检查，Scribe 才能启动；即使两个角色指向同一个 CLI，也不能为了少一次壳命令而绕过该门。当前没有 dependency-free 的 same-stage multi-role 组，因此不启用跨角色 coalescing。

旧 `cli_shell_coalescing_*` 实验按整张 full CLI matrix 分组，未进入 `run-pipeline`，也未处理上述角色依赖。它的五个运行模块、两个专用测试和当前验收链已经退出主线，历史证据移到 `docs/archive/acceptance_legacy_20260718/cli_shell_coalescing/`。
当前 full_cli 核心角色拓扑是：

| Role | 当前执行面 | 合同与边界 |
|---|---|---|
| Supervisor | Hermes + GPT-5.6 Sol (`xhigh`) | `hermes_supervisor`；容量/认证类失败只走预批准 fallback |
| Observer | Agy + Gemini 3.5 Flash High | `agy_observer`；独立读取文本、图片、视频、音频、PDF 证据 |
| Observer 容量 fallback | 同一 Agy 壳 + Claude Sonnet 4.6 | 仅 Gemini `quota_exhausted`、`rate_limited` 或 `model_unavailable` 的受治理结果允许；只读文本、图片、PDF |
| Writer | Claude Code + DeepSeek V4 Pro | `claude_writer`；运行前精确绑定模型、effort、预算、plan mode、JSON 与空 tools，产出正文与 narrative ledger 候选 |
| Researcher | Hermes + xAI OAuth + Grok 4.3 | `grok_research`；产出带来源的研究证据 |
| ArtifactProducer | 按 ArtifactTask 类型动态分派：文本/表格/演示走 Qwen CLI，图片/视频走 Hermes + xAI OAuth + Grok 4.3 | `artifact_task_policy.yml` 是唯一权威；音频和跨 provider 混合产物当前不支持；所有返回均为 run-local candidate，不得自验收 |

`claude_writer_ultracode` 是独立的开发性编辑路线，不是默认 Writer 的
“更强档”。只有 sealed Writer packet 同时显式提供
`ultracode_opt_in: true`、`writer_mode: developmental_ultracode` 和 allowlist
内的 `work_type` 才可执行；运行时写 `ultracode_activation_receipt.yml`，并
始终禁止 `final_prose_draft`。

任务级操作入口为：

```bash
./agentlab.sh run-agent Writer --project <project> --task-id <task> \
  --writer-ultracode --writer-work-type revision_plan --execute
```

缺少任一 Ultracode 参数时仍走普通纯 Writer 合同；专用
`WriterUltracode` 容量路线不会自动降级成普通正文起草。

ArtifactProducer 不能以“未声明类型的通用角色”直接执行。用户侧
`assign-role` 必须提供 `--artifact-type`，再由
`artifact_task_policy.yml` 推导 required capabilities、provider、invocation
contract 和 capacity route；目标 provider 不可用时必须阻断。CSV 中原有
profile 列只表示 full-cli 的基础媒体 profile，新增 `artifact_dispatch` 列才是
按类型生效的执行面。

Agy 的 Gemini 与 Claude Observer 是两个独立订阅池。五小时与周窗口的时长来自用户声明，但 limit、remaining、reset_at 都未知；OpenAI Codex 与 xAI 订阅池也同样未知。认证通过或 smoke 成功只证明 reachability，不证明额度充足。

安全容量探测只允许 `agy models` 或 provider-scoped `hermes auth status <provider>`。不得运行会扩大秘密暴露面的 broad Hermes status，也不得猜测重置点。

媒体执行复用同一容量门：pending Grok 合同只能运行精确的
`hermes auth status xai-oauth`，并且 capacity route、
`hermes_grok_oauth` backend、generation receipt 三者必须一致；运行前写
`media_capacity_route_receipt.yml`。手写 backend、音频以及同时要求图片和
视频但没有 composite adapter 的请求都必须阻断，不能缩减成单一媒体输出。

## 2. Agent 职责

| Agent | 职责 | 不应该做 |
|---|---|---|
| FrontDesk/Hermes | 可选用户入口、任务提交、状态观察、报告已验证证据 | 扮演 Writer/ArtifactProducer/Supervisor 直接完成生产内容 |
| Supervisor | mission contract、route、scope、budget、production-pack selection、approval gates | 静默改源码或绕过审批 |
| Observer | 独立多模态观察、实际候选产物检查、证据记录 | 生成自己要验收的产物或臆测未读取的质量 |
| RepoScout | 代码任务的仓库结构和上下文读取 | 改文件 |
| InterfaceMapper | 代码接口、契约、跨层边界分析 | 实现 patch |
| Researcher | 通过 `grok_research` 调查外部资源并产出有来源的 domain brief | 无证据地变成事实源 |
| PromptEngineer | 准备有边界的执行 prompt 与上下文 handoff | 代替生产角色执行或 promotion |
| Coder | 代码任务的实现、候选 patch、代码产物 | 默认产出小说、视频、文章等非代码任务 |
| ArtifactProducer | 按 ArtifactTask 能力路由生产非代码候选资产；图像/视频走 `grok_media`，文本/表格/演示走 Qwen CLI，音频和跨 provider 混合产物当前阻断 | 替代 Coder、自己验收、直接 promotion |
| Writer | 通过 Claude Code + DeepSeek 生产长篇叙事候选正文和 ledger | 直接 promotion 到 production memory |
| Reviewer | 小说连续性、人物状态、时间线、POV、风格漂移审计 | 默认重写正文 |
| Scribe | narrative ledger、state-transition proposal | 把未批准事实当生产事实 |
| TesterAuditor | 验证命令、审计风险、证据记录 | 无证据宣布通过 |
| Verifier | 输出契约和 handoff 完整性检查 | 改 implementation |
| Archivist | acceptance 后归档、promotion、project memory 更新 | 对 pack 排除 archive 的任务强行 promotion |

## 3. 生产包规则

当前规则：

```text
code task -> code_factory
known non-code task -> configured production_pack
unknown complex non-code task -> production-pack synthesis candidate
simple one-shot non-code task -> generic/artifact light path
```

这意味着以后不需要每遇到一个非代码任务就手工设计全新流水线。AgentLab 应先判断：

- 已知领域：复用已有 production pack；
- 相邻领域：复用旧 pack 并小幅 specialization；
- 未知复杂领域：进入 production-pack synthesis，由 Researcher 先做 domain brief，再由 ArtifactProducer/Verifier 产出候选 pack；
- 简单一次性 artifact：走 generic/artifact light path。

production-pack synthesis 的候选输出是：

```text
production_pack_proposal.yml
domain_memory_contract.yml
lifecycle_profile.yml
```

候选 pack 不能自动安装，必须经过 `pack-candidate-validate` 和显式批准。

当前离线 smoke 已证明候选包三件套可以生成并通过 validator：

```bash
./agentlab.sh production-pack-synthesis-smoke --out acceptance_runs/agentlab_capability_acceptance/production_pack_synthesis_smoke.yml
```

该 smoke 在 `projects/AgentLab/runs/task_production_pack_synthesis_smoke_20260707/` 写出 `domain_research_brief.md`、`production_pack_proposal.yml`、`domain_memory_contract.yml`、`lifecycle_profile.yml`；proposal 验证为 `synth_multimodal_asset_generation`，但不会自动 promotion。

这里必须区分 deterministic scaffold 和真实角色返回。`production_pack_synthesis_smoke.yml` 只证明调度壳、候选结构和 validator；它不证明 Supervisor/Researcher/ArtifactProducer/Verifier 已真实完成一次新领域生产包。独立命令 `production-pack-role-session-audit` 审计后者。当前历史 run 保留了真实 Researcher 报告及通过的 research contract，但 Supervisor/Researcher 调用发生在完整 outbound manifest 闸门落地之前，且该 run 缺少持久化 mission contract；ArtifactProducer 的三项同轮返回和 Verifier receipt 也尚未返回，因此 capability 保持 `candidate`。严格验收必须让四名 provider-bound 角色都留下 scoped approval、exact manifest 和 returned artifact；不得静默 fallback 或自动 promotion。

`prepare --write-plan` 与 pipeline 自己的 `PREPARE_PLAN` 现在都会把同一份 rule-based mission compiler 输出写成 `mission_contract.yml`、`required_capabilities.yml`、`artifact_contracts.yml`、`acceptance_gates.yml` 和 `risk_flags.yml`。Mission 只在内存中参与 plan 构建、不落盘的旧行为已移除；`workflow_plan.yml` 不重复内嵌整份 mission，避免上下文膨胀。

正式 fresh-run handoff 由 `production-pack-role-session-request` 生成。它不调用 provider、不创建 target run，只检查 source hash/secret pattern、route/pack、四角色 binding 和 full-cli surface，并生成必须显式设置 `AGENTLAB_PRODUCTION_PACK_CONTEXT_APPROVED=1` 才能执行的脚本。脚本固定新 task id，先 init/prepare，再执行 pipeline，最后用 `production-pack-role-session-audit --require-pass` 回收；未批准时 exit 2，target run 不产生。

production-pack synthesis 可以向外寻求资源，但外部资源边界必须保持清楚：`approved_external_research` 只能在批准后作为候选证据来源，必须写入 run-local `resource_evidence_ledger` / source notes；`external_research_may_not_write_project_memory: true`，外部发现不能直接成为 fact snapshot、project memory 或生产事实。任何 evidence -> memory 的转换都必须经过 review/promotion gate，因此外部资料只能辅助候选 pack 设计，不能绕过 AgentLab 的状态治理。

## 4. 当前代表生产链

来自 `production_chain_audit.yml` 的当前通过结果：

| 场景 | Route | Production pack | Agent chain | 关键状态记忆 |
|---|---|---|---|---|
| 长期代码/UI app | `interface_sensitive_task` | `code_factory` | Supervisor -> RepoScout -> InterfaceMapper -> Coder -> TesterAuditor -> Verifier -> Archivist | repo context、implementation report、validation/audit/archive |
| Crown 小说轻章 | `narrative_light_chapter` | `narrative_longform` | Supervisor -> Writer | chapter packet、fiction draft、continuity ledger、state transition proposal、delivery receipt |
| 普通文章 | `article_light_draft` | `article_light` | Supervisor -> ArtifactProducer | article draft、structure check |
| Crown 阶段重审计 | `narrative_heavy_audit` | `narrative_longform` | Supervisor -> Reviewer -> Scribe -> Verifier | fiction review、continuity failure report、state transition proposal、rewrite proposal |
| Crown 漫画/短视频/海报图册 | `media_generation_task` | `media_series_production` | 生成：Supervisor -> ArtifactProducer -> TesterAuditor；promotion：Observer + Reviewer + Verifier -> 人/Supervisor | episode plan、shot list、character visual bible、asset registry、prompt pack、generation ledger、media QC |
| 未知复杂非代码领域 | `media_generation_task` + synthesis | `pack_synthesis_candidate` | Supervisor -> Researcher -> ArtifactProducer -> Verifier | domain research brief、pack proposal、memory contract、lifecycle profile |

这六条链路通过：

`narrative_heavy_audit` 的 Reviewer/Scribe/Verifier 使用专用 `qwen_narrative_audit` role-session contract。AgentLab 先把最小完整上下文封装进 packet，再通过 stdin 一次性交给 Qwen；该会话禁止普通工具调用和工作区扫描，要求 `AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1`，且只允许通过受约束的 structured output 返回 candidate-only 审计文件。Reviewer 才读取完整章节上下文，Scribe/Verifier 只消费上游结构化审计产物，避免重复注入正文。

```bash
./agentlab.sh production-chain-audit --out acceptance_runs/agentlab_capability_acceptance/production_chain_audit.yml
```

审计曾抓出一个真实漏点：`narrative_light_chapter` 的 Supervisor 仍继承 `agent_docs/01_REPO_MAP.md`。已修复为 narrative light/batch/heavy 都使用非代码 Supervisor contract，代码路径不受影响。

角色/worker/生产链一致性通过：

```bash
./agentlab.sh agent-role-chain-audit --out acceptance_runs/agentlab_capability_acceptance/agent_role_chain_audit.yml
```

这次审计又抓出一个真实配置漂移：`narrative_heavy_audit` 使用 `Reviewer` 和 `Scribe`，但它们没有正式 role binding，且全局 `agent_order` 缺少 Writer/Reviewer/Scribe。已补齐 Reviewer/Scribe 绑定、worker allow/forbid 覆盖和全局 agent 顺序。

媒体连续剧 scaffold 另有专门审计：

```bash
./agentlab.sh media-series-scaffold-audit --out acceptance_runs/agentlab_capability_acceptance/media_series_scaffold_audit.yml
```

它不把历史 run 目录里的旧占位文件当作活动生产线证据，而是检查 `media_generation_task`、`media_series_production`、媒体 YAML 交付件、candidate-only 状态、promotion 阻断和无 production media 写入。报告里的 local Grok preflight 是历史字段；当前执行合同是 Hermes/xAI 的 `grok_media`。

## 5. 状态治理如何复用

AgentLab 复用的是这几层，而不是复用代码壳：

| 层 | 代码任务 | 小说任务 | 媒体任务 | 未知非代码 |
|---|---|---|---|---|
| mission contract | 需求、仓库目标、风险 | 章节目标、连续性范围 | 媒体意图、风格、生成目标 | 领域目标和未知能力 |
| workflow plan | code route + agents | Writer/Reviewer/Scribe route | ArtifactProducer/TesterAuditor route | Researcher -> pack synthesis route |
| lifecycle | repo/context/implementation/validation/archive | chapter packet/draft/ledger/audit | prompt/asset/generation/QC | research/proposal/validation |
| memory | repo map、interface registry、implementation report | fact snapshot、artifact index、continuity ledger、state transitions | visual bible、asset registry、shot ledger、generation ledger | domain memory contract |
| validation | tests/build/static checks | narrative delivery receipt、continuity audit | backend preflight、media QC、asset provenance | pack validator |
| promotion | archive after acceptance | no production manuscript write before acceptance | no final media promotion before QC/human acceptance | no pack install before approval |

## 6. 当前验收结论

`goal_acceptance_scope.yml` 保存的是 2026-07-12 scoped goal 的历史完成口径：代码项目和
Crown 长篇走完整验收，production-pack synthesis 只要求 deterministic scaffold，媒体只
要求 generation readiness。该历史 scope 不等于当前生产 promotion 标准。

当前视觉资产必须走独立验收：`grok_media` 先返回 run-local candidate，Observer 再读取
实际图片/视频/音频并记录证据。Reviewer 必须用与 Producer/Observer 不同的角色会话完成
审美、连续性、技术、事实安全四维判断；Verifier 则只验证资产 hash、证据链、Reviewer
独立性与 promotion 边界，不假装直接感知画面，也不重复审美结论。最后由人或 Supervisor
显式 promotion。任何 `pending`、`unknown` 或缺失证据都阻断 promotion。

机器总报告生成命令：

```bash
./agentlab.sh capability-acceptance --out acceptance_runs/agentlab_capability_acceptance/current.yml
```

2026-07-18 当前快照的结果：

```text
overall_status: candidate
pass: 20
candidate: 8
```

当前没有 fail。8 个 candidate 都是尚未返回的阶段性 role-session/live 验收；
它们不改变路由、模型登记和本地治理链的通过状态。当前 Writer request 已按
Claude Code + DeepSeek V4 Pro 生成，只等待真实 role-session 返回。

已经成立的结论：

- 代码工厂路径仍在，`code_factory` 没被非代码改动削弱。
- 非代码任务不会默认继承代码壳。
- production-pack synthesis 的 deterministic scaffold、validator 和候选包三件套 smoke 已通过；带 persisted mission 与 exact outbound manifest 的真实 Supervisor -> Researcher -> ArtifactProducer -> Verifier 返回闭环仍是 candidate，二者不再混报。
- 核心大脑层 package import 稳定性已纳入机器验收：`workflow_plan`、`task_router`、`model_resolver`、`skill_injector`、`skill_usage`、`state_store` 等可作为 `agent_runtime.*` 包模块导入，package-mode workflow plan 能构建 `code_factory` 且不再让 skill plan / artifact intent 静默降级。
- 代表生产链可机器审计。
- CLI workflow shell governance 已并入主线：`config/cli_workflow_shells.yml`、`config/agent_role_bindings.yml`、`config/worker_invocation_contracts.yml`、`config/media_generation_backends.yml` 和 `config/agent_model_profiles.yml` 共同证明 full_cli 治理 shell capability/delivery，而不是重建 shell scaffold；Hermes/Claude Code/Agy/Codex/Qwen/Grok 的共通能力、独特能力、效率收益、交付契约和风险控制都有注册。
- CLI 壳调用规则已剪枝：壳原生 subagent/kanban 只服务于一个 AgentLab role-session；跨 lifecycle gate 的角色保持独立。未被生产管线调用的 synthetic coalescing runner、collector、request/status 链已归档，不再进入 current acceptance 或默认 CLI 命令面。
- Crown 的本地长篇治理、mock 链路、1500 章治理模拟成立；`crown_heavy_audit_scale` 已明确通过 1500 章 governance-scale audit，但该审计只证明状态治理规模能力，不证明 1500 章正文质量。一章 live candidate 已通过本地 candidate audit，确认正文 565 行、候选状态变更、delivery receipt、reset baseline 和未写入 production manuscript。
- Crown 媒体连续剧 scaffold 已通过本地 media-series audit：活动路线是 `media_generation_task`，生产包是 `media_series_production`，episode/shot/visual bible/asset/prompt/generation/QC/receipt 都是 candidate-only，且没有写入 production media。
- Web UI/app 已完成 production promotion：候选 `artifacts/web_ui/` 通过 DOM/fetch、headless browser、operator interaction、run-local API write、截图像素和桌面/移动响应式视觉证据后，由 artifact steward 发布到 `projects/AgentLab/artifacts/web_ui/`，并写入 `archive_receipt.yml` 与 `project_artifact_index.yml`。
- DeepSeek text/code provider reachability 已通过无私有上下文 live smoke：`deepseek-v4-flash` 在禁用 thinking 的 ProviderSmoke 合同下返回 `AGENTLAB_PROVIDER_SMOKE_OK`，并记录 `finish_reason: stop`、输入/输出/总 token。此前空内容是短 smoke 未禁用 thinking 导致 `finish_reason: length`，不是当前 provider reachability 失败。
- 当前 Grok 角色通过 Hermes executable + xAI OAuth + Grok 4.3 执行。Researcher 使用 `grok_research`；只有图片/视频 ArtifactProducer 使用 `grok_media`，两者共享 xAI subscription pool，但不能互换交付合同。文本/表格/演示 ArtifactProducer 走 Qwen CLI；跨 provider 混合任务在 composite adapter 就绪前阻断。旧 `grok-build-0.1`/generic Grok 命令只属历史证据，不再是当前路由。
- `grok_media` 的 OAuth reachability、preflight、asset-return 与 candidate-only 边界不等于成品验收。返回资产必须经过 Observer、相互独立的 Reviewer/Verifier 与人或 Supervisor promotion；真实质量、连续性和成本在完成该链前都保持未验收。
- Frontdesk 边界已机器审计：Hermes CLI + DeepSeek V4 Pro 是默认 FrontDesk；Codex 仅是外部建设/审计 worker。Hermes 的 FrontDesk profile 与 Supervisor 等 role-session profile 严格分离。既定 pipeline 可走 direct closed loop，不要求 FrontDesk；Writer/ArtifactProducer 的 live 调用仍必须带对应 role-session evidence。Canonical flags 是 `hermes_frontdesk=True`、`direct_closed_loop=True`、`codex_external_worker=True`。
- Hermes FrontDesk 的真实 provider/model/auth 路径已做隔离非私有 smoke：从 `/private/tmp` 使用显式 `deepseek / deepseek-v4-pro` 一次性调用，Hermes 无 fallback provider，精确返回 `AGENTLAB_HERMES_DEEPSEEK_V4_PRO_FRONTDESK_OK`。证据在 `hermes_frontdesk_deepseek_v4_pro_smoke.yml`；该结果只证明 FrontDesk reachability，不替代 Crown Writer 私有 role-session 验收。
- 历史 `internal_live_readiness.yml` 的 `ready_for_internal_live_smoke` 证明当时 route/safety 与无私有上下文 reachability。它不证明当前容量：Agy、OpenAI Codex、xAI 的 limit/remaining/reset 仍未知，也不证明当前 Claude Code + DeepSeek Writer 的 live 质量。
- 术语边界：`private live smoke` 只是旧简称；canonical kind 是 `private_role_session_acceptance_smoke`，准确含义是“带项目上下文的角色会话验收跑”。它不是新的默认生产链路，只用于最终验收 Writer/ArtifactProducer 真实 provider 路径是否能返回候选产物；日常小说/媒体生产仍应走对应 production pack、记忆闭环和候选/晋升 gate。
- 历史 trusted-live runner request 带硬 gate：无私有上下文 health 需要 `AGENTLAB_TRUSTED_LIVE_RUNNER=1`，私有 role-session 还需要 `AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1`。旧脚本先跑 Agy/Grok reachability，再校验 returned-artifact QC；这些控制面证据保留，但旧 Agy Writer 选择不再定义当前 Writer。
- 历史 Agy Writer run 使用过 `agy_writer` sealed packet。当前 Writer 已改为 Claude Code + DeepSeek V4 Pro / `claude_writer`，但继续沿用最小 sealed payload、隔离 cwd、越界拒绝与 `outbound_context_manifest_writer.yml` 边界。旧 run 只证明 artifact/manifest 合同，不证明当前 executor。
- Production-pack synthesis 的 Supervisor、Researcher、ArtifactProducer、Verifier 都采用 packet-only 边界：CLI task packet 不再携带 `agentlab_root` / `project_root` / `run_dir` 等工作区路径，只携带 AgentLab 已组装的最小 messages，并在临时隔离 cwd 中执行。每个角色必须先写自己的 `outbound_context_manifest_<role>.yml`，使用独立批准域 `AGENTLAB_PRODUCTION_PACK_CONTEXT_APPROVED=1`；秘密模式命中、source 越界/缺失、payload 非精确或未批准时，都在 subprocess/API 调用之前阻断。full-cli 主 worker 不可用时直接 block；不得静默切换 direct API。显式 `full_api` 路线仍使用相同 manifest gate，但需要单独规划和批准 provider surface。
- Writer 返回值不再被当作整段 `fiction_draft.md`，narrative-eval 和普通 pipeline 共用 `writer_output_materializer.py`：只有同一 run 的四个完整 AGENTLAB_EDIT 候选块全部存在时才事务性写入，且 harness 不再用固定模板覆盖 Writer 的 continuity/state/receipt。`writer_output_contract.yml` 明确记录 `harness_generated_story_state: false`。
- Media live adapter 在调用 Grok/Hermes 前写 `outbound_context_manifest_media.yml`，hash 的是实际 1200 字符上限 media prompt；默认 subprocess cwd 使用临时隔离目录。secret 命中或 trusted acceptance 缺 approval 时在 command runner 之前阻断。
- 历史 trusted-live runner operator handoff 保留 Agy Writer/Grok media 两个可选 item；当时 scoped goal 只使用 Writer selected collect，媒体 item 留在 `deferred_internal_live_smokes`。这些字段用于复核旧 run，不定义当前角色绑定。
- 人读 handoff 的 canonical 路径是 `role_session_acceptance_handoff.md`；旧 `private_live_smoke_approval_handoff.md` 只保留为 legacy path，避免再把 legacy shorthand 当成正式生产链名称。
- 历史 trusted-live runner collector 已纳入能力矩阵：它保留 Writer/media 两项当时状态，goal/objective audit 读取 Writer-specific selected collect。旧 blocker 字段只解释冻结 scope，不能外推到当前 Claude Writer 或视觉 gate。
- 兼容性与可观测字段仍完整保留：每项继续暴露 `required_files_exist`、`returned_candidate_artifacts_accepted` 和 `acceptance_blocker`。Collector 继续暴露 `acceptance_blockers`、`acceptance_blocker_reasons`、`required_files_missing_count`、`returned_candidate_artifacts_accepted_count`、`acceptance_report_hygiene_status`，并刷新 `live_unblock_plan.yml`。
- 当前 collector issue 是 `collector refreshed reports, but non-private session health still needs attention`；它指向当前 Claude Writer 会话探针，不会把 route/model 登记误报为失败。
- 历史 handoff 继续保留 canonical text、hygiene、selected readiness 与两个 approval gate 字段。它们证明当时控制面完整，不允许把 `selected_ready` 解读成当前容量可用。
- 历史 acceptance-report hygiene 是 `pass`：它证明冻结 scope 的 canonical reports、文本 handoff、审批 env 与 snapshot 分类一致。它只治理该历史报告集，不是当前 role topology 或容量事实源；旧 Agy/Grok smoke 继续保留为历史快照。

当前报告保留这些精确的机器兼容标记：
`full_run_requires_trusted_status_pass`、`approval_gate_before_private_context`、
`selected_item_readiness`、
`selected_ready=run_crown_internal_media_smoke`、
`selected_blocked=run_crown_internal_writer_eval`。当前 blocker reasons 是
`missing_required_files`，具体 reasons 是
`claude_writer_session_health_blocked_before_private_writer_smoke` 与
`missing_candidate_artifacts`，计数是
`required_files_missing_count: 10` 与
`returned_candidate_artifacts_accepted_count: 0`。Hygiene 字段是
`canonical_text_artifact_count: 2`、`canonical_text_issues`、
`hygiene_private_selected_command_hits`、
`stale_private_selected_command_hit_count: 0`；原始 policy 文本是
`selected private role-session commands must include AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1`。
该 issue 是当前非私有会话 health gate；runner 在 returned status 未通过时会非零退出。
`external_acceptance_readiness.yml` 只是旧消费者兼容文件；
`acceptance_report_hygiene.yml` 把 `*_now`、`*_check` 与 `*_current` 归为
非权威快照。

当前架构与历史验收的边界：

- 历史 `crown_formal_live_narrative_eval` 的 Agy/Gemini 单章返回后来通过当时 scoped QC。它证明 governed narrative artifact 合同，不证明当前 Claude Code + DeepSeek V4 Pro Writer 的 live surface 或更广泛文学质量；若当前 executor 也要求 live acceptance，必须单独取证。

旧 scope 将 `production_pack_synthesis_role_session` 四角色 provider live acceptance 与
真实 generated-assets/QC 标为 deferred。当前视觉合同不把质量无限期推给未来流程：任何
真实资产在 Observer + Reviewer + Verifier 证据与显式 promotion 前都保持 blocked。

对应解阻计划：

```bash
./agentlab.sh live-unblock-plan --out acceptance_runs/agentlab_capability_acceptance/live_unblock_plan.yml
```

Frontdesk 安全 handoff：

```bash
./agentlab.sh frontdesk-live-handoff --agent hermes --out acceptance_runs/agentlab_capability_acceptance/frontdesk_live_handoff.yml
```

该 handoff 的含义是：Hermes/DeepSeek V4 Pro 可以作为可选 FrontDesk 提交 AgentLab 命令并观察 artifact；既定闭环也可以不经过 FrontDesk。live 正文生成归 Writer role-session，live 媒体生成归 ArtifactProducer role-session。

历史 Trusted runner 可执行包：

```bash
./agentlab.sh trusted-live-runner-request --out acceptance_runs/agentlab_capability_acceptance/trusted_live_runner_request.yml --request-id <id>
```

该 `.sh` 保留旧 Agy Writer/Grok media 请求的 `--preflight-only`、session-health 与私有上下文批准门。它只用于复核原始 run；新执行必须重新 materialize 当前 Claude Writer、Agy Observer、`grok_research` / `grok_media` 绑定，不能直接复用旧 worker map。

内部 live-smoke readiness：

```bash
./agentlab.sh internal-live-readiness --out acceptance_runs/agentlab_capability_acceptance/internal_live_readiness.yml
```

该报告当前是 `route_ready_session_blocked`；路由与安全合同已就绪，但当前 Claude Writer 会话探针尚未返回。这是可恢复的运行时会话状态，不是 role topology、模型登记或本地治理链失败。`external_acceptance_readiness.yml` 仍只是旧消费者兼容文件。

历史拒绝证据：

```text
acceptance_runs/agentlab_capability_acceptance/external_policy_rejection_writer_20260707.yml
```

历史 runner 中保留的 live-smoke item：

- `run_crown_internal_writer_eval`：当时用 Agy Writer 跑 formal `narrative-eval live`，不能当作当前 Claude Writer 绑定；
- `run_crown_internal_media_smoke`：用 `grok_media` 跑 `media-backend-execute --live`，产物仍只能是 run-local candidate。

目标级闭合审计：

```bash
./agentlab.sh goal-completion-audit --out acceptance_runs/agentlab_capability_acceptance/goal_completion_audit.yml
```

当前 scope 逐条验收审计：

```bash
./agentlab.sh objective-requirement-audit --out acceptance_runs/agentlab_capability_acceptance/objective_requirement_audit.yml
```

该 2026-07-12 scoped audit 保留 11 条 requirement，当时结果为 11 pass / `complete`。其中 Crown Writer pass 来自历史 Agy/Gemini run；媒体 live artifact 和 production-pack 四角色 provider 验收按旧 scope deferred。它不自动验收当前 Claude+DeepSeek Writer 或视觉 promotion 链。

该历史 scoped goal 的状态仍是 `complete`，其证据和口径不改写。当前架构的独立事实是：Supervisor、Observer、Writer、`grok_research` 与 `grok_media` 按新绑定执行；未观察到的容量保持 unknown；视觉候选在独立验收与显式 promotion 前不得进入 production。

历史上的 Codex shell 私有上下文拒绝只说明外部 worker 入口选错，不能作为 AgentLab 内部 Writer、route、provider 或 role binding 失败证据。Canonical 验收应由 Hermes FrontDesk 提交，或直接通过 AgentLab role-session/pipeline 闭环执行；Codex 只读取返回 artifact 和审计报告。

该审计会检查源报告和每个目标项引用的证据路径是否真实存在；如果证据缺失，对应目标项不能继续保持 `pass`。

## 7. 目前应该如何继续

如果要继续扩大 live 证据，顺序应为：

1. 复用已通过的一章 formal `narrative-eval live` 作为基线，不要把 1500 章治理模拟误写成 1500 章正文质量证明。
2. 后续章节走当前 Claude Code + DeepSeek Writer light path；历史 Agy 结果只能作结构基线。
3. Writer 返回物仍只能进入 run-local candidate artifacts，不能自动 promotion。
4. 媒体生成使用 `grok_media`；研究使用 `grok_research`，不得用 generic Grok 合同混跑。
5. 视觉候选立即进入 Observer -> 独立 Reviewer + Verifier -> 人或 Supervisor promotion gate。
6. 任何未观测容量与未完成视觉证据保持 `unknown` / `pending`，不能用 reachability 代替。

当前最诚实状态就是：

```text
本地治理和生产链：通过
历史 live 证据：Agy/Gemini Crown 单章按旧 scoped contract 通过
当前 Writer：Claude Code + DeepSeek V4 Pro；当前 executor 的 live 质量需独立取证
当前视觉资产：candidate-only；独立观察、审美验证、显式 promotion 前未验收
当前容量：limit / remaining / reset_at 未观测时保持 unknown
```

## 8. 测试剪枝

验收闭环后，重复最严重的四个历史测试文件已收敛：

- `test_goal_completion_audit.py` 与 `test_objective_requirement_audit.py` 合并为
  `test_scoped_acceptance_audits.py`。
- `test_live_unblock_plan.py` 与 `test_trusted_live_runner_operator_handoff.py`
  合并为 `test_trusted_live_runner_control_plane.py`。

这组测试从 1651 行降到 396 行，减少 1255 行。原来的 13 个顶层测试改为
7 个参数化测试函数，pytest 实际收集 11 个场景。保留的覆盖包括：当前 complete
状态、Writer pending 回归、CLI 写出、审批环境变量、sealed/private context 边界、
selected session-health gate、Writer pass/media deferred，以及缺失返回状态的非空化。
`trusted_live_runner_request` 的 secret scan、路径隔离和审批门禁测试没有合并删除。
