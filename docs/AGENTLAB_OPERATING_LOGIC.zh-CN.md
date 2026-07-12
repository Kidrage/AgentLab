# AgentLab 整体逻辑图

更新日期：2026-07-12

这份文档是 AgentLab 当前定位、agent 职责、生产链和验收状态的中文总图。机器可读事实源是：

- `acceptance_runs/agentlab_capability_acceptance/current.yml`
- `acceptance_runs/agentlab_capability_acceptance/production_chain_audit.yml`
- `acceptance_runs/agentlab_capability_acceptance/agent_role_chain_audit.yml`
- `acceptance_runs/agentlab_capability_acceptance/live_unblock_plan.yml`
- `acceptance_runs/agentlab_capability_acceptance/internal_live_readiness.yml`
- `acceptance_runs/agentlab_capability_acceptance/external_acceptance_readiness.yml`（旧消费者兼容文件；canonical report type 仍是 `agentlab_internal_live_readiness`）
- `acceptance_runs/agentlab_capability_acceptance/cli_shell_coalescing_runner_request.yml`
- `acceptance_runs/agentlab_capability_acceptance/cli_shell_coalescing_status.yml`
- `acceptance_runs/agentlab_capability_acceptance/cli_shell_coalescing_collect.yml`
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

当前 `cli_native_command_surface_governance` 已通过验收：`cli_shell_coalescing_plan.yml` 按 backend 分组 full_cli/performance roles，`claude_code` 的 Coder+Archivist 走 native inline agents，`hermes` 的 Supervisor+PromptEngineer 走 kanban/board-mediated coordination，并要求每个 delegated role 返回独立 receipt 与 validation evidence。该控制面 smoke 使用内嵌 synthetic fixture，`read_scope=[]`，不加载项目文件。Claude 在隔离临时目录启动，只开放 `Agent` 工具、safe mode 且不持久化会话；Hermes 每次使用唯一 attempt id 和 `scratch` workspace。

这里必须区分成本语义：Hermes kanban 合并的是 AgentLab/frontdesk 的调度入口和治理面，底层可能为每个角色启动独立 worker，系统不宣称它是单一 provider 会话。`cli_shell_coalescing_status.yml` 对真实返回物执行硬门槛：每个 packet 必须有 shell receipt，每个 role 必须有 receipt、非空 finding artifact 和 validation evidence。Receipts 必须声明 provider execution、无私有上下文、隔离 workspace、禁用项目读取和禁止 promotion，并且 SHA-256 必须匹配当前 materialized packet。哈希不匹配只会进入 `stale` 后重跑，安全合同冲突才会 fail。

当前 gate 已通过：`accepted_packets=2/2`、`accepted_roles=4/4`、missing/stale/failure 均为 0。`cli_shell_coalescing_collect.yml` 以纯本地方式把结果刷新进 capability/objective/goal/hygiene；这证明 CLI native runtime 与 receipt 回收机制，不等于 Crown 私有 Writer/media 质量验收。

Hermes 模型路由必须使用已安装 CLI 的真实注册语义：Supervisor profile 是 `agentlabsupervisor`，provider 为 `openai-codex`，model slug 为 `gpt-5.5`，`high` 写入 `agent.reasoning_effort`，不能伪造为 provider `codex` 或 model `gpt-5.5-high`；PromptEngineer 使用隔离 profile `agentlabpromptengineer` 和 `deepseek-v4-flash`。`--provision-only` 只克隆/校验本地 profile，不派发 kanban 或调用 provider；provisioner 以 `config.yaml` 是否真实落盘作为创建后置条件，兼容 Hermes 已创建 profile 但命令因后续清理返回非零的行为。两个 profile 的配置和认证预检均已通过。真实 Claude/Hermes role-session 仍会向模型发送任务上下文，因此当前私有工作区 live run 需要宿主外发审批；这不是 AgentLab 内部 role、route 或 provider 故障。

## 2. Agent 职责

| Agent | 职责 | 不应该做 |
|---|---|---|
| Frontdesk/Codex | 用户入口、任务提交、状态观察、报告已验证证据 | 扮演 Writer/ArtifactProducer/Supervisor 直接完成生产内容 |
| Supervisor | mission contract、route、scope、budget、production-pack selection、approval gates | 静默改源码或绕过审批 |
| RepoScout | 代码任务的仓库结构和上下文读取 | 改文件 |
| InterfaceMapper | 代码接口、契约、跨层边界分析 | 实现 patch |
| Researcher | 新领域/生产包需要外部资源或能力调查时产出 domain brief | 无证据地变成事实源 |
| Coder | 代码任务的实现、候选 patch、代码产物 | 默认产出小说、视频、文章等非代码任务 |
| ArtifactProducer | 非代码 artifact/production-pack contract 的产物生产 | 替代 Coder 改 source |
| Writer | 长篇叙事候选正文和轻路径 ledger | 直接 promotion 到 production memory |
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
| Crown 漫画/短视频/海报图册 | `media_generation_task` | `media_series_production` | Supervisor -> ArtifactProducer -> TesterAuditor -> Verifier | episode plan、shot list、character visual bible、asset registry、prompt pack、generation ledger、media QC |
| 未知复杂非代码领域 | `media_generation_task` + synthesis | `pack_synthesis_candidate` | Supervisor -> Researcher -> ArtifactProducer -> Verifier | domain research brief、pack proposal、memory contract、lifecycle profile |

这六条链路通过：

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

它不把历史 run 目录里的旧占位文件当作活动生产线证据，而是检查 `media_generation_task`、`media_series_production`、媒体 YAML 交付件、candidate-only 状态、promotion 阻断、无 production media 写入，以及本地 Grok CLI preflight 是否安全可解释。

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

当前验收范围由 `acceptance_runs/agentlab_capability_acceptance/goal_acceptance_scope.yml`
显式声明：代码项目和 Crown 长篇走完整验收；production-pack synthesis 本轮只要求
deterministic scaffold；媒体只要求 generation readiness。媒体成品、镜头连续性与质量
验收延期到后续 ComfyUI 式可视化节点工作流，不再用当前黑盒链路阻塞本 goal。

当前总报告：

```bash
./agentlab.sh capability-acceptance --out acceptance_runs/agentlab_capability_acceptance/current.yml
```

结果：

```text
overall_status: candidate
pass: 27
candidate: 5
```

已经成立的结论：

- 代码工厂路径仍在，`code_factory` 没被非代码改动削弱。
- 非代码任务不会默认继承代码壳。
- production-pack synthesis 的 deterministic scaffold、validator 和候选包三件套 smoke 已通过；带 persisted mission 与 exact outbound manifest 的真实 Supervisor -> Researcher -> ArtifactProducer -> Verifier 返回闭环仍是 candidate，二者不再混报。
- 核心大脑层 package import 稳定性已纳入机器验收：`workflow_plan`、`task_router`、`model_resolver`、`skill_injector`、`skill_usage`、`state_store` 等可作为 `agent_runtime.*` 包模块导入，package-mode workflow plan 能构建 `code_factory` 且不再让 skill plan / artifact intent 静默降级。
- 代表生产链可机器审计。
- CLI workflow shell governance 已并入主线：`config/cli_workflow_shells.yml`、`config/agent_role_bindings.yml`、`config/worker_invocation_contracts.yml`、`config/media_generation_backends.yml` 和 `config/agent_model_profiles.yml` 共同证明 full_cli 治理 shell capability/delivery，而不是重建 shell scaffold；Hermes/Claude Code/Agy/Codex/Qwen/Grok 的共通能力、独特能力、效率收益、交付契约和风险控制都有注册。
- CLI coalesced shell session 的 trusted-runner request 已被接受：`cli_shell_coalescing_runner_request.yml` 当前是 `accepted`，明确 Codex/frontdesk 不承担 AgentLab 角色执行，trusted runner 已返回 shell-level receipt、每个 delegated role 的 receipt 和 validation evidence。
- CLI coalesced shell trusted runner 已同时通过 canonical dry-run 与 synthetic live：dry-run 记录 `execute_requested=false`、`provider_calls_executed=false` 并展示安全命令形态；live reports 分别记录 Claude inline agents 与 Hermes kanban 的 `provider_calls_executed=true`，且不加载项目上下文。
- Hermes coalesced roles 已使用隔离的 `agentlabsupervisor` / `agentlabpromptengineer` profiles；前者已校正为 `openai-codex` + `gpt-5.5` + `high` reasoning，后者为 DeepSeek Flash。`cli_shell_coalescing_profile_provision.yml` 证明本地 provision-only 通过且 `provider_calls_executed=false`，两条 profile auth preflight 也通过。
- CLI coalesced shell session 的 post-run collector 已接入并通过：`cli_shell_coalescing_collect.yml` 会以纯本地方式刷新 status、runner request、capability、objective、goal 与 hygiene 报告；它拒绝密钥形态来源、校验 status/request SHA-256，且只允许 canonical 默认路径刷新总验收。collector 自身仍记录 `provider_calls_executed=false`，真实执行证据来自逐 packet shell receipts。
- CLI coalesced shell session 的 synthetic 返回验收已通过：`cli_shell_coalescing_status.yml` 为 `pass`，Claude Coder/Archivist 与 Hermes Supervisor/PromptEngineer 达到 `2/2 packets`、`4/4 roles`，missing/stale/failure 均为 0，两个 shell receipts 都记录 provider execution 并匹配当前 packet SHA-256。该 pass 只覆盖 native shell coordination/receipt mechanics，不覆盖 Crown 私有上下文产出质量。
- Crown 的本地长篇治理、mock 链路、1500 章治理模拟成立；`crown_heavy_audit_scale` 已明确通过 1500 章 governance-scale audit，但该审计只证明状态治理规模能力，不证明 1500 章正文质量。一章 live candidate 已通过本地 candidate audit，确认正文 565 行、候选状态变更、delivery receipt、reset baseline 和未写入 production manuscript。
- Crown 媒体连续剧 scaffold 已通过本地 media-series audit：活动路线是 `media_generation_task`，生产包是 `media_series_production`，episode/shot/visual bible/asset/prompt/generation/QC/receipt 都是 candidate-only，且没有写入 production media。
- Web UI/app 已完成 production promotion：候选 `artifacts/web_ui/` 通过 DOM/fetch、headless browser、operator interaction、run-local API write、截图像素和桌面/移动响应式视觉证据后，由 artifact steward 发布到 `projects/AgentLab/artifacts/web_ui/`，并写入 `archive_receipt.yml` 与 `project_artifact_index.yml`。
- DeepSeek text/code provider reachability 已通过无私有上下文 live smoke：`deepseek-v4-flash` 在禁用 thinking 的 ProviderSmoke 合同下返回 `AGENTLAB_PROVIDER_SMOKE_OK`，并记录 `finish_reason: stop`、输入/输出/总 token。此前空内容是短 smoke 未禁用 thinking 导致 `finish_reason: length`，不是当前 provider reachability 失败。
- Grok/xAI media adapter 已支持 `hermes_grok_oauth` / `local_grok_cli`；当前命令契约是本机 `hermes --ignore-rules --provider xai-oauth -m grok-build-0.1 -z <prompt>`。`grok` 已注册为 AgentLab 内部 `ArtifactProducer` 专用 worker。route、worker binding、OAuth CLI session、非交互 prompt contract、backend preflight、asset-return contract 和 candidate-only gate 均通过当前 readiness-only scope。`AGENTLAB_GENERATED_ASSET: <path>` 仍是未来真实产物回收硬合同，但本轮不以黑盒 media live artifact 作为完成条件，也不宣称视频质量或镜头连续性已验收。
- Frontdesk 边界已机器审计：Hermes CLI + DeepSeek V4 Pro 是默认 FrontDesk；Codex 仅是外部建设/审计 worker。Hermes 的 FrontDesk profile 与 Supervisor 等 role-session profile 严格分离。既定 pipeline 可走 direct closed loop，不要求 FrontDesk；Writer/ArtifactProducer 的 live 调用仍必须带对应 role-session evidence。Canonical flags 是 `hermes_frontdesk=True`、`direct_closed_loop=True`、`codex_external_worker=True`。
- Hermes FrontDesk 的真实 provider/model/auth 路径已做隔离非私有 smoke：从 `/private/tmp` 使用显式 `deepseek / deepseek-v4-pro` 一次性调用，Hermes 无 fallback provider，精确返回 `AGENTLAB_HERMES_DEEPSEEK_V4_PRO_FRONTDESK_OK`。证据在 `hermes_frontdesk_deepseek_v4_pro_smoke.yml`；该结果只证明 FrontDesk reachability，不替代 Crown Writer 私有 role-session 验收。
- Internal live-smoke readiness 当前是 `ready_for_internal_live_smoke`：route/safety readiness 已通过，`agy` 和 Grok/Hermes 的无私有上下文 session health 都通过，`session_health_issues: []`。Writer 仍要执行带项目上下文的 role-session acceptance smoke；媒体 readiness 已满足本轮 scope，其 live artifact item 转入 deferred。
- 术语边界：`private live smoke` 只是旧简称；canonical kind 是 `private_role_session_acceptance_smoke`，准确含义是“带项目上下文的角色会话验收跑”。它不是新的默认生产链路，只用于最终验收 Writer/ArtifactProducer 真实 provider 路径是否能返回候选产物；日常小说/媒体生产仍应走对应 production pack、记忆闭环和候选/晋升 gate。
- Trusted live runner request 现在带硬 gate：`--session-health-only` 前必须显式设置 `AGENTLAB_TRUSTED_LIVE_RUNNER=1`；真正会发送 Crown 私有上下文的完整 `.sh` 或 `--only ...` 私有 role-session acceptance 命令还必须同时设置 `AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1`。缺任一 gate 时脚本会拒绝继续，避免 Codex/frontdesk shell 再次污染 canonical smoke 报告或误发送私有上下文。完整运行 `.sh` 时会先执行无私有上下文的 `agy-cli-smoke`、`grok-cli-smoke` 和 `internal-live-readiness`；只要 `session_health_issues` 仍不为空，脚本会刷新 status 后退出，不会继续发送 Crown 私有正文或媒体上下文。该 request 还记录 `approval_gate_before_private_context: true` 与 `full_run_requires_trusted_status_pass: true`，完整脚本在刷新 status/collect 后会要求 `trusted_live_runner_status.yml` 顶层 `status: pass`，否则非零退出。
- Writer 私有上下文不再通过含 `agentlab_root` / `project_root` / `run_dir` 的通用 CLI task packet 暴露给 shell。`agy_writer` 使用只含完整 Writer messages 的 sealed packet，在临时隔离 cwd 中执行；chapter packet 的越界 `must_read` 会被拒绝。每次 provider 调用前必须写 `outbound_context_manifest_writer.yml`，只记录 payload/source 的 SHA-256、大小、相对路径、secret pattern 名称和 approval 状态，不记录正文或 secret 值。
- Production-pack synthesis 的 Supervisor、Researcher、ArtifactProducer、Verifier 都采用 packet-only 边界：CLI task packet 不再携带 `agentlab_root` / `project_root` / `run_dir` 等工作区路径，只携带 AgentLab 已组装的最小 messages，并在临时隔离 cwd 中执行。每个角色必须先写自己的 `outbound_context_manifest_<role>.yml`，使用独立批准域 `AGENTLAB_PRODUCTION_PACK_CONTEXT_APPROVED=1`；秘密模式命中、source 越界/缺失、payload 非精确或未批准时，都在 subprocess/API 调用之前阻断。full-cli 主 worker 不可用时直接 block；不得静默切换 direct API。显式 `full_api` 路线仍使用相同 manifest gate，但需要单独规划和批准 provider surface。
- Writer 返回值不再被当作整段 `fiction_draft.md`，narrative-eval 和普通 pipeline 共用 `writer_output_materializer.py`：只有同一 run 的四个完整 AGENTLAB_EDIT 候选块全部存在时才事务性写入，且 harness 不再用固定模板覆盖 Writer 的 continuity/state/receipt。`writer_output_contract.yml` 明确记录 `harness_generated_story_state: false`。
- Media live adapter 在调用 Grok/Hermes 前写 `outbound_context_manifest_media.yml`，hash 的是实际 1200 字符上限 media prompt；默认 subprocess cwd 使用临时隔离目录。secret 命中或 trusted acceptance 缺 approval 时在 command runner 之前阻断。
- Trusted live runner operator handoff 仍保留 Writer/media 两个可选 item，作为历史兼容和未来证据；当前 goal 只使用 Writer selected collect。媒体 item 即使仍为 pending，也只出现在 `deferred_internal_live_smokes`，不会进入 active blockers。Canonical 内部入口是 Hermes FrontDesk 提交或无 FrontDesk 的 direct closed loop，不再把 Codex 放进 AgentLab 执行链。
- 人读 handoff 的 canonical 路径是 `role_session_acceptance_handoff.md`；旧 `private_live_smoke_approval_handoff.md` 只保留为 legacy path，避免再把 legacy shorthand 当成正式生产链名称。
- Trusted live runner collector 已纳入能力矩阵：全局 collector 仍如实记录 Writer/media 两项历史状态，但 goal/objective audit 读取 Writer-specific selected collect。当前 active blocker 只有 `writer_missing_returned_artifacts`；media missing files 作为 deferred evidence 保留，不再污染当前完成条件。
- 兼容性与可观测字段仍完整保留：每项继续暴露 `required_files_exist`、`returned_candidate_artifacts_accepted` 和 `acceptance_blocker`。Collector 继续暴露 `acceptance_blockers`、`acceptance_blocker_reasons`、`required_files_missing_count`、`returned_candidate_artifacts_accepted_count`、`acceptance_report_hygiene_status`，并刷新 `live_unblock_plan.yml`。
- 当前全局 collector issue 仍是 `collector refreshed reports, but returned role-session acceptance artifacts are not accepted yet`。这个 issue 不是 session health，因为它只指向 deferred media item。当前计数是 `required_files_missing_count: 3`、`returned_candidate_artifacts_accepted_count: 1`。Writer blocker 是 `none`；media blocker 是 `missing_required_files`，reason 是 `missing_candidate_artifacts`，且 media 已被 scope 标为 deferred。
- Hygiene 继续记录 `canonical_text_artifact_count`、`canonical_text_issues`、`hygiene_private_selected_command_hits`、`stale_private_selected_command_hit_count`。Handoff 的 `selected_item_readiness` 当前仍显示 `selected_ready=run_crown_internal_writer_eval,run_crown_internal_media_smoke`、`selected_blocked=none`，但 active scope 只选择 Writer。`approval_gate_before_private_context` 与 `full_run_requires_trusted_status_pass` 仍保留，selected private role-session commands must include `AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1`。
- Acceptance report hygiene 已纳入验收证据：`acceptance_report_hygiene.yml` 当前是 `pass`。它把 `current.yml`、`objective_requirement_audit.yml`、`goal_completion_audit.yml`、`internal_live_readiness.yml`、trusted-runner 系列报告作为 canonical truth，也检查 `role_session_acceptance_handoff.md` 和 legacy handoff 的 required markers；当前 `canonical_text_artifact_count: 2`，`canonical_text_issues: []`。它还检查 selected 私有 role-session 命令是否带 `AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1`，当前 `stale_private_selected_command_hit_count: 0`，对应 policy 是 `selected private role-session commands must include AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1`。同时它把 `*_now` / `*_check` / `*_current` 归类为非权威快照；旧的手工 session smoke 快照如 `agy_cli_session_smoke_now.yml`、`grok_cli_session_smoke_now.yml` 只作为历史快照保留，不再覆盖 canonical smoke 结论。

当前 scope 内仍未完成的 live 质量验收：

- `crown_formal_live_narrative_eval`：candidate。旧 DeepSeek retry / host-policy rejection 只保留为历史证据；当前 full tier 的 Writer 已改为内部 AgentLab role-session：`agy` + `gemini_3_5_flash_high_agy_oauth`。还缺一次刷新后的单章 formal live smoke。

scope 外 deferred：`production_pack_synthesis_role_session` 四角色 provider live acceptance，
以及 `grok_xai_media_backend` 的真实 generated-assets/QC。两者的请求和安全合同保留，
但不要求本轮执行。

对应解阻计划：

```bash
./agentlab.sh live-unblock-plan --out acceptance_runs/agentlab_capability_acceptance/live_unblock_plan.yml
```

Frontdesk 安全 handoff：

```bash
./agentlab.sh frontdesk-live-handoff --agent hermes --out acceptance_runs/agentlab_capability_acceptance/frontdesk_live_handoff.yml
```

该 handoff 的含义是：Hermes/DeepSeek V4 Pro 可以作为可选 FrontDesk 提交 AgentLab 命令并观察 artifact；既定闭环也可以不经过 FrontDesk。live 正文生成归 Writer role-session，live 媒体生成归 ArtifactProducer role-session。

Trusted runner 可执行包：

```bash
./agentlab.sh trusted-live-runner-request --out acceptance_runs/agentlab_capability_acceptance/trusted_live_runner_request.yml --request-id <id>
```

生成的 `.sh` 可先用 `--preflight-only` 做本地路径/命令检查；完整运行前脚本会自动跑无私有上下文 session health，并在 health 不干净时拒绝进入私有 live 命令。`--session-health-only` 必须用 `AGENTLAB_TRUSTED_LIVE_RUNNER=1` 前缀；完整/selected 私有运行必须同时用 `AGENTLAB_TRUSTED_LIVE_RUNNER=1 AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1` 前缀。该 request 和 handoff 当前都是 `ready_for_trusted_runner`；后续阻塞不再是 session health，而是 private role-session acceptance artifacts 尚未返回或尚未通过 QC。

内部 live-smoke readiness：

```bash
./agentlab.sh internal-live-readiness --out acceptance_runs/agentlab_capability_acceptance/internal_live_readiness.yml
```

该报告当前是 `ready_for_internal_live_smoke`。含义是：本地 evidence、source report、frontdesk handoff、后续安全命令、secret 安全边界、两个内部 role-session 路由以及 `agy`/Grok-Hermes 无私有上下文 session health 都已经准备好。`external_acceptance_readiness.yml` 只是旧消费者兼容文件，canonical report type 是 `agentlab_internal_live_readiness`。

历史拒绝证据：

```text
acceptance_runs/agentlab_capability_acceptance/external_policy_rejection_writer_20260707.yml
```

仍待执行的内部 live smoke：

- `run_crown_internal_writer_eval`：用 Writer/agy role-session 跑一章 formal `narrative-eval live`；
- `run_crown_internal_media_smoke`：用 ArtifactProducer/grok role-session 跑 `media-backend-execute --live`，产物仍是 run-local candidate。

目标级闭合审计：

```bash
./agentlab.sh goal-completion-audit --out acceptance_runs/agentlab_capability_acceptance/goal_completion_audit.yml
```

当前 scope 逐条验收审计：

```bash
./agentlab.sh objective-requirement-audit --out acceptance_runs/agentlab_capability_acceptance/objective_requirement_audit.yml
```

它保留 11 条 requirement，并按 `goal_acceptance_scope.yml` 解释完成门槛。当前结果是 11 pass，状态为 `complete`。Crown Writer formal live acceptance 已通过；媒体 live artifact 和 production-pack 四角色 provider 验收仍按 scope 明确 deferred。

当前 scoped goal 状态是 `complete`：代码项目、Crown Writer formal live、媒体 generation readiness 和 production-pack deterministic scaffold 均达到各自门槛。active blocker 为空；production-pack 四角色和 media live artifact 仍在 deferred，不得被误报成已验收。

历史上的 Codex shell 私有上下文拒绝只说明外部 worker 入口选错，不能作为 AgentLab 内部 Writer、route、provider 或 role binding 失败证据。Canonical 验收应由 Hermes FrontDesk 提交，或直接通过 AgentLab role-session/pipeline 闭环执行；Codex 只读取返回 artifact 和审计报告。

该审计会检查源报告和每个目标项引用的证据路径是否真实存在；如果证据缺失，对应目标项不能继续保持 `pass`。

## 7. 目前应该如何继续

如果要继续扩大 live 证据，顺序应为：

1. 复用已通过的一章 formal `narrative-eval live` 作为基线，不要把 1500 章治理模拟误写成 1500 章正文质量证明。
2. 后续章节继续走 Writer light path，每 3/10 章及卷末按既定 cadence 做阶段审计。
3. Writer 返回物仍只能进入 run-local candidate artifacts，不能自动 promotion。
4. 媒体 live 生成等待未来可视化 node-graph 工作流，不回填到当前黑盒链路。
5. promotion 前必须经过 heavy audit / QC / human acceptance。

当前最诚实状态就是：

```text
本地治理和生产链：通过
候选 live 证据：Writer selected item 已通过
正式 live 内部 role-session：Crown 单章 Writer 验收通过；media live artifact 已 deferred
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
