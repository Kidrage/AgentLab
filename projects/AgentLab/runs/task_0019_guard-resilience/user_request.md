# AgentLab Resilience & Knowledge Guard v1.0

> 目标：让 AgentLab 在本地电脑宕机、模型中断、任务跑到一半、资料重复调研、项目目录混乱、备份失败等情况下，仍然能恢复、续跑、追溯、复用。
>
> 核心原则：**恢复能力优先于智能能力；备份优先级高于自动执行；本地状态文件高于聊天记忆；研究报告必须可复用、可索引、可过期、可被更强模型接管。**

---

## 0. 当前 AgentLab 的已具备能力与缺口

### 已具备能力

当前 AgentLab 已经有比较好的基础：

- `projects/<ProjectName>/agent_docs/`：长期项目记忆。
- `projects/<ProjectName>/runs/<task_id>/`：单任务运行记录。
- `state.yml`：任务状态。
- `workflow_plan.yml`：路由、预算、验证门禁。
- `research_notes.md`：任务级研究记录。
- `brain_decisions.yml`：大脑层决策。
- `config/backup_policy.yml`、`github_policy.yml`、`version_policy.yml`：备份、GitHub、回滚策略雏形。

### 核心缺口

现在的问题不是“没有文件”，而是缺少真正的保护机制：

1. `state.yml` 直接写入，没有原子写入、文件锁、心跳、事务日志。电脑宕机时可能出现半写入状态。
2. `version_policy.yml` 里定义了 checkpoint/rollback，但 CLI/runtime 里没有完整实现 checkpoint、recover、rollback 命令。
3. `backup_policy.yml` 有 TrueNAS/GitHub 规划，但 backup 不是任务状态机的一等公民，失败也不会阻塞高风险任务。
4. `research_notes.md` 只属于单次任务，不会自动沉淀成项目级研究库，导致不同模型接入时可能重复调研。
5. 项目目录虽然规定为 `projects/<ProjectName>/`，但缺少全局项目注册表、备份优先级、恢复入口。
6. Coder 阶段缺少“任务分支 + patch + checkpoint”强制保护，容易中途改坏而没有回档。

---

## 1. 新增总机制：AgentLab Guard

新增一个系统层模块：**AgentLab Guard**。

它不是一个新 Agent，而是运行时保护层，包住所有 CLI、Agent、Coder、Researcher、Archivist 操作。

### 1.1 Guard 的职责

AgentLab Guard 负责：

- 原子写入：所有关键文件通过 temp file + fsync + atomic rename 写入。
- 文件锁：同一个 project/task 同时只能有一个写入者。
- 心跳：长任务执行期间每 10–30 秒更新 heartbeat。
- 崩溃恢复：重启后扫描 stale lock 与 incomplete transaction。
- checkpoint：任务启动前、Coder 写代码前、验证通过后、归档完成后自动快照。
- research vault：所有调研报告进入项目级知识库，后续任务先检索再决定是否重新调研。
- backup gate：高优先级文件未备份时，阻止进入高风险 Coder/rollback 阶段。
- manifest：每个项目、任务、研究报告、备份快照都有可机器读取的索引。

---

## 2. 目录结构重构

### 2.1 全局结构

```text
AgentLab/
├── AGENTS.md
├── config/
│   ├── backup_policy.yml
│   ├── memory_policy.yml
│   ├── version_policy.yml
│   ├── resilience_policy.yml        # 新增：崩溃恢复、锁、事务、心跳策略
│   └── research_policy.yml          # 新增：调研复用、过期、索引策略
├── agent_runtime/
│   ├── atomic_io.py                 # 新增：原子写入与锁
│   ├── checkpoint_manager.py        # 新增：checkpoint/rollback/recover
│   ├── backup_manager.py            # 新增：本地/NAS/GitHub 备份执行
│   ├── research_vault.py            # 新增：项目级调研库
│   ├── guard.py                     # 新增：统一保护入口
│   └── run_task.py                  # 修改：所有命令接入 Guard
├── projects/
│   ├── PROJECT_REGISTRY.yml         # 新增：全局项目索引
│   └── <ProjectName>/
│       ├── project_config.yml
│       ├── agent_docs/
│       ├── runs/
│       ├── research/                # 新增：项目级调研知识库
│       ├── manifests/               # 新增：项目/任务/备份清单
│       └── repo/                    # 可选：项目源码镜像或子模块
└── .agentlab_runtime/               # git-ignored
    ├── locks/
    ├── transactions/
    ├── heartbeats/
    ├── checkpoints/
    ├── recovery/
    └── backup_queue/
```

### 2.2 项目目录标准

每个项目必须是 `projects/<ProjectName>/` 下的顶级兄弟目录，不允许把新项目嵌在已有项目或某个 task 下面。

```text
projects/<ProjectName>/
├── project_config.yml
├── agent_docs/
│   ├── 00_CONTEXT_PACK.md
│   ├── 01_REPO_MAP.md
│   ├── 02_TASK_LEDGER.yml
│   ├── 03_DECISION_LOG.md
│   ├── 04_INTERFACE_REGISTRY.md
│   ├── 05_CHANGELOG_AGENT.md
│   ├── 06_RISK_REGISTER.md
│   ├── 07_DEVELOPMENT_LOG.md
│   ├── 08_CODEX_DIALOGUE_LOG.md
│   ├── 09_COST_LEDGER.yml
│   └── 10_SYNC_LEDGER.yml
├── runs/
│   └── task_0001_slug/
├── research/
│   ├── index.yml
│   ├── topic_cards/
│   ├── reports/
│   ├── source_cache/
│   ├── update_proposals/
│   └── README.md
├── manifests/
│   ├── project_manifest.yml
│   ├── backup_manifest.yml
│   ├── checkpoint_manifest.yml
│   └── research_manifest.yml
└── repo/
```

---

## 3. 任务级崩溃恢复机制

### 3.1 状态机

将 `state.yml` 扩展为强状态机：

```yaml
project: AgentLab
task_id: task_0021_resilience-guard
status: running_agent
phase: Researcher
current_agent: Researcher
started_at: "2026-05-31T...Z"
updated_at: "2026-05-31T...Z"
last_heartbeat_at: "2026-05-31T...Z"
last_safe_checkpoint: ckpt_20260531_153012_task_0021_pre_researcher
active_transaction: tx_20260531_153020_researcher
completed_agents:
  - Supervisor
  - RepoScout
reports:
  Supervisor: supervisor_plan.md
  RepoScout: reposcout_report.md
recovery:
  resume_strategy: resume_from_last_completed_agent
  interrupted_agent: Researcher
  partial_outputs:
    - .agentlab_runtime/transactions/tx_.../partial_output.md
```

### 3.2 每次命令执行流程

任何 `run-agent`、`log-event`、`prepare`、`checkpoint`、`backup-run` 都必须经过以下流程：

```text
1. acquire_lock(project, task_id)
2. create_transaction(tx_id)
3. update_state(status=running_agent, current_agent=...)
4. create_checkpoint_if_needed()
5. execute_command_or_agent()
6. write_outputs_to_temp()
7. fsync temp + atomic rename
8. validate_expected_outputs()
9. update_state(completed/blocked/failed_recoverable)
10. enqueue_backup_if_priority_requires()
11. release_lock()
```

### 3.3 宕机后的恢复扫描

新增命令：

```bash
./agentlab.sh recover --scan
./agentlab.sh recover --project AgentLab --task-id task_0021 --preview
./agentlab.sh recover --project AgentLab --task-id task_0021 --from latest-safe-checkpoint --confirm
```

扫描逻辑：

```text
如果发现 lock 存在但 heartbeat 超过 timeout：
  → 标记为 stale_lock
  → 读取 active_transaction
  → 检查 partial outputs
  → 将 state.yml 标记为 failed_recoverable
  → 写 RECOVERY_REQUIRED.md
  → 提供三个选项：
       A. resume：从 last completed agent 继续
       B. retry：重跑 interrupted agent
       C. rollback：回到 last safe checkpoint
```

### 3.4 写入保护

`state.yml`、`workflow_plan.yml`、`brain_decisions.yml`、`cost_ledger.yml`、`research/index.yml`、`backup_manifest.yml` 必须使用原子写入。

新增 `agent_runtime/atomic_io.py`：

```python
from pathlib import Path
import os
import tempfile


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
```

---

## 4. Checkpoint / Rollback 机制

### 4.1 Checkpoint 触发点

必须自动创建 checkpoint：

- `on_task_start`：任务初始化后。
- `before_agent_execute`：每个 Agent 执行前。
- `before_coder_edit`：Coder 改源码前，最高优先级。
- `after_coder_complete`：Coder 写完 implementation_report 后。
- `after_validator_pass`：验证通过后。
- `after_archivist_complete`：归档完成后。
- `manual`：用户手动触发。

### 4.2 Checkpoint 存放方式

```text
.agentlab_runtime/checkpoints/
└── <ProjectName>/
    └── <task_id>/
        ├── ckpt_20260531_153012_pre_coder/
        │   ├── manifest.yml
        │   ├── agent_docs.tar.zst
        │   ├── runs_task.tar.zst
        │   ├── config.tar.zst
        │   ├── git_status.txt
        │   ├── git_diff.patch
        │   └── source_tree_manifest.yml
        └── latest -> ckpt_...
```

### 4.3 Coder 阶段必须使用任务分支或 patch

L2/L3 任务不能直接在 `main` 上无保护修改。

推荐规则：

```text
L1 小改动：允许直接修改，但必须有 pre-coder checkpoint。
L2 标准任务：创建 task branch：agentlab/<ProjectName>/<task_id>。
L3 重型任务：必须 task branch + patch 文件 + validation gate。
```

每次 Coder 完成后，必须写：

```text
runs/<task_id>/implementation_report.md
runs/<task_id>/diffs/coder_changes.patch
runs/<task_id>/commands/commands_run.log
runs/<task_id>/validation_report.md
```

---

## 5. 项目级调研知识库 Research Vault

### 5.1 为什么需要 Research Vault

`runs/<task_id>/research_notes.md` 只能记录一次任务的研究结果，不适合长期复用。

新的规则：**所有调研必须沉淀到项目级 `research/`，后续模型先查 research vault，再决定是否需要重新调研。**

### 5.2 目录结构

```text
projects/<ProjectName>/research/
├── index.yml
├── topic_cards/
│   └── model-routing-price-and-provider.md
├── reports/
│   └── 2026/
│       └── 05/
│           └── 2026-05-31_model-routing-price-survey.md
├── source_cache/
│   └── <source_hash>.yml
├── update_proposals/
│   └── 2026-05-31_research-update-proposal.md
└── README.md
```

### 5.3 `research/index.yml` 标准格式

```yaml
version: 1
project: AgentLab
updated_at: "2026-05-31T...Z"
topics:
  model-routing-price-and-provider:
    title: "Model routing, pricing, provider selection"
    aliases:
      - "模型分层"
      - "coder model 性价比"
      - "DeepSeek vs Qwen"
    status: active
    freshness_class: volatile
    stale_after_days: 14
    last_reviewed_at: "2026-05-31T...Z"
    canonical_report: research/reports/2026/05/2026-05-31_model-routing-price-survey.md
    topic_card: research/topic_cards/model-routing-price-and-provider.md
    source_count: 8
    confidence: medium
    next_review_trigger:
      - "用户问最新价格"
      - "模型 API 命名变化"
      - "provider route 改动"
    reusable_summary: >
      当前 AgentLab 模型路由应区分 brain/perception/coder/audit/archive，
      provider 价格必须按 DeepSeek official、DashScope、OpenRouter 分开记录。
    open_questions:
      - "是否需要为国内环境单独设置 DashScope CN provider profile?"
```

### 5.4 topic card 格式

每个研究主题必须有一张 `topic_card`，作为后续模型快速读取的压缩版。

```markdown
# Topic Card: Model Routing / Pricing / Provider Strategy

## Current conclusion
- ...

## What has already been researched
- ...

## Source quality
- Official docs checked: yes/no
- Third-party registry checked: yes/no
- Date-sensitive: yes/no

## Reuse rules
- Reuse this card if the user asks about stable architecture decisions.
- Re-browse if the user asks about latest pricing, current model name, or API availability.

## Do not repeat
- Do not re-compare all models from scratch unless pricing changed.
- Do not mix OpenRouter pricing with DashScope pricing.

## Next better-model instruction
If a stronger model takes over, first verify provider names and pricing, then revise routing policy.
```

### 5.5 Researcher 执行前必须先查库

Researcher 的执行流程改为：

```text
1. parse user request → topic candidates
2. query research/index.yml
3. read matching topic_card
4. decide:
   A. reuse existing research
   B. update existing research
   C. create new research topic
5. only browse externally if:
   - topic missing
   - stale_after expired
   - user asks latest/current
   - source confidence low
   - stronger model explicitly requests revised research plan
6. write research_notes.md for current task
7. update research vault after validation
```

---

## 6. Backup 优先级体系

### 6.1 备份分级

备份优先级最高。所有 AgentLab 改动必须分级：

| Priority | 内容 | 触发策略 | 失败处理 |
|---|---|---|---|
| P0 restore-critical | `config/`, `AGENTS.md`, `project_config.yml`, `agent_docs/`, `runs/*/state.yml`, `workflow_plan.yml`, `brain_decisions.yml`, `research/index.yml`, `manifests/` | 每次写入后立即入队备份 | 失败则阻止高风险继续执行 |
| P1 active source | 活跃项目源码、patch、diff、验证报告 | Coder 前后备份 | 失败则要求用户确认继续 |
| P2 research archive | 完整调研报告、source cache、topic cards | Researcher/Archivist 完成后备份 | 失败写入 warning，不阻塞 L1 |
| P3 disposable logs | 临时输出、debug cache、模型 raw output | 定时或手动 | 可丢弃 |

### 6.2 三层备份目标

```text
Local checkpoint  →  TrueNAS mirror/snapshot  →  GitHub private remote
```

- 本地 checkpoint：最快恢复。
- TrueNAS：防本地电脑宕机、硬盘损坏。
- GitHub private：防 NAS/本地同时不可用，保留远端历史。

### 6.3 不建议继续用纯 cp -n 当唯一备份方式

`cp -n` 的好处是不会覆盖远端文件，但坏处是：同名文件更新后不会被备份到远端，远端可能永远停留在旧版。

更合理的方式：

```text
immutable snapshots + mutable manifest
```

也就是说：

- 数据快照永远新建，不覆盖。
- `backup_manifest.yml` 记录哪个 snapshot 是 latest。
- 恢复时按 manifest 选版本。
- 不删除旧快照，按 retention 策略清理。

### 6.4 Backup manifest

```yaml
version: 1
project: AgentLab
updated_at: "2026-05-31T...Z"
latest_successful_backup:
  local: ckpt_20260531_153012
  truenas: nas_20260531_153020
  github: commit_sha_or_branch
backup_health:
  local: ok
  truenas: warning
  github: ok
last_error:
  target: truenas
  at: "2026-05-31T...Z"
  message: "mount not available"
queue:
  - item: projects/AgentLab/runs/task_0021/state.yml
    priority: P0
    status: pending_retry
```

---

## 7. Recovery Playbook

### 7.1 电脑宕机后

用户重新打开电脑后运行：

```bash
./agentlab.sh guard-status
./agentlab.sh recover --scan
```

如果发现中断任务：

```bash
./agentlab.sh recover --project AgentLab --task-id task_0021 --preview
```

输出应显示：

```text
Interrupted task: task_0021
Last completed agent: RepoScout
Interrupted agent: Researcher
Last safe checkpoint: ckpt_20260531_153012_pre_researcher
Partial output found: yes
Recommended action: retry Researcher from last safe checkpoint
```

然后：

```bash
./agentlab.sh recover --project AgentLab --task-id task_0021 --retry-agent Researcher --confirm
```

### 7.2 代码改坏后

```bash
./agentlab.sh rollback --project AgentLab --task-id task_0021 --scope source --preview
./agentlab.sh rollback --project AgentLab --task-id task_0021 --scope source --checkpoint ckpt_... --confirm
```

### 7.3 调研重复/方向漂移后

```bash
./agentlab.sh research-query --project AgentLab --topic "model routing pricing"
./agentlab.sh research-update-proposal --project AgentLab --topic model-routing-price-and-provider
```

强模型接管时，必须先读：

```text
projects/<ProjectName>/research/index.yml
projects/<ProjectName>/research/topic_cards/<topic>.md
projects/<ProjectName>/agent_docs/00_CONTEXT_PACK.md
projects/<ProjectName>/agent_docs/03_DECISION_LOG.md
```

---

## 8. CLI 新增命令

```bash
# Guard / health
./agentlab.sh guard-status
./agentlab.sh recover --scan
./agentlab.sh recover --project <Project> --task-id <task_id> --preview
./agentlab.sh recover --project <Project> --task-id <task_id> --confirm

# Checkpoint / rollback
./agentlab.sh checkpoint --project <Project> --task-id <task_id> --scope task --reason "before coder edit"
./agentlab.sh rollback --project <Project> --task-id <task_id> --list
./agentlab.sh rollback --project <Project> --task-id <task_id> --preview <checkpoint_id>
./agentlab.sh rollback --project <Project> --task-id <task_id> --checkpoint <checkpoint_id> --confirm

# Research vault
./agentlab.sh research-query --project <Project> --topic "..."
./agentlab.sh research-add --project <Project> --task-id <task_id> --from research_notes.md
./agentlab.sh research-card --project <Project> --topic-id <topic_id>
./agentlab.sh research-update-proposal --project <Project> --topic-id <topic_id>

# Backup
./agentlab.sh backup-status --project <Project>
./agentlab.sh backup-run --project <Project> --priority P0 --target local
./agentlab.sh backup-run --project <Project> --priority P0 --target truenas
./agentlab.sh backup-run --project <Project> --priority P0 --target github
./agentlab.sh backup-queue --project <Project>
```

---

## 9. Codex 实施顺序

### Phase A：最小保命闭环

1. 新增 `agent_runtime/atomic_io.py`。
2. 修改 `state_store.py`，所有 `write_text` 改成 `atomic_write_text`。
3. 新增 `.agentlab_runtime/locks/` 与 lock/heartbeat。
4. `run-agent` 执行前写 `current_agent` 与 heartbeat，完成后标记 completed。
5. 新增 `recover --scan`，识别 stale lock 与 failed_recoverable task。

### Phase B：Checkpoint / rollback

1. 新增 `checkpoint_manager.py`。
2. 实现 `checkpoint --scope task|project|config|source`。
3. 实现 `rollback --list/--preview/--confirm`。
4. Coder 阶段前强制 checkpoint。
5. 保存 `git_status.txt`、`git_diff.patch`、`manifest.yml`。

### Phase C：Research Vault

1. 新增 `projects/<Project>/research/` 初始化。
2. 新增 `research_vault.py`。
3. 实现 `research-query`、`research-add`、`research-card`。
4. Researcher agent prompt 加入“先查 Research Vault，再决定是否调研”。
5. Archivist 完成后将 validated `research_notes.md` 转成 topic card + report。

### Phase D：Backup Manager

1. 新增 `backup_manager.py`。
2. 实现 P0/P1/P2/P3 分级。
3. 实现 immutable snapshot + backup manifest。
4. 实现 TrueNAS/GitHub backup queue。
5. `guard-status` 显示 backup health。

---

## 10. 最终运行原则

1. **任何任务必须能回答：现在跑到哪一步？上一个安全点在哪？如果断电从哪里恢复？**
2. **任何模型接入必须先读项目记忆与 research vault，而不是只读聊天记录。**
3. **任何调研都必须进入项目级 research vault，否则视为一次性无效调研。**
4. **任何 Coder 改动前必须 checkpoint，L2/L3 必须 task branch 或 patch。**
5. **任何 P0 文件写入后必须进入 backup queue。**
6. **备份失败可以不打扰用户，但不能假装成功；P0 失败必须阻止高风险继续执行。**
7. **远端备份不要覆盖历史，用 immutable snapshots + manifest。**
8. **聊天不是事实源，本地 memory / state / manifest 才是事实源。**

---

## 11. 给 Codex 的实现提示词

请在当前 AgentLab 仓库中实现 “AgentLab Guard v1.0” 的最小闭环，不要一次性改太大。优先级如下：

1. 新增 `agent_runtime/atomic_io.py`，提供 `atomic_write_text()`、`atomic_write_yaml()`。
2. 修改 `agent_runtime/state_store.py`，把所有直接 `write_text()` 的关键状态写入改为原子写入。
3. 新增 `agent_runtime/guard.py`，实现 lock、heartbeat、transaction id、stale lock 检测。
4. 在 `run_task.py` 的 `run-agent`、`prepare`、`log-event` 中接入 Guard：命令开始 acquire lock，执行中更新 heartbeat，结束 release lock；异常时将 state 标记为 `failed_recoverable`。
5. 新增 `recover --scan` CLI 命令，扫描 `.agentlab_runtime/locks/` 和 task `state.yml`，生成 `RECOVERY_REQUIRED.md`。
6. 不要实现复杂云备份；只先写 backup queue 和 manifest 占位。
7. 所有新增行为必须不破坏现有 CLI；原有命令仍可运行。
8. 写 `implementation_report.md`，列出修改文件、运行命令、验证结果。
