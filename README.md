# AgentLab / 智能体实验室

[English](docs/README.en-US.md) | [中文](docs/README.zh-CN.md) |
[Capability reference](docs/CURRENT_VERSION_CAPABILITIES.en-US.md) |
[能力手册](docs/CURRENT_VERSION_CAPABILITIES.zh-CN.md) |
[Project Agents + Canonical Truth](docs/PROJECT_AGENTS_AND_TRUTH.md)

AgentLab is a local-first governed production runtime for code, longform text,
articles, typed artifacts, and media workflows. It owns task planning, role
routing, durable state, evidence, review gates, and promotion. Local AI CLIs are
replaceable workers, not the workflow host.

AgentLab 是本地优先、可审计的生产运行时，支持代码、长篇文本、普通文章、结构化
产物和媒体工作流。系统负责计划、角色路由、持久状态、证据、质量门和晋升；本地
AI CLI 是可替换 worker，不是工作流宿主。

## Core Flow / 核心流程

```text
request
  -> mission contract
  -> smallest safe route + production pack
  -> workflow plan with resolved role profiles
  -> role execution and deterministic checks
  -> receipts, events, decisions, and candidate artifacts
  -> explicit review/approval/promotion when required
```

Configuration authorities / 配置权威：

- `config/agent_registry.yml`: roles and active templates / 角色与 active prompt
- `config/routing_rules.yml`: route membership / 路线成员
- `config/production_packs.yml`: domain lifecycle and gates / 领域生命周期与门禁
- `config/execution_modes.yml`: AgentLab workflow driver
- `config/agent_model_profiles.yml`: per-role worker/model / 角色壳与模型
- `config/worker_invocation_contracts.yml`: shell commands / 壳命令
- `config/model_capacity.yml`: declared fallback / 已声明 fallback
- `config/task_runtime_v2.yml`: Task/Job/WorkItem/Attempt identity and evidence policy

Route profiles / 路由配置: code factory routes (`small_task`, `medium_task`, `interface_sensitive_task`, `research_sensitive_task`, `large_or_risky_task`) plus governed production-pack routes such as `narrative_light_chapter`, `narrative_batch_chapters`, `narrative_heavy_audit`, `article_light_draft`, and `media_generation_task`.

## Quick Start / 快速开始

```bash
# Bootstrap once after cloning / 克隆后先完成可复现安装
./agentlab.sh bootstrap

# Read-only orientation / 只读检查
./agentlab.sh repository-handoff --repo .
./agentlab.sh model-doctor
./agentlab.sh protocol-doctor

# Route preview / 路由预览
./agentlab.sh route-probe "Implement a small CLI fix with tests"

# Create and prepare / 创建与准备
./agentlab.sh task create --project AgentLab --task-id task_0001 \
  --title "Implement one CLI fix" --goal "Implement a small CLI fix with tests" \
  --idempotency-key request-0001

# Legacy compatibility during Runtime v2 migration
./agentlab.sh init-task --project AgentLab --task-id task_0001 \
  --request-text "Implement a small CLI fix with tests"
./agentlab.sh prepare --project AgentLab --task-id task_0001 --write-plan

# Execute only after approval / 仅在授权后执行
./agentlab.sh run-pipeline --project AgentLab --task-id task_0001 --execute
```

The supported Python versions are 3.11-3.13. `bootstrap` creates `.venv` and
installs the hash-locked dependency set from `requirements.lock`; it does not
require Provider credentials. If dependencies are missing, other commands stop
with an actionable bootstrap message instead of a Python traceback.

支持 Python 3.11-3.13。`bootstrap` 会创建 `.venv` 并从
`requirements.lock` 安装带哈希的锁定依赖，不需要任何模型密钥。依赖缺失时，
其他命令会给出明确的自举提示，而不是直接输出 Python 堆栈。

Use `./agentlab.sh --help` and nested `--help` for the current command inventory.
Do not rely on a copied command count or model table.

## Artifact Boundary / 产物边界

```text
projects/<Project>/runtime/tasks/<task_id>/    v2 event ledger, projections, evidence
projects/<Project>/runs/<task_id>/             legacy staged-migration compatibility
projects/<Project>/production/                 promoted current deliverables
projects/<Project>/archive/                    superseded formal deliverables
projects/<Project>/project_truth.yml           enforced canonical truth pointer
projects/<Project>/.agentlab/truth/            immutable truth history
```

Candidate completion never implies production promotion. Longform facts remain
structured in fact snapshots, artifact indexes, packets, ledgers, and state
proposals. Retrieval can provide evidence but does not replace that authority.
When `project_truth_mode: enforced`, those files become projections or evidence;
the canonical snapshot is the sole live authority.

候选完成不等于正式晋升。长篇事实继续由 fact snapshot、artifact index、packet、
ledger 和 state proposal 维护；检索只能提供证据，不能替代事实源。

## State And Recovery / 状态与恢复

New Tasks use one hash-chained `events.jsonl` authority and rebuildable Task,
Job, WorkItem, Attempt, artifact, evidence, progress, and handoff projections.
Legacy runs remain dual-read during migration, while all Runtime v2 writes stay
under `runtime/tasks/`. See `docs/TASK_RUNTIME_V2.md`.

每个 run 都有可恢复计划、状态、生命周期、事件、决策和 receipts。后台或新会话从
这些文件查询进度，不需要持续占用一个前台对话盯任务。

## Role And Worker Boundary / 角色与壳边界

- AgentLab roles are stable responsibility contracts.
- Hermes, Claude Code, Codex, Agy, Grok, Qwen, and other registered CLIs are
  workers selected by configuration.
- A shell may use native subagents within one assigned role, then return the
  declared receipt.
- Cross-role shell coalescing and full-driver emulation are disabled.
- Provider/model fallback is allowed only through a declared capacity route.

准确角色、壳、模型和 fallback 必须实时读取配置，README 不维护第二份矩阵。

## Skills / 技能

External skills are staging candidates until validated and approved. A canonical
smoke source used by the opt-in live importer test is:

`https://raw.githubusercontent.com/anthropics/skills/main/skills/skill-creator/SKILL.md`

```bash
./agentlab.sh skill-import-url <url>
```

Default tests do not fetch this URL or call a live model.

## Safety / 安全

- Local-first and approval-gated by default.
- No implicit live provider calls, private-context export, fallback, production
  write, promotion, public posting, or credential sync.
- CLI homes and secrets are local-only and excluded from repository ingestion.
- Do not expose AgentLab directly to the public internet.
- Generated acceptance reports are evidence snapshots, not runtime policy.

当前验收状态见
`acceptance_runs/agentlab_capability_acceptance/current.yml`，测试治理见
`docs/TEST_SUITE_GOVERNANCE.md`，完整运行模型见 `OPERATING_MODEL.md`。

The pre-pruning README is archived at
`docs/archive/root_agent_guides_legacy_20260718/README_PRE_PRUNING.md`.
