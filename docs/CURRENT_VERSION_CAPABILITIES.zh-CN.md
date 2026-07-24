# AgentLab 当前能力手册

语言：[English](CURRENT_VERSION_CAPABILITIES.en-US.md) | [中文](CURRENT_VERSION_CAPABILITIES.zh-CN.md)

本文按权威来源说明能力，不复制易漂移的模型表、provider 额度、完整命令清单、
测试计数或验收状态。

## 系统定位

AgentLab 是本地优先、可审计的生产运行时。它把用户请求编译成 mission contract，
选择最小安全路线和 production pack，解析每个角色的执行壳/模型，记录可恢复状态与
证据，并把候选生成和正式晋升严格分开。

当前验收状态只看：
`acceptance_runs/agentlab_capability_acceptance/current.yml`。本文列出的是已定义的
能力合同，不代表所有可选 live provider 此刻都有认证或额度。

## 权威层

| 关注点 | 权威来源 |
|---|---|
| 角色与 active prompt | `config/agent_registry.yml` |
| 路线 | `config/routing_rules.yml` |
| 领域生产包与质量门 | `config/production_packs.yml` |
| 工作流 driver | `config/execution_modes.yml` |
| 角色壳/模型矩阵 | `config/agent_model_profiles.yml` |
| 壳命令合同 | `config/worker_invocation_contracts.yml` |
| 模型/provider 事实 | `config/model_catalog.yml`, `config/model_providers.yml` |
| 容量 fallback | `config/model_capacity.yml` |
| 状态机 | run-local 状态文件、`lifecycle_graph.py`、`task_index.py` |
| 产物晋升 | `project_artifact_steward.py` 与项目 artifact index |

当前命令以 `./agentlab.sh --help` 及二级 `--help` 为准。当前角色分配用
`./agentlab.sh models show --role <Role>` 查询，不在手册中维护第二份表。

额度探针、自动 fallback/reset canary 的真实边界，以及后端模型提案/跨档位更新
接口见
[`MODEL_CAPACITY_AND_UPDATE_GOVERNANCE.zh-CN.md`](MODEL_CAPACITY_AND_UPDATE_GOVERNANCE.zh-CN.md)。

## Mission、路线与角色

- Mission 编译器归一化意图、领域、体量、风险、边界和证据要求。
- 路由器只选择当前任务真正需要的角色。
- Production pack 定义领域生命周期节点、必要产物、记忆和质量门。
- Workflow plan 按 active mode/tier 解析每个角色的 worker、model 和命令合同。
- AgentLab 始终是工作流宿主；CLI 壳只是可替换 worker。
- 壳可在单个已分配角色内使用自身 subagents，但必须收回该角色 receipt。
- 跨角色壳合并和单壳 full-driver 已退役。

角色注册表覆盖规划、仓库/接口发现、研究、观察、编码、通用/媒体生产、小说规划与
写作、审查/记录、测试、验证和归档晋升。准确角色集合以注册表为准。

## 生产能力

### 代码

从窄修复到大型高风险工程，路线按需加入仓库扫描、接口分析、研究、实现、测试、
验证和归档。源码编辑始终受 scope 与证据约束。

### 长篇小说

- 轻单章路线产出候选正文、连续性状态、状态变化提案和交付回执。
- 有界多章路线维护章节顺序与批次连续性证据。
- Heavy audit 审计已有候选，产出 review、continuity failure 和 rewrite proposal，
  不静默修改正式正文。
- Rewrite planning、正文写作和 promotion 是三个不同阶段。

Fact snapshot、artifact index、chapter packet、ledger 和 state proposal 是长篇事实
权威。当前不依赖 RAG；未来检索层也不能替代结构化事实源。

### 文章与通用产物

普通短文走 article light。文档、数据、演示、图片、视频等通用产物通过声明式
candidate 合同和格式结构检查交付，不继承代码或小说的整条治理链。

### 媒体与只读观察

图像/视频任务包含媒体合同、后端 preflight、生成台账、资产 hash、独立观察/审查和
结构验证。Producer 不能验收自己。Observer 可精读指定长文本、文档、图像、视频或
音频，但没有生产和晋升权。

## 状态、后台与恢复

任务可从 `projects/<Project>/runs/<task_id>/` 独立恢复：

- `mission_contract.yml`, `workflow_plan.yml`
- `state.yml`, `lifecycle.yml`, `progress.yml`
- `task_events.jsonl`, decision cards
- 各角色报告、输出合同和 receipts

Web UI、TUI、daemon、watchdog 和新会话从这些文件投影状态，不依赖旧聊天。
Watchdog 识别 stale/actionable 状态；daemon 写本地 heartbeat/status，并按配置发送
通知。长篇 background controller 是专用批次控制器，不是绕过通用治理的快捷方式。

## 产物、记忆与技能

- 候选：`runs/<task_id>/artifacts/`
- 正式：`production/`
- 被替换正式版本：`archive/`

正式晋升需要 lineage、声明路径、独立审查/审批、旧版归档回执和 artifact index
更新。`PROJECT_HANDOFF.md` 是唯一可写仓库交接。Active skill 是跟踪包，usage
ledger 属于具体 run。新 skill、role、pack 或 bridge 先提案、验证、审批，再激活。

## 模型、容量与成本

路由选择和模型选择相互独立。OAuth/订阅、API 和特殊 worker 分别登记能力、认证、
usage 与计费事实。壳提供 status/usage 时记录已观察余量和刷新时间；看不到就保持
unknown。

只有声明过的同角色 capacity route 可以 fallback；未声明故障直接停止并报告。
OAuth 调用不能按公开 API 单价伪装成 API 账单。成本账本区分真实 usage、估算价格、
媒体单位计费和未知成本。

## 操作界面

- `agentlab.sh`：权威本地 CLI 包装。
- TUI/Web UI：同一 runtime state 的任务、状态和决策投影。
- MCP/role session：有界集成面，不是第二套权威。
- Repository handoff/workspace entry：最小安全发现入口。
- TrueNAS/GitHub：显式交付或备份，不暗中复制运行状态。

Web UI 的模型信息来自 workflow plan 和权威配置，不维护浏览器本地模型路由器。

## 安全边界与限制

- 不隐式发起 provider 调用、私有上下文外发、production 写入、promotion、fallback
  或外部发布。
- 凭据和 CLI home 只留本地，不进入仓库 ingestion。
- Candidate 完成不是 production 验收。
- Dry-run/静态合同证据不是 live provider 证据。
- Generated acceptance 是证据快照，不是运行策略。
- 自进化可改进 AgentLab 组件，但不能自行扩展产品范围、创建凭据或授予 production
  权限。

## 验证

```bash
./agentlab.sh model-doctor
./agentlab.sh protocol-doctor
./agentlab.sh repo-hygiene-check --root .
python3 -m pytest -q <focused tests>
```

共享 runtime 改动交付前运行一次完整测试。测试治理见
`docs/TEST_SUITE_GOVERNANCE.md`。

剪枝前快照保存在 `docs/archive/current_capabilities_legacy_20260718/`。
