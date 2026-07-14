# AgentLab 当前版本完整能力手册

语言：[English](CURRENT_VERSION_CAPABILITIES.en-US.md) | [中文](CURRENT_VERSION_CAPABILITIES.zh-CN.md)

> 本文记录 2026-07-14 的已提交能力快照。能力实现基线为 `424b983`，审计起点为 `b098513`。仓库尚未发布语义化版本，因此本文以日期和 Git 提交界定“当前版本”。

AgentLab 是本地优先的 AI Production OS 与长期项目治理后端。它负责合同、路由、预算、审批、证据、验收、恢复、记忆和归档，不替代 Codex、Claude Code、Hermes、Agy、Qwen 或 OpenClaw。

本文只描述 Git `HEAD=b098513` 已提交事实。审计期间工作区另有并行未提交改动；这些改动没有被计入当前 GitHub 版本，也不会被本次文档提交覆盖。

## 1. 快照、成熟度与验收口径

| 项目 | 当前事实 |
|---|---|
| 仓库 | `Kidrage/AgentLab` |
| 默认分支 | `main` |
| 本文能力实现基线 | `424b983`，`feat: govern agent roles and model capacity` |
| 本文审计起点 | `b098513`，角色/容量改造 handoff 已刷新 |
| 产品阶段 | M-series 对齐；M1 治理内核较完整，M2/M3 仍持续建设 |
| CLI 规模 | `./agentlab.sh --help` 当前列出 253 个顶层命令 |
| 完整测试基线 | `2663 passed, 24 skipped, 11 warnings` |
| 协议 Doctor | `106/106` 检查通过 |
| Artifact Doctor | `21/21` 检查通过 |
| 当前能力验收矩阵 | `27 pass / 5 candidate`，总体仍为 `candidate` |
| 本轮真实 provider 调用 | 0；没有模型、媒体或付费 API 调用 |

完整测试中的 22 个私有 Crown 用例在干净克隆中因无私有资产而跳过，但已在本机含资产环境通过。另有 2 个外部 live 用例按设计跳过。

当前“candidate”不等于失败。它表示本地合同、路由、审计和大部分闭环已验证，但仍有真实 Grok 媒体返回物、外部 provider 在线状态或人工 promotion 证据尚未收齐。

### 成熟度标签

| 标签 | 含义 | 代表能力 |
|---|---|---|
| 强约束可用 | 有确定性合同、失败关闭、证据与测试 | mission、workflow、24 节点 lifecycle、role binding、capacity、phase acceptance |
| 可用但轻量 | 可操作且有测试，但不是完整产品平台 | Project Brain、TUI、Web UI、task compaction、delivery manifest |
| mock-first / candidate | 合同和离线验收完整，真实后端仍受门控 | S9 通用 capability fabric、部分 retry、媒体 live acceptance |
| registry / plan-only | 只登记、盘点、生成计划或 handoff | external projects、未批准 external agents、部分 specialist backends |
| roadmap | 产品方向，不代表已实现 | 完整 CRM、自动营收、自动平台发布、多租户 SaaS |

## 2. 系统架构与治理边界

```text
自然语言目标
  → Mission Compiler v2
  → ProjectWorkflowPlan + 当前任务 WorkflowPlan
  → Production Pack + 角色/能力/预算路由
  → sealed role session / ArtifactTask packet
  → 本地工具、CLI worker 或受批准 provider
  → execution envelope + receipts + artifacts
  → review / audit / verify / phase acceptance
  → Project Brain、task index、handoff、archive
  → retry / recovery / resume / operator decision
```

AgentLab 始终拥有 mission、route、role packet、项目记忆、验证、验收和 promotion。CLI workflow shell 只在单个受限角色会话内编排工具和 provider 请求。

主要持久化边界：

- `projects/<project>/runs/<task_id>/`：任务事实、计划、状态、receipts、证据和候选产物。
- `projects/<project>/project_brain/`：路线图、阶段、决策、事实事件、快照和长期记忆。
- `skills/`：技能候选、生命周期、active registry、usage ledger 和 Vault。
- `acceptance_runs/`：离线验收、doctor、smoke 和候选 promotion 证据。
- `memory/repositories/`：仓库 HandOff 的共享镜像，不是源码替代品。

### 权威配置分层

| 事实 | 唯一或主要事实源 |
|---|---|
| 角色职责 | `config/agent_registry.yml`、`agent_templates/*.md` |
| 角色与 worker 绑定 | `config/agent_role_bindings.yml` |
| 默认角色后端选择 | `config/agent_model_profiles.yml` |
| CLI 精确命令模板 | `config/worker_invocation_contracts.yml` |
| 模型能力事实 | `config/model_catalog.yml` |
| Provider 事实 | `config/model_providers.yml` |
| 容量、breaker、fallback | `config/model_capacity.yml` |
| 数字定价 | `config/model_pricing.yml`，禁止其他文件复制数字价格 |
| ArtifactTask 路由 | `config/artifact_task_policy.yml` |
| 协议和审批 | `config/protocol_enforcement.yml`、`config/approval_policy.yml` |

默认模型模式是 `full_cli`，默认底层档位是 `performance`。公共预算名 `quality / balanced / frugal` 分别映射到底层 `full / performance / low`。

还存在 `qwen_token_plan_cli`、`full_api`、`hybrid_ide`。`trusted_headless_cli` 是显式安全例外，不是默认路径。

## 3. 14 角色、默认执行面与职责边界

AgentLab 有 14 个治理角色；“14 角色”与“24 生命周期节点”是两件不同的事。

| 层级 | 角色 | 当前主职责 | 默认或典型执行面 | 关键边界 |
|---|---|---|---|---|
| T1 | Supervisor | 规划、拆解、进度、恢复、最终综合 | Hermes + OpenAI Codex OAuth + GPT-5.6 Sol `xhigh` | 不接管 Writer、Coder、Producer |
| T2 | RepoScout | 低成本仓库定位和事实收集 | `rg`、Codex、Claude Code | 只读，不做实现 |
| T2 | Researcher | 外部网络、社媒、热点和证据调研 | Hermes + xAI OAuth + Grok 4.3 | 事实/推断分离，不写成品 |
| T2 | Observer | 长文和多模态只读观察 | Agy + Gemini 3.5 Flash High | 只输出文本，不写文件、不生成媒体 |
| T2 | InterfaceMapper | AST、接口、依赖和边界映射 | `ast-grep`、Codex、Claude Code | 不越权修改接口 |
| T2 | PromptEngineer | 角色提示、上下文和任务包设计 | Hermes / Claude / Qwen | 不替代执行角色 |
| T3 | Coder | 受限代码实现与修复 | Claude Code、Codex、Aider、Hermes | 仅允许文件和命令范围 |
| T3 | ArtifactProducer | 非代码候选产物 | Grok 媒体；Qwen 文档类 | candidate-only，不得自审 |
| T3 | Writer | 中文叙事候选写作 | Claude Code shell + DeepSeek | 不规划、不浏览、不改源码 |
| T4 | Reviewer | 内容、视觉、diff 和证据质量评审 | Qwen；视觉时 Agy；亦可 Claude | 必须独立于 Producer |
| T4 | Scribe | 状态、连续性和决策账本 | Qwen / Claude / Codex | 记录事实，不改写原产物 |
| T4 | TesterAuditor | 测试执行与测试充分性审计 | pytest / Claude / Codex / Hermes | 不把“声称通过”当证据 |
| T4 | Verifier | 格式、静态检查、完整性和闭环验证 | ruff / mypy / eslint / Claude / Codex / Hermes | 不负责 promotion 决策 |
| T5 | Archivist | 受控记忆写入、归档和 Git 交付 | git / Claude / Hermes | 只写批准路径和格式 |

绑定是双向的：角色必须允许 worker，worker 也必须允许角色。`--force` 不能绕过绑定；frontdesk-only 的 OpenClaw 永远不能被当作角色 worker。

### 默认 `full_cli` 模型矩阵

| 角色 | Full / quality | Performance / balanced | Low / frugal |
|---|---|---|---|
| Supervisor | Hermes + GPT-5.6 Sol `xhigh` | 同左 | 同左 |
| Observer | Agy Gemini 3.5 Flash High | 同左 | 同左 |
| RepoScout | Codex + DeepSeek V4 Pro | 同左 | Codex + Qwen 3.6 Flash |
| InterfaceMapper | Codex + DeepSeek V4 Pro | 同左 | 跳过 |
| Researcher | Hermes + Grok 4.3 | 同左 | 同左 |
| PromptEngineer | Hermes + Qwen 3.7 Max | Hermes + DeepSeek V4 Flash | Hermes + Qwen 3.6 Flash |
| Coder | Claude + DeepSeek V4 Pro | Claude + Qwen3 Coder Plus | Claude + Qwen3 Coder Next |
| ArtifactProducer | 按 ArtifactTask 类型分流 | 同左 | 同左 |
| Writer | Claude + DeepSeek V4 Pro | 同左 | Claude + DeepSeek V4 Flash |
| Reviewer | Qwen 3.6 Flash | 同左 | 同左 |
| Scribe | Qwen 3.6 Flash | 同左 | 同左 |
| TesterAuditor | Hermes + Qwen 3.7 Max | Codex + DeepSeek V4 Pro | Codex + DeepSeek V4 Flash |
| Verifier | Hermes + Qwen 3.6 Flash | Codex + DeepSeek V4 Flash | 同左 |
| Archivist | Claude + DeepSeek V4 Pro | 同左 | Claude + Qwen 3.6 Flash |

媒体 VisualReviewer 是独立 profile：优先 Agy/Gemini，容量和模态允许时可转 Agy/Claude。它不等同于普通 Qwen Reviewer。

## 4. 从目标到生产链

### 4.1 Mission Compiler v2

`mission-compiler compile` 用确定性规则把粗需求冻结成结构化合同。默认 CLI 编译过程不调用 LLM。

它识别 narrative、code、article、image/video generation/editing、multimodal、pack synthesis 等领域，并生成：

- `mission_contract.yml`：项目、目标、规模、约束、风险和非目标。
- `intent_summary.md`：人类可读目标摘要。
- `required_capabilities.yml`：能力、风险和审批需求。
- `artifact_contracts.yml`：目标产物、格式、路径和验收要求。
- `acceptance_gates.yml`：测试、审查、人工决策与 promotion 条件。
- `risk_flags.yml` 与 `decision_cards/`：未知事实、高风险动作和用户选择。

库层允许可选的 LLM 辅助 draft，但只有经过 schema 校验和规范化后才能成为候选，不能直接覆盖权威 mission。

### 4.2 两层计划

ProjectWorkflowPlan 按项目类型生成多阶段路线。每个 phase 固定输入、产物、能力、worker、验收门、人工决策、恢复策略、memory 更新和下一阶段条件。

当前任务 WorkflowPlan 装配 route、风险 R1–R3、budget、token、角色、model profile、validation、skills、memory、production pack 和 missing inputs。

R3 默认提升为 `max_quality`；R2 不默认使用 frugal。显式用户预算不会被系统擅自覆盖。

### 4.3 七类 Production Pack

| Pack | 使用场景 | 关键记忆/验收 |
|---|---|---|
| `code_factory` | 构建、修复、重构、测试、架构 | repo facts、diff、tests、verify |
| `narrative_longform` | 章节、批量章节、重审 | continuity/state ledgers，candidate-only |
| `article_light` | 短文章、轻量结构检查 | draft + review |
| `read_only_observation` | 长文、图、视频、音频、PDF | evidence locators + observation |
| `media_series_production` | 多集图像/视频 | 角色、场景、镜头、资产连续性 |
| `media_generation` | 单次图片/视频生成或编辑 | generation ledger、QC、独立视觉验收 |
| `generic_artifact` | 无更深领域包的非代码产物 | 通用 artifact contract |

没有现成 pack 的非代码域可生成 proposal、domain memory contract 和 lifecycle profile。候选必须 validate、审计并由用户或 Supervisor 批准后才能进入 catalog。

### 4.4 24 节点生命周期

```text
INIT_TASK
→ CONTEXT_PROFILE → CONTEXT_BUDGET → CONTEXT_PACK
→ PREPARE_PLAN → SUPERVISOR_PLAN
→ REPO_CONTEXT → RESEARCH_OPTIONAL → OBSERVATION_OPTIONAL → INTERFACE_OPTIONAL
→ WRITER_DRAFT → FICTION_REVIEW → SCRIBE_LEDGER
→ CODER_IMPLEMENTATION → ARTIFACT_PRODUCTION
→ VISUAL_OBSERVATION → VISUAL_REVIEW
→ VALIDATION → AUDIT → VERIFY → ARCHIVE
→ SELF_CHECK → SYNC_OPTIONAL → FINALIZE
```

Production Pack 会把不适用节点预标为 `skipped` 并写原因。节点保存 waiting、running、completed、skipped、paused 或 failed，以及时间、checkpoint、report 和 error。

resume 优先回到 failed/paused checkpoint，不越过到后续节点；completed 节点不会重跑。

### 4.5 执行、证据与阶段验收

`run-agent` 和 `run-pipeline` 默认 dry-run，强制 fake provider。只有显式 `--execute` 才能进入真实 provider 路径。

Task packet 固定 objective、context、允许/禁止文件、required outputs、acceptance criteria、must-read、允许/禁止命令、rollback、cost 和 repository handoff。

外部结果被规范成 `execution_result_envelope.yml`。changed files、测试、产物和安全声明都只是证据；缺少原始 evidence 时，外部“已通过”声明不能关闭阶段。

`phase-accept` 同时检查 scope、evidence、tests、human approval 和 project fact state。`NEEDS_HUMAN_REVIEW` 或 `NEEDS_EVIDENCE` 都不能视为完成。

## 5. 关键模型组合与小说能力

### 5.1 Supervisor：Hermes + GPT-5.6 Sol

Supervisor 使用 Hermes profile `agentlabsupervisor`，provider 为 `openai-codex`，模型为 `gpt-5.6-sol`，推理强度为 `xhigh`。用户写 `extra` 时会映射到 `xhigh`。

预检校验 profile、provider、model、reasoning 和空 fallback；任何尾部 argv 覆盖都会在 provider 启动前失败。

Supervisor 只做规划、拆解、进度、恢复和最终综合。容量故障时，可按同角色边界转 Claude shell + DeepSeek V4 Pro；不能转为 Writer 或 Producer。

本机旧 Hermes profile 可能仍是 GPT-5.5/high。AgentLab 不修改 `~/.hermes`，profile 未 provision 到精确配置时会 fail-closed。

### 5.2 Writer：Claude Code shell + DeepSeek

Writer 是纯中文叙事候选生产者。默认 DeepSeek V4 Pro，低成本档为 V4 Flash；普通合同的 CLI ceiling 是 1 美元。

Writer 使用 plan 权限、JSON 输出、空工具列表。它不能浏览网络、规划全项目、调用 subagent、修改源码或自行 promotion。

标准输出包含 prose candidate、continuity/state proposal 和 delivery receipt。V4 Pro 只在 `model_unavailable` 时转 Flash，不因质量主观判断静默降级。

### 5.3 Ultracode：显式发展性编辑模式

Ultracode 是独立 `WriterUltracode` route，不是普通 Writer 的隐式开关。必须同时满足：

- sealed Writer packet。
- `ultracode_opt_in: true`。
- `writer_mode: developmental_ultracode`。
- work type 属于 `developmental_edit`、`structure`、`continuity`、`revision_plan`。

它禁止 `final_prose_draft`，CLI ceiling 是 2 美元，必须写 activation receipt。失败后不静默转回普通写作。

### 5.4 Researcher：Hermes + Grok 4.3

Researcher 使用 xAI OAuth 和 Grok 的 `web`、`x_search` 工具，聚焦真实网络、社媒、热点、流行趋势与外部证据。

报告必须保留 URL、检索时间、事实与推断分离。Researcher 不写代码、长篇正文或媒体候选，也没有自动 provider fallback。

### 5.5 Observer：Agy 多模态只读层

Agy 只允许 Observer 和 Reviewer。它明确禁止 Supervisor、Writer、Coder、ArtifactProducer 等生产角色。

Gemini 3.5 Flash High 输入支持 text、image、video、audio、PDF；Claude Sonnet fallback 仅支持 text、image、PDF。两者都只输出文本，不能生成图像。

Observer 输出必须带可定位证据：图片区域/帧、视频关键帧与时间戳、音频时间戳、PDF 页码、长文段落或引用位置。

### 5.6 长篇小说交付、重审与规模治理

`narrative_longform` pack 把权威 story memory、chapter packet、候选正文、连续性账本、状态提案、fiction review、revision proposal、验证和 promotion 分开。

章节 packet 会读取 project fact snapshot、artifact index、production bible、当前 outline、candidate fact ledger，以及最近最多 3 个已接受候选章节。

Light chapter 的必需候选输出：

- `chapter_packet.yml`。
- `fiction_draft.md`。
- `continuity_ledger.yml`。
- `state_transition_proposal.yml`。
- `narrative_delivery_receipt.yml`。

Review gates 覆盖 continuity、character state、timeline、POV、style、scene goal、chapter hook 和 word count。

任何 blocking fiction review，或 `fail / rejected / needs_revision` verdict，都会阻断 archive 和 promotion。

`narrative-eval` 分 L0–L3：L0 检查事实源，L1 审计历史正文，L2 运行候选章节链，L3 做长篇治理规模模拟。

L2 支持 audit-only、mock、live、章节范围、恢复已验证章节和阻塞策略。其 live 是真实执行模式；只做离线审计时必须显式选择 `audit-only` 或 `mock`。

Heavy audit 将职责拆开：Reviewer 写 fiction/continuity 报告，Scribe 写状态提案，Verifier 写 revision/rewrite proposal。

三类输出都必须 `candidate_only:true`、`production_modified:false`。审计不能直接编辑正文。

连续性阻断时，Verifier 必须要求 rewrite 并给非空 proposals；`direct_draft_edits` 必须为 false。

Crown heavy-audit prepare 一次最多封装 20 章，逐文件记录 SHA256 和字符数，要求 production manuscript 保持为空。该命令只准备输入，不调用 provider。

L3 的 1500 章能力只验证 series arc、chapter state、伏笔、人物弧、timeline/worldline、audit cadence 和 promotion contract 的账本规模。

其事实标志为 `governance_ledger_only`，`draft_chapters_generated: 0`。这不是 1500 章正文生成或质量验收。

## 6. 多模态、媒体生成与视觉验收

### 6.1 真实媒体生产面

当前 `media_backend_adapter` 实际支持本地 Grok CLI 和 xAI Imagine REST。Bailian/Ark 虽已登记在 backend catalog，但当前 adapter 未实现，不能写成可执行后端。

Grok 媒体合同只做 image/video 工具编排。Grok 的文本回答不是媒体产物；必须存在真实文件、asset manifest、SHA256、generation ledger 和 receipt。

已登记模型包括 Grok Imagine Image Quality 与 Grok Imagine Video 1.5。真实调用需要 `--live`、准确认证和受治理 ArtifactProducer role session。

### 6.2 独立视觉验收链

```text
ArtifactProducer candidate
→ Observer 定位可检查证据
→ Reviewer 审美/连续性/技术/事实安全评审
→ Verifier 校验文件完整性、证据链、独立性和 promotion 边界
→ 外部 promotion gate 重新读取真实文件与 hash
```

Producer、Observer、Reviewer、Verifier 必须是独立角色和会话。Observer 与 Reviewer 可共享 Agy provider/model，但不得共享同一 session。

视觉候选记录路径、尺寸、SHA256 和 workspace 约束。promotion 会重新检查文件，验收后替换文件或 hash 变化都会阻断。

Reviewer 维度包含 aesthetic、continuity、technical、factual safety。Verifier 不重新做审美，而检查完整性、证据链和 reviewer independence。

### 6.3 媒体系列

`media_series_production` 为多集或多镜头任务维护角色、服装、场景、镜头、资产和时间连续性。它提供 scaffold 和审计，不代表自动完成整季生产。

Crown 的 1500 章验收是 `governance_ledger_only` 规模模拟，生成正文数为 0。Heavy-audit bundle 单次最多 20 章，不能把规模账本写成已生成 1500 章。

## 7. ArtifactTask：文档、表格、演示、图片和视频

ArtifactTask 必须声明类型、精确输出路径、格式、requirements、validation 和 routing。缺少任一关键字段会在 provider 前阻断。

| 产物 | 当前默认生产者 | 格式 | 状态 |
|---|---|---|---|
| 文本/文档 | Qwen CLI | `md`、`txt`、`docx` | 支持 |
| 表格 | Qwen CLI | `xlsx`、`csv` | 支持 |
| 演示 | Qwen CLI | `pptx`、`pdf` | 支持 |
| 图片 | Grok / xAI Imagine | `png`、`jpg`、`webp` | candidate；需视觉验收 |
| 视频 | Grok / xAI Imagine | `mp4`、`mov` | candidate；需视觉验收 |
| 音频 | 无受治理 producer | — | fail-closed，`capability_mismatch` |
| 跨 provider mixed | 无 composite adapter | — | fail-closed，`capability_mismatch` |

Qwen 文档路线按 Max → Plus → Flash 多跳，每一跳只允许 `model_unavailable`。Grok 图片/视频没有自动 fallback。

### 输入与输出隔离

- Assigned input 必须是 workspace root 内普通文件；目录、symlink、path escape 均在 provider 前失败。
- 系统只复制声明输入，并绑定原始 bytes 与 SHA256；复制后设置只读权限。
- provider 运行后只回收精确声明输出，不扫描或接受额外文件。
- 后检记录 inode、size、mtime、ctime、SHA256、目录 `0500` 和文件 `0400`。
- Observer、Reviewer、Verifier 任一步发现输入或候选被修改，都会失败关闭。

### 结构与格式验证

- XLSX、DOCX、PPTX：检查 ZIP package、`[Content_Types].xml` 和核心 Office entry。
- PDF、PNG、JPEG、WebP、MP4/MOV：检查文件签名。
- YAML：必须可解析。
- Markdown、TXT、CSV、JSON：必须是 UTF-8。
- 空文件、空目录、超过 512 MiB 的 materialization 均失败。

这些检查证明结构和交付合同有效，不证明公式正确、PPT 美观或内容准确。内容质量仍需 Reviewer、Verifier 或人工验收。

Qwen Artifact 使用 `--approval-mode yolo`，Grok 使用 `--ignore-rules`。这些命令本身是高风险的；安全来自 sealed packet、隔离 workspace、精确输出回收、审批和 receipts。

## 8. 容量、订阅窗口、breaker 与 fallback

容量账本是 run-local 原子 YAML：`model_capacity_ledger.yml`。它只保存结构化观察，不保存 probe 原始输出。

### 容量池

| Pool | 计费模式 | 已知窗口 | 诚实状态 |
|---|---|---|---|
| `agy_gemini_observer` | subscription | 5h rolling + weekly | limit/remaining/reset 均为 `null` |
| `agy_claude_observer` | subscription | 5h rolling + weekly | limit/remaining/reset 均为 `null` |
| `openai_codex_agentic` | subscription | 未知 | 全部 `null`，运行时观察 |
| `xai_subscription_shared` | subscription | 未知 | 全部 `null`，运行时观察 |
| `deepseek_metered_api` | metered API | 无 quota probe | 由真实成功/失败更新 |
| `dashscope_metered_api` | metered API | 无 quota probe | 由真实成功/失败更新 |

两个 Agy pool 分开记账，但不代表系统知道具体额度。Agy 没有可靠 quota API，AgentLab 不猜 remaining 或 reset。

### 故障范围

- `rate_limited`、`quota_exhausted`、`auth_missing` 是 pool-scoped，会打开共享池 breaker。
- `model_unavailable` 是 route-scoped，只阻断具体 route。
- `unknown` 不是容量证据，不会打开 breaker。

breaker 到期后只发一个 300 秒 canary lease。只有 lease owner 的成功可以关闭 breaker；文件锁防止并发 worker 同时抢跑。

### 当前 fallback 图

| 起点 | 允许 fallback | 触发条件 |
|---|---|---|
| Supervisor GPT-5.6 Sol | Claude + DeepSeek V4 Pro | rate/quota/auth/model unavailable |
| Observer Gemini | Agy Claude | quota/rate/model unavailable；仅模态兼容时 |
| VisualReviewer Gemini | Agy Claude | 同上 |
| Qwen Artifact Max | Plus → Flash | 每跳仅 model unavailable |
| Writer Pro | Writer Flash | 仅 model unavailable |
| WriterUltracode | 无 | 失败即报告 |
| Researcher / Grok media | 无 | 失败即报告 |

Fallback 用声明顺序 DFS，可支持任意深度。循环、重复 route、未知 route、跨角色、前驱故障不匹配或模态不兼容都会 fail-closed。

Observer 的 Claude route 不支持 video/audio，因此这两类任务不能借 fallback 丢失模态。Receipt 保留完整 `route_chain` 和 `attempt_id`。

安全 probe 仅允许 `agy models` 与 `hermes auth status <provider>`。`hermes status --all` 被明确禁止，以免泄露认证信息。

## 9. 定价、预算、token 与成本账本

`config/model_pricing.yml` 是唯一数字价格事实源，版本 3，币种 USD，最近核验日期为 2026-07-13。

### 文本模型参考价格

单位均为 USD / 1M tokens。

| 模型 | Input | Cache read | Output | 说明 |
|---|---:|---:|---:|---|
| Qwen 3.7 Max | 1.650 | — | 4.951 | DashScope CN |
| Qwen 3.6 Plus | 0.276 | — | 1.651 | DashScope CN |
| Qwen3 Coder Next | 0.144 | — | 0.574 | DashScope CN |
| Qwen3 Coder Plus | 0.574 | — | 2.294 | 0–32k tier |
| Qwen 3.6 Flash | 0.165 | — | 0.990 | DashScope CN |
| DeepSeek V4 Flash | 0.140 | 0.0028 | 0.280 | input 为 cache miss |
| DeepSeek V4 Pro | 0.435 | 0.003625 | 0.870 | input 为 cache miss |
| GPT-5.6 Sol API 参考 | 5.000 | 0.500 | 30.000 | 不用于 Hermes OAuth 结算 |
| Grok 4.3 API 参考 | 1.250 | 0.200 | 2.500 | 不用于 Hermes xAI OAuth 结算 |

Hermes OpenAI-Codex OAuth 与 Hermes xAI OAuth 都是 subscription 路线。AgentLab 不能把公开 API token 价格伪装成订阅会话的实际成本。

### 媒体单位价格

| 模型 | 单位 | 价格 USD |
|---|---|---:|
| Grok Imagine Image Quality | input image | 0.01 |
| 同上 | output image 1K | 0.05 |
| 同上 | output image 2K | 0.07 |
| Grok Imagine Video 1.5 | input image | 0.01 |
| 同上 | 480p output / second | 0.08 |
| 同上 | 720p output / second | 0.14 |
| 同上 | 1080p output / second | 0.25 |

媒体账单只有在所有正数 billing unit 都有价格时才计算总价。缺少任一单价时返回 `null`，避免假精确。

### 三层成本边界

- Invocation contract ceiling：限制单次 CLI，如 Writer 1 美元、Ultracode 2 美元。
- Approval policy：未知 CLI 成本或超过 0.50 美元的动作生成 decision card。
- Task/project budget：由 `budget_policy.yml`、`cost_policy_v2.yml` 和 BudgetGate 控制总任务或项目。

这三层不能混为一谈。单次 CLI 未超 ceiling，不代表项目总预算自动通过。

### Usage 与 receipts

Usage ledger 记录 exact usage/cost、estimated cost、currency、pricing source/confidence、usage source 和 unpriced reason。

它还透传 capacity route/pool/status、attempt、failure、selected CLI/model，以及 provider 实际报告的 model/session。

外部 CLI 未返回原生 usage 时写 `unavailable/null`。只有 direct API 有真实 token 数时，才能依据价格表计算成本。

## 10. CLI 合同、协议、receipts 与错误

### 10.1 Workspace、Frontdesk 与 Role Session

`workspace-entry` 生成 root、branch/HEAD、agent 能力、允许角色、recent task、事实源和禁止行为。Worker 不应先重扫整个仓库。

Frontdesk 只做需求捕获、解释状态、创建 task/handoff、调用登记合同、监控和报告。它不能实施目标、编辑核心 config/production，或静默换 agent。

OpenClaw 是 frontdesk-only。Hermes、Agy、Qwen 即使兼具 frontdesk，也必须与正式 role session 分开。

Role session packet 包含 role/worker、绑定 verdict、revision state、must-read、required outputs、source/shell policy、forbidden actions 和 exit evidence。

Coder 或 Writer 若 revision governance 未清，会在 dispatch 前阻断。

### 10.2 精确 CLI 合同

- Hermes Supervisor 固定 profile、provider、model 和最大 reasoning，禁止尾部覆盖。
- Claude Writer 使用 plan、JSON、空 tools 和预算 ceiling。
- Codex 使用 `codex exec --json --model ... -C <workspace>`，工作区显式。
- Qwen 通用合同使用 `--bare --approval-mode default --output-format json`。
- Agy Observer/Reviewer 使用 OAuth，进程环境移除 API-key fallback。
- Grok Research 与 Grok Media 是两份不同合同；Media 不继承 research tools。

### 10.3 不可变执行证据

每次受治理尝试写 `model_execution_receipt_<role>_<route>_<attempt>.yml`，并推进 `model_execution_chain_<role>.yml`。

Chain 记录 route、pool、selection kind、provider、selected/reported model、issues、fallback 原因和最终 receipt。

专项证据还包括：

- Agy：profile/argv、OAuth provider/model、unset API-key env、capacity route。
- Supervisor：Hermes profile path+SHA256、provider/model/xhigh 和空 fallback。
- Claude：原生 JSON token/cache/cost/session、selected 与 reported model 差异。
- Qwen Artifact：DashScope auth/base URL、reported model、materialization receipt、output hash。
- Grok Research：只读 sealed workspace、tool allowlist、credential 只记存在性。
- Grok Media：generation ledger、receipt、assets manifest。
- Ultracode：独立 `ultracode_activation_receipt.yml`。

### 10.4 错误分类

通用 CLI 错误类：

`binary_missing`、`timeout`、`invalid_cli_invocation`、`auth_required`、`network_required`、`permission_denied`、`quota_exhausted`、`model_unavailable`、`rate_limited`、`task_failed`、`unknown_failure`。

容量层再归一为 `auth_missing`、`quota_exhausted`、`rate_limited`、`model_unavailable` 或 `unknown`。

### 10.5 Capability schema 与 S9 fabric

AgentLab 有两层不同能力概念：

1. Role capability schema：定义角色可用或禁止的 planning、file edit、multimodal observation、artifact generation 等能力。
2. S9 capability fabric：mock-first 的通用 provider registry 与 permission gate。

当前 S9 中 `filesystem_read` 与 `ide_handoff` 可用；write、git、shell、web/browser 需审批；OCR、audio、PDF、spreadsheet、database、GitHub ops 等通用 backend 仍是 missing/mock。

这不否定受治理 Agy、Grok 或 Qwen 专用 role route。专用路线有独立合同，不能被 S9 registry 的状态替代。

## 11. 项目记忆、上下文、技能、恢复与外部集成

### 11.1 Project Brain 与长期项目

`project-brain-init` 可生成 product vision、project brief、roadmap、milestone graph、state contract、fact snapshot/event log、decision log、acceptance history、risks、phase plan 和 next actions。

Workflow phases 优先转为 milestones。缺少 workflow 时，creative、coding 和 other 各有确定性三阶段 fallback roadmap。

项目事实状态采用 append-only event + rebuild snapshot。影响状态的产物必须带 `artifact_lineage.yml` 和 `state_transition_proposal.yml`，仅在 phase acceptance 后应用。

Delivery manager 当前生成 delivery manifest/skeleton，不是自动发布或完整商业交付系统。

### 11.2 上下文治理

系统可识别 short/long text、narrative、code repo、audit/debug、web research、crawl batch、data/stream、logs、tool output、image、history 和 abstract reasoning。

它生成 `context_profile.yml`、`context_budget.yml`、`context_pack.yml` 和 `compression_trace.yml`，限制输入、输出、工具回传、来源、文件和图像 crop。

Repo、narrative、long text、web、crawl、data、log、tool output、image、history 和 reasoning 均有 packer。

Code、config、legal 和证据类内容禁止有损压缩。Image context packer 本身不做真实 OCR/视觉理解；真实观察由 Agy Observer 承担。

### 11.3 Repository HandOff 与任务发现

`repository-handoff` 只扫描路径和有限元数据，不跟随 symlink、不读取二进制或密钥、不批量倾倒源码。

它生成 `PROJECT_HANDOFF.md`、`.agentlab/HandOff.md`、`agent_docs/HandOff.md` 和共享 memory 镜像。

Task index 支持 list、find、open、map、artifacts 和 resume candidates。Repository HandOff 是仓库级记忆，task index 是运行级发现，两者用途不同。

### 11.4 Skills 全生命周期

Active skill 从 registry 和 `skills/active/` 匹配；按 trigger、confidence、risk 和预计 token saving 排序。高风险技能不会静默注入，而会创建审批卡。

生命周期：

```text
pending request → approved/rejected → staging → validated → active → retired
```

Skill Vault 提供 registry、布局、迁移、备份计划和状态。`skill-distill` 可从任务记忆生成脱敏 draft，但 draft 不可直接执行。

Trace-to-Skill 与 post-task learning 可从重复成功/失败轨迹生成 candidate，仍需安全审查和人工批准。

URL importer 要求 policy 开启、host/path allowlist 和显式 `--allow-network`。ECC 仅支持静态 scan-only；登记不等于启用。

Legacy skill staging 的验证是 fake sandbox，只检查 metadata 和文件可读性，不是通用安全沙箱。

### 11.5 Failure、retry、recovery 与 resume

Failure event 保存脱敏错误、相关 artifact 和分类。诊断生成 root-cause hypotheses、evidence、blast radius、confidence、warnings 和 human-review requirement。

Recovery plan 固定 safe/unsafe commands、validation、stop conditions。Fake-evidence detector 要求来源 hash 和 line refs。

Verdict 为 retry、human_review、stop 或 continue。Stop 必须 human approve；`--force` 只能在有批准时覆盖，并留下审计标志。

通用 retry manager 支持 attempt ledger、3E review、scorecard、重复失败和预算停止，但 HEAD 的自动执行仍是 mock-first。

### 11.6 P/S 系列能力家族

| 家族 | 当前能力 | 边界 |
|---|---|---|
| P0 | CostLedger、Pricing、BudgetGate、RepoManifest、CloneGuard、ResourceLedger、Artifact Gate、Pipeline | 本地治理底座 |
| P1 | External skill registry、ECC scan、external agent handoff、search/repo adapters | 默认禁用或 data-only |
| P2 | 3E review、retry policy、provider scorecard、context governance、failure recovery、closure feedback | 外部自动 retry 仍受门控 |
| S7 | Project Brain、roadmap、phase plan、accept/replan/snapshot | 决定性长期编排 |
| S8 | Executor packet、result ingest、review、phase acceptance | 外部结果只是证据 |
| S9 | Capability registry、permission gate、gap cards | mock-first |
| S10 | Offline generalization suite、CI gate policy | 不调用外部能力 |
| S11 | Read-only ops snapshot、local serve plan | 不是公网控制台 |
| S12 | Service match、quote、timeline、delivery skeleton | planning，不是自动商业履约 |

### 11.7 External projects、agents 与 MCP

External projects 支持 registry、capability map 和 risk report，默认 `registry_only`、shell/network false。它不会自动 clone、安装或执行。

External agent 模块生成脱敏 handoff 和 append-only ledger。结果经 normalization、evidence validation 和 phase acceptance，不能直接标记通过。

MCP stdio server 使用 JSON-RPC，protocol `2025-06-18`，暴露 21 个 task、decision、skill、watchdog 和 external-skill 工具。

MCP 默认 `enabled=false`；写操作分别受 policy 开关。External-skill MCP 工具只读，路径和 registry 内容会脱敏。

## 12. 安全、审批与禁止行为

### 默认安全姿态

- Local-first；真实 provider、网络、外部写入和安装默认关闭。
- Pipeline 默认 dry-run/fake provider；真实调用需 `--execute` 或专项 `--live`。
- 所有外部 argv 用 `shlex` 解析并以 `shell=false` 执行。
- Provider/model 变更只能走治理 proposal 或 capacity fallback。
- Unknown CLI cost、shell、network、filesystem write 和 browser 产生审批。
- Critical secret、私有路径和 destructive shell 必须显式人工批准。

### Frontdesk 与路径保护

Frontdesk protected paths 包含核心 model/binding config、`agent_runtime/**` 和 `production/**`。前台会话不能借“聊天”身份编辑这些路径。

Archivist memory writer 只接受批准的 agent docs 路径，以及受控 SEARCH/REPLACE 或 YAML merge block。

### Secret 与认证

密钥保存在 env 或 CLI 私有认证存储。Shared directory 禁止 credential；provider status 永不打印 key；日志递归遮蔽 api_key、secret、token 和 bearer。

Grok receipt 只记录 credential 是否存在，`credential_values_recorded:false`。容量 probe 原文不会落盘。

### Runtime hygiene

`runtime-doctor` 汇总 layout、symlink、gitignore 和 secret scan。扫描不跟随 symlink。

服务默认仅绑定 `127.0.0.1` 或本地进程。公开 bind 和 endpoint override 需要审批。

### 有意保留的高风险命令

Claude 通用代码合同使用 `bypassPermissions`，Qwen Artifact 使用 `yolo`，Grok 使用 `--ignore-rules`。

它们不是低风险命令。AgentLab 依靠 role binding、sealed packet、isolated workspace、allowed paths、审批、hash 和 receipts 把风险约束在任务范围内。

## 13. 测试、Doctors、CI 与验收

### 已验证基线

| 验证 | 结果 |
|---|---|
| 角色/容量 focused regression | `248 passed` |
| Capacity regression | `86 passed` |
| 完整 pytest | `2663 passed, 24 skipped, 11 warnings` |
| Model routing doctor | 0 issues |
| Artifact doctor | `21/21` |
| Protocol doctor | `106/106` |
| Agent role chain audit | pass |
| 文档/实现分支 CI | GitHub Actions `29275493261`、`29276017764` 均成功 |

CI 使用 Python 3.11，执行 text integrity、compileall、pytest、S10 generalization、`git diff --check`、入口 help/compile 和 forbidden tracked file 检查。

当前 canonical capability acceptance 为 `candidate`：27 项 pass，5 项 candidate。Live provider 证据不完整的能力不会被离线测试伪装成 production-ready。

### Web UI smoke matrix

Web UI 有 candidate、headless browser、interaction、API、visual 和 responsive smoke。它们验证 DOM、交互、写 API、截图像素健康和桌面/移动布局。

### TUI、Web UI 与 Ops surfaces

`tui` 支持 overview、phases、tasks、evidence、costs、approvals、recovery、artifacts、config 的 headless snapshot。

`webui` 和 `web_ui/server.py` 提供本地 dashboard、JSON API 与 SSE。POST 需要 `AGENTLAB_WEB_UI_TOKEN` 和 `X-AgentLab-Token`；未配置时返回 403。

Web server 使用内置 `HTTPServer`，无 TLS、多用户 session 或 RBAC，只适合本机。部分只读 GET 无 token，严禁公网暴露。

S11 ops console 是 read-only snapshot 或本地 serve plan；CLI core 不依赖 UI。

## 14. Operator 命令与完整命令面

先查看命令自己的 help；参数会随能力演进：

```bash
./agentlab.sh <command> --help
./agentlab.sh models --help
./agentlab.sh mission-compiler --help
./agentlab.sh narrative --help
```

### 14.1 推荐日常路径

```bash
# 健康、协议与模型
./agentlab.sh doctor
./agentlab.sh runtime-doctor
./agentlab.sh protocol-doctor
./agentlab.sh artifact-doctor
./agentlab.sh models show
./agentlab.sh models capacity
./agentlab.sh model-doctor

# 从需求到 dry-run
./agentlab.sh init-task --project <Project> --task-id <task_id>
./agentlab.sh prepare --project <Project> --task-id <task_id> --write-plan
./agentlab.sh run-pipeline --project <Project> --task-id <task_id>
./agentlab.sh status --project <Project> --task-id <task_id>

# 强制角色会话
./agentlab.sh workspace-entry --agent <agent>
./agentlab.sh frontdesk-session --agent <agent>
./agentlab.sh role-session --role <Role> --worker <worker> --project <P> --task-id <T>
./agentlab.sh role-doctor --role <Role> --worker <worker>

# ArtifactTask
./agentlab.sh artifact-task-plan --task-text "<goal>" --project <P> --task-id <T> --write
./agentlab.sh media-backend-preflight --help
./agentlab.sh artifact-check --project <P> --task-id <T>

# Writer Ultracode，真实调用前仍需审批与正确认证
./agentlab.sh run-agent Writer --project <P> --task-id <T> \
  --writer-ultracode --writer-work-type revision_plan --execute

# 长项目与恢复
./agentlab.sh project-brain-init --mission-contract <mission.yml> \
  --project <P> --out projects/<P>/project_brain
./agentlab.sh project-plan --project-brain projects/<P>/project_brain \
  --out <phase_plan_dir>
./agentlab.sh project-next --project-brain projects/<P>/project_brain \
  --out <next_action_dir>
./agentlab.sh phase-accept --phase-plan <phase_plan.yml> \
  --evidence-dir <evidence_dir> --out <acceptance_dir>
./agentlab.sh recovery-status --project <P> --task-id <T>
```

### 14.2 顶层命令分组索引

当前 help 有 253 个顶层命令。以下按操作域分组；子应用另有自己的二级命令。

#### UI、状态与基础操作

`tui`, `webui`, `doctor`, `status`, `progress`, `brain-status`, `harness-status`, `policy-status`, `chat`, `daemon`, `daemon-status`, `ops-console-status`, `ops-console-serve`, `service-factory-plan`, `timeline`, `event-log-tail`.

#### Intake、任务、路由与生命周期

`init-task`, `task-clear`, `task-list`, `task-index`, `task-find`, `task-open`, `task-resume-candidates`, `task-map`, `task-artifacts`, `prepare`, `project-workflow-plan`, `route-probe`, `assign-role`, `route-task`, `route-explain`, `activation-plan`, `activation-explain`, `run-agent`, `run-next`, `run-pipeline`, `lifecycle-status`, `pause`, `resume`, `recover`, `guard-status`.

#### 协议、角色、worker 与 CLI entrypoint

`repository-handoff`, `workspace-entry`, `frontdesk-context`, `frontdesk-session`, `role-session`, `frontdesk-doctor`, `frontdesk-write-gate`, `role-doctor`, `protocol-doctor`, `frontdesk-boundary-audit`, `role-requirements`, `role-inspect`, `role-compatible-workers`, `worker-scan`, `worker-list`, `worker-inspect`, `worker-doctor`, `worker-contracts`, `worker-contract-validate`, `worker-invocation-probe`, `worker-invocation-report`, `worker-audition`, `worker-scorecard`, `cli-entrypoint-scan`, `cli-entrypoint-bootstrap`, `cli-entrypoint-install`, `cli-entrypoint-doctor`, `cli-entrypoint-status`, `configure-agent`.

#### Capability、provider 与执行经济

`capability-list`, `capability-check`, `capability-gap`, `capabilities`, `capability-providers`, `capability-provider-inspect`, `capability-broker-plan`, `provider-trust-report`, `skill-discover`, `mcp-discover`, `execution-economy-report`, `estimate-spawn-cost`, `cache-profile-report`, `request-traversal`, `request-coder-quota`.

#### Models、provider、成本与审批

`models`, `model-doctor`, `providers`, `provider-test`, `provider-smoke`, `grok-cli-smoke`, `agy-cli-smoke`, `budget-eval`, `cost-status`, `cost-estimate`, `cost-alerts`, `cost-efficiency-review`, `approvals`, `approve`, `reject`, `log-event`.

#### Context、memory 与 Project Brain

`workspace-scan`, `context-profile`, `context-budget`, `context-pack`, `context-show`, `context-audit`, `context-build`, `context-status`, `context-smoke`, `project-brain-init`, `project-plan`, `project-next`, `phase-accept`, `phase-replan`, `project-summarize-phase`, `project-snapshot`, `ingest-repo-memory`.

#### Artifact、媒体与 Production Pack

`artifact-task-plan`, `artifact-doctor`, `artifact-check`, `vision-contract`, `audio-contract`, `document-contract`, `media-backend-preflight`, `media-backend-execute`, `ingest-artifact`, `pack-candidate-validate`, `pack-catalog-audit`, `pack-candidate-promote`, `production-pack-synthesis-smoke`, `production-pack-role-session-request`, `production-pack-role-session-audit`, `production-chain-audit`, `media-series-scaffold-audit`.

#### Skills、Vault 与学习

`skill-status`, `skill-distill`, `skill-draft-list`, `skill-draft-approve`, `skill-draft-reject`, `skill-vault-list`, `skill-vault-status`, `skill-vault-migrate`, `skill-vault-backup`, `skill-vault-backup-status`, `skill-request`, `skill-list`, `skill-approve`, `skill-reject`, `skill-stage`, `skill-validate`, `skill-promote`, `skill-retire`, `skill-match`, `skill-inject`, `skill-usage`, `skill-import-url`, `skill-candidates`, `skill-candidate-approve`, `skill-candidate-reject`, `skill-candidate-list`, `skill-candidate-show`, `skill-registry-validate`, `learning-review`.

#### Feedback、decisions、watchdog 与 webhooks

`feedback-status`, `watchdog-scan`, `watchdog-status`, `webhook-test`, `webhook-status`, `webhook-redeliver`, `task-event`, `decision-list`, `decision-approve`, `decision-reject`, `decision-resume`.

#### Recovery、closure 与 executor connector

`failure-diagnose`, `failure-status`, `recovery-plan`, `recovery-smoke`, `recovery-brain-plan`, `recovery-approve`, `recovery-reject`, `recovery-stop`, `recovery-status`, `recovery-feedback`, `p2-capability-map`, `p2-closure`, `executor-task-create`, `executor-result-ingest`, `executor-review`.

#### Acceptance、CI 与受信 live runner

`eval-generalization`, `ci-gates`, `capability-acceptance`, `agent-role-chain-audit`, `goal-completion-audit`, `objective-requirement-audit`, `acceptance-report-hygiene`, `live-unblock-plan`, `external-acceptance-readiness`, `internal-live-readiness`, `frontdesk-live-handoff`, `trusted-live-runner-request`, `trusted-live-runner-status`, `trusted-live-runner-operator-handoff`, `trusted-live-runner-collect`, `trusted-live-runner-preflight`, `cli-shell-coalescing-plan`, `cli-shell-coalescing-status`, `cli-shell-coalescing-runner-request`, `cli-shell-coalescing-runner`, `cli-shell-coalescing-collect`.

#### Web UI 与专项 acceptance smoke

`m2-operator-demo`, `web-ui-candidate-smoke`, `web-ui-browser-smoke`, `web-ui-interaction-smoke`, `web-ui-api-smoke`, `web-ui-visual-smoke`, `web-ui-responsive-smoke`, `m1-demo`, `performance-eval`.

#### Crown / longform 专项治理

`crown-live-candidate-audit`, `crown-scale-governance-audit`, `crown-completion-batch-audit`, `crown-heavy-audit-prepare`.

#### Codex driver 与 continuation

`codex-start`, `codex-status`, `codex-handoff`, `codex-resume`, `codex-verify-artifacts`, `continue-with-api`.

#### Runtime hygiene、迁移、同步与备份

`runtime-doctor`, `runtime-layout`, `runtime-audit-symlinks`, `runtime-secret-scan`, `check`, `sync`, `sync-status`, `migration-doctor`, `migration-init`, `truenas-status`, `truenas-sync`, `backup-status`.

#### 模块化二级命令入口

`external-skills`, `search`, `repo-index`, `external-projects`, `mission-compiler`, `config`, `assistant`, `goal`, `governance`, `narrative`, `narrative-eval`.

## 15. 当前限制、非承诺与运维注意事项

- 当前版本仍在 active development，253 个命令不代表 253 个 production-ready 外部能力。
- Canonical 默认是 `full_cli`；`full_api`、hybrid 和 token-plan 不代表所有角色/模态均已闭环。
- 没有受治理音频 producer；跨 provider mixed 没有 composite adapter。
- Agy 的 limit、remaining、reset 不可查询，必须保持 `null`。
- Agy Claude fallback 不支持 video/audio，不能降模态继续。
- OpenAI/xAI OAuth 窗口未知；subscription 不能按 API 价结算。
- Grok 文本不是媒体；没有真实文件、hash 和 manifest 就是失败。
- Bailian/Ark 当前只在 catalog 登记，不在实际 media adapter 支持列表。
- Gemini API free tier 只是显式备用 rough-work 路线，不是 Agy OAuth 的默认替代。
- Codex Plus 是手动 IDE handoff；AgentLab 不把它当 direct API。
- Hermes 本地 Supervisor profile 不匹配时 fail-closed；AgentLab 不修改用户私有 profile。
- CLI entrypoint 文件是 advisory；wrapper 才是可靠的强制执行路径。
- Generic retry 自动执行、fake skill sandbox、service factory 和部分 P/S/M smoke 仍是 mock-first。
- External projects/agents 默认 registry/data-only，不会自动安装或执行。
- Project Brain compaction 不是语义向量数据库或自动知识图谱。
- Web UI 无 TLS、RBAC 或多租户，不可公开部署。
- 不包含自动平台发布、自动收款、完整 CRM 或 Revenue OS。
- Commercial projects、私有作品、credentials 不进入公开 GitHub。

## 16. 关键源码、配置与扩展阅读

### 核心运行时

- [`../agent_runtime/run_task.py`](../agent_runtime/run_task.py)：顶层 CLI 与命令注册。
- [`../agent_runtime/pipeline_runner.py`](../agent_runtime/pipeline_runner.py)：pipeline、checkpoint、resume。
- [`../agent_runtime/lifecycle_graph.py`](../agent_runtime/lifecycle_graph.py)：24 节点生命周期事实源。
- [`../agent_runtime/workflow_plan.py`](../agent_runtime/workflow_plan.py)：当前任务 workflow 组装。
- [`../agent_runtime/model_capacity.py`](../agent_runtime/model_capacity.py)：池、breaker、canary、多跳 fallback。
- [`../agent_runtime/observation_contract.py`](../agent_runtime/observation_contract.py)：Agy 多模态输入与证据合同。
- [`../agent_runtime/media_backend_adapter.py`](../agent_runtime/media_backend_adapter.py)：Grok/xAI 媒体 adapter、preflight 与执行。
- [`../agent_runtime/protocols/artifact_task.py`](../agent_runtime/protocols/artifact_task.py)：ArtifactTask 解析、隔离和路由。
- [`../agent_runtime/visual_acceptance.py`](../agent_runtime/visual_acceptance.py)：视觉候选验收。
- [`../agent_runtime/narrative_delivery.py`](../agent_runtime/narrative_delivery.py)：章节候选交付与连续性产物。
- [`../agent_runtime/narrative_eval.py`](../agent_runtime/narrative_eval.py)：L0–L3 长篇验收。
- [`../agent_runtime/repository_handoff.py`](../agent_runtime/repository_handoff.py)：安全仓库记忆。

### 关键配置

- [`../config/agent_registry.yml`](../config/agent_registry.yml)：14 角色职责。
- [`../config/agent_role_bindings.yml`](../config/agent_role_bindings.yml)：角色/worker 双向边界。
- [`../config/agent_model_profiles.yml`](../config/agent_model_profiles.yml)：模型模式与档位。
- [`../config/worker_invocation_contracts.yml`](../config/worker_invocation_contracts.yml)：精确 CLI 合同。
- [`../config/model_catalog.yml`](../config/model_catalog.yml)：模型能力事实。
- [`../config/model_providers.yml`](../config/model_providers.yml)：provider 事实。
- [`../config/model_capacity.yml`](../config/model_capacity.yml)：容量与 fallback。
- [`../config/model_pricing.yml`](../config/model_pricing.yml)：数字价格唯一事实源。
- [`../config/artifact_task_policy.yml`](../config/artifact_task_policy.yml)：ArtifactTask 路由与格式。
- [`../config/media_generation_backends.yml`](../config/media_generation_backends.yml)：媒体后端目录与执行边界。
- [`../config/visual_acceptance.yml`](../config/visual_acceptance.yml)：视觉验收与独立性规则。
- [`../config/production_packs.yml`](../config/production_packs.yml)：七类生产包。
- [`../config/protocol_enforcement.yml`](../config/protocol_enforcement.yml)：协议强制规则。
- [`../config/approval_policy.yml`](../config/approval_policy.yml)：审批边界。

### 协议与运行说明

- [`../OPERATING_MODEL.md`](../OPERATING_MODEL.md)：角色、预算、执行和验收总规则。
- [`WORKSPACE_ENTRY_PROTOCOL.md`](WORKSPACE_ENTRY_PROTOCOL.md)：仓库入口包。
- [`FRONTDESK_PROTOCOL.md`](FRONTDESK_PROTOCOL.md)：前台边界。
- [`ROLE_SESSION_PROTOCOL.md`](ROLE_SESSION_PROTOCOL.md)：角色会话。
- [`ARTIFACT_PRODUCER_PROTOCOL.md`](ARTIFACT_PRODUCER_PROTOCOL.md)：ArtifactProducer。
- [`PROTOCOL_ENFORCEMENT.md`](PROTOCOL_ENFORCEMENT.md)：运行时强制说明。
- [`../PROJECT_HANDOFF.md`](../PROJECT_HANDOFF.md)：当前仓库状态与验证记录。
- [`README.zh-CN.md`](README.zh-CN.md)：中文项目总览与路线图。

本文是 GitHub 的“当前版本能力索引”，不是替代配置的第二事实源。出现差异时，以列出的权威配置、运行时验证和当前 Git 提交为准。
