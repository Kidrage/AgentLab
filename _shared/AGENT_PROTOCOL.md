# Agent Protocol — Shared Workspace Convention

> **权威版本位置**: `ssh truenas:/mnt/hdd2/AgentLab_WorkSpace/_shared/AGENT_PROTOCOL.md`
> 本文件是 4 个 agent CLI（Claude Code, Hermes, Codex, Agy）之间的**唯一共享协议**。
> 各 agent 的本地指令文件不得重复本文内容；只保留 agent 特有指令 + 指向本文的指针。

---

## 1. 工作原则：本地优先，truenas 为镜像

| 层级 | 位置 | 用途 |
|------|------|------|
| **Primary** | 本地磁盘 | 日常编码、运行、测试 |
| **Mirror** | `truenas:/mnt/hdd2/AgentLab_WorkSpace/` | 备份 + 跨 agent 共享读取 |

- 所有 agent **默认工作在本地**，不直接操作 truenas。
- 重要产出（项目记忆、会话摘要、导出文件）**推送到 truenas 对应命名空间**。
- 任何 agent 可以**只读访问**其他 agent 的 truenas 命名空间来获取上下文。
- 不要向 truenas 推送：`node_modules/`、`.venv/`、`__pycache__/`、构建产物、缓存、日志、二进制文件、密钥。

---

## 2. Agent 角色分工

| Agent | 定位 | 擅长的任务 |
|-------|------|-----------|
| **Claude Code** (`~/.claude/`) | 深度编码主力 | 复杂重构、深层代码分析、多文件架构变更、设计系统、Workflow 编排 |
| **Hermes** (`~/.hermes/`) | 系统协调员 | 系统级操作、跨工具协调、CLI 执行监控、全局记忆管理、MCP 网关 |
| **Codex** (`~/.codex/`) | 快速交付 | 快速代码片段、API 集成、仓库 onboarding、CI/CD 确认、PR 工作流 |
| **Agy** (`/usr/local/bin/agy`) | 轻量探索 | 极速探索、轻量任务、多模态处理、快速问答 |

---

## 3. 命名空间与所有权

```
truenas:/mnt/hdd2/AgentLab_WorkSpace/
├── _shared/                    # ← 本协议所在（所有 agent 共读）
│   └── AGENT_PROTOCOL.md
├── shared_protocols/           # 旧协议 → 指针指向本文件
│   ├── agent_states/           # Agent 状态文件（JSON）
│   └── locks/                  # 任务锁文件
├── agents/
│   ├── claude-code/            # Claude Code 独占写入
│   │   ├── projects/           #   项目记忆
│   │   ├── sessions/           #   会话产出
│   │   └── exports/            #   导出文件
│   ├── hermes/                 # Hermes 独占写入
│   ├── codex/                  # Codex 独占写入
│   └── agy/                    # Agy 独占写入
├── projects/                   # 共享项目文件（任意 agent 可写）
├── config/                     # AgentLab 配置
├── memory/                     # 共享记忆
└── ...
```

**规则：**
- 每个 agent **只写入自己的命名空间**（`agents/<name>/`）。
- 读取其他 agent 的命名空间时**只读**，不修改。
- `projects/` 和 `memory/` 为共享区，任何 agent 可写，但写入前检查其他 agent 的状态文件。
- `_shared/` 只有协议维护者（当前为 Claude Code）写入。

---

## 4. 状态发布与任务锁（本地优先 + 远程镜像同步）

为了确保本地开发的高效性（无需频繁通过 SSH 检查远程锁文件导致延迟），协同锁与状态发布采取**"本地读写，双向同步"**的机制。

### 4.1 锁与状态的目录结构
* **本地主路径**：`AgentLab/.agents/locks/` 和 `AgentLab/.agents/agent_states/`
* **远程镜像路径**：`truenas:shared_protocols/locks/` 和 `truenas:shared_protocols/agent_states/`

进行 `rsync` 备份和拉取时，这部分变更会在本地与远端镜像之间保持对齐。

### 4.2 状态发布
每个 agent 在开始执行任务前、或工作周期结束后，必须更新本地状态文件：
`AgentLab/.agents/agent_states/<agent_name>_state.json`

状态文件格式：
```json
{
  "agent": "claude-code",
  "updated": "2026-06-20T17:00:00Z",
  "current_task": "简短任务描述",
  "status": "in_progress | completed | blocked",
  "working_repo": "/path/to/repo",
  "branch": "feature/xxx",
  "notes": "额外说明"
}
```

### 4.3 任务锁（本地快速上锁）
避免多个 agent 在本地同时修改同一文件：
1. **检查锁**：开始大型任务前，先检查**本地** `.agents/locks/` 下是否有冲突锁。同时通过 `git status` 确认本地工作区没有其他 agent 未提交的残留修改。
2. **上锁**：在本地 `.agents/locks/` 创建 `<任务名>.lock` 文件（内容包含 agent 标识与时间戳），并立即执行一次 `rsync` 同步上传到 TrueNAS，以同步状态。
3. **解锁**：任务完成、代码提交并运行 `rsync` 备份后，在本地删除该 `.lock` 文件，并再次同步以在远程清理锁。
4. **锁超时**：如果锁文件存在且超过 24 小时未更新，视为过期锁，可进行清理。

### 4.4 去重与冲突预防
- 任何 agent 在执行大型重构或编辑共享文件（如 `projects/` 记忆）之前，必须先拉取最新状态，并在本地检查 `.agents/agent_states/` 以确保任务未被其他 agent 认领。
- 严禁在本地工作区有冲突锁的情况下，编辑同一组代码路径。

---

## 5. 同步约定

### 何时推送
- 完成一个任务后，将会话摘要推送到 `agents/<name>/sessions/`
- 项目记忆更新后，推送到 `agents/<name>/projects/`
- 需要共享给其他 agent 的产出，推送到 `agents/<name>/exports/`
- 状态变化时，更新 `shared_protocols/agent_states/<name>_state.json`

### 何时拉取
- 开始新任务前，检查其他 agent 的状态文件和命名空间是否有相关上下文
- 进入一个跨 agent 协作的项目时，读取其他 agent 的项目记忆

### 命名规范
- 会话文件: `YYYY-MM-DD_<简短描述>.md`
- 项目记忆: `<project-name>.md`
- 导出文件: `<project-name>/<描述>.md`

---

## 6. 共享规则（所有 agent 遵守）

### 6.1 Token 与仓库读取纪律
- 遵循第 10 节的完整 Token 效率策略（本节为摘要，详细方案见下方）
- 优先使用最廉价的导航方式（rg, git grep, git ls-files）
- 先读轻量级仓库地图（AGENTS.md, REPO_GUIDE.md）再深入
- 禁止全仓库扫描
- 不读 `.venv/`、`node_modules/`、`dist/`、`build/`、`coverage/`、`.git/`、`__pycache__/`、缓存、日志、lockfile、二进制文件

### 6.2 Git 纪律
- 不擅自 push，不 push 到 `main`
- 先检查 `git status -sb` 再编辑
- 保留无关的本地修改
- 不假设 CI 通过，必须验证或明确声明未验证

### 6.3 安全边界
- 不执行破坏性命令（`rm -rf`、force push、hard reset）除非显式要求
- 不暴露密钥、令牌、敏感路径
- 不假设仓库可以安全推送
- 遇到不确定，选最安全的最小动作

### 6.4 最小变更原则
- 做满足任务的最小正确变更
- 不重构无关代码
- 不重命名公共接口（除非要求）
- 不触碰无关格式化

### 6.5 验证标准
- 代码编辑不等于任务完成
- 必须运行相关测试/检查
- 失败要么修复，要么明确报告
- 产出最终报告：结论、仓库、分支、commit、变更文件、验证结果、剩余风险

---

## 7. Agent 特有指令位置

每个 agent 的**唯一本地指令文件**（只含该 agent 特有内容）：

| Agent | 本地文件 | 用途 |
|-------|----------|------|
| Claude Code | `~/.claude/CLAUDE.md` | Claude 特有工作流、skills、repo-scout |
| Hermes | `~/.hermes/SOUL.md` | 人格定义 + truenas 指针 |
| Codex | `~/.codex/AGENTS.md` | Codex 特有：onboarding 协议、`.codex/` 目录约定、codebase-memory-mcp |
| Agy | `~/.agy/AGENTS.md` | Agy 特有配置 |

**禁止事项：**
- ❌ 不得在两个 agent 的指令文件中写相同的规则
- ❌ 不得在本协议之外另立跨 agent 规则
- ❌ 不得绕过本协议直接修改其他 agent 的命名空间
- ❌ 不得在旧 `shared_protocols/AGENT_COORDINATION_PROTOCOL.md` 中添加内容（该文件已废弃，仅保留指针）

---

## 8. SSH 连接信息

```
Host:      truenas (10.147.17.61:2222)
User:      agentlab
Key:       ~/.ssh/agentlab_truenas (ED25519)
Workspace: /mnt/hdd2/AgentLab_WorkSpace
Disk:      11TB
```

SSH 配置位于 `~/.ssh/config`，所有 agent 共享使用。macOS LaunchAgent (`com.agentlab.truenas-keepalive`) 在开机时自动建立保活连接。

---

## 9. 协议更新流程

1. 修改本文件（`_shared/AGENT_PROTOCOL.md`）并推送到 truenas
2. 如需更新 agent 特有指令，只修改对应 agent 的本地文件
3. 在 commit message 中标注 `[protocol]` 前缀
4. 其他 agent 下次读取本协议时自动获得更新

---

## 10. Token 效率策略

> 核心原则：**逐级升级，每级需自证必要性。能用上层解决的绝不降到下层。**

### 10.1 分层上下文读取（Tiered Reading）

Agent 在获取任何信息时，必须从最便宜的层级开始，逐级升级：

| 层级 | 成本 | 操作 | 示例 |
|------|------|------|------|
| **L0** 文件索引 | ~10 tok | 列出文件名/路径 | `git ls-files \| head -N`, `ls <dir>` |
| **L1** 元数据 | ~50 tok | Git 历史、diff 统计、行数 | `git log --oneline -5`, `git diff --stat`, `wc -l` |
| **L2** 结构化搜索 | ~200 tok | 正则/符号搜索 | `rg -n <pattern>`, `git grep`, `search_graph`, `search_code` |
| **L3** 摘要/签名 | ~500 tok | 函数签名、类大纲 | `rg '^(func\|def\|class\|export)'`, `head -30`, `sed -n 'A,Bp'` |
| **L4** 精确范围 | ~1K tok | 指定行范围读取 | `Read(offset, limit)`, `sed -n '100,200p'` |
| **L5** 完整文件 | ~5K tok | 整个文件（最后手段） | `Read(file)` — 仅在前 4 级已定位目标后使用 |

**升级规则：**
1. 每级必须先穷尽本层手段，才能降级到下一层
2. 降级时必须在内部思考中说明理由（例如："L2 搜索结果 `fn()` 被 12 处调用，需要 L4 查看具体实现"）
3. 跨文件跳转时，从 L0/L1 重新开始，不直接跳到 L5
4. 已知文件无需重复读取——先检查 agent 已有上下文

**特例快速通道（允许跳过升级）：**
- 已缓存在对话上下文中的文件 → 直接引用
- 项目的 `AGENTS.md` / `REPO_GUIDE.md` → 直接 L4/L5（但仅限首次进入仓库时）
- 用户明确指定的文件路径 + 行号 → 直接 L4
- Agent 状态文件（`.agents/agent_states/`）→ 直接 L5（文件极小，<500 bytes）

### 10.2 仓库导航最小化（Minimal Repo Navigation）

进入任意 git 仓库的标准流程，禁止全量扫描：

```
Step 1 (L0+L1) — 快照采集（始终执行，~2秒）:
  git rev-parse --show-toplevel
  git status -sb
  git branch --show-current
  git remote -v
  git ls-files | wc -l              # 了解规模

Step 2 (L1) — 地图优先（查找已有导航文件）:
  检查: AGENTS.md, .codex/REPO_GUIDE.md, .codex/repo_files.txt,
        CLAUDE.md, README.md, docs/AI_REPO_GUIDE.md
  → 存在 → 直接 L4 读取该文件 → 获得仓库全景 → 跳到目标文件
  → 不存在 → 进入 Step 3

Step 3 (L2) — 按任务定向搜索:
  根据用户任务，在关键目录中定向搜索：
  rg -n <task_keyword> -- <likely_paths>
  或使用 codebase-memory-mcp: search_graph / search_code
  → 找到候选符号/文件 → 进入 Step 4

Step 4 (L3+L4) — 精确定位:
  读取候选文件的签名/大纲（L3）
  → 确认目标 → L4 读取精确范围
```

**禁止的仓库探索模式：**
- `ls -R`、`tree`、无过滤的 `find .`
- `cat $(git ls-files)` 或等价的全量 dump
- 递归读取整个目录树
- 在未定位目标前打开大型文件（>500行）
- 重复读取同一文件（利用已有上下文缓存）

**codebase-memory-mcp 优先（如可用）：**
- `search_graph(name_pattern="...")` → 定位函数/类，无需 grep 全仓库
- `trace_path(function_name="...")` → 追踪调用链，无需逐文件阅读
- `get_code_snippet(qualified_name="...")` → 精确取源码，无需定位行号
- `get_architecture()` → 高层面包屑，替代手动探索

### 10.3 任务进度恢复（Task Resumption）

Agent 启动或切换任务时，按以下顺序增量恢复（低 token 消耗）：

```
恢复链（从最便宜到最完整）:

1. Agent 状态 JSON（L5 快速通道, ~200 tok）:
   读取 .agents/agent_states/<name>_state.json
   → 获取: 当前任务、仓库路径、分支、状态
   → 如果 status = "idle" → 无进行中任务，等待用户指令

2. Git 现场恢复（L1, ~50 tok）:
   git status -sb
   git branch --show-current
   → 确认工作区是否有未提交变更

3. 会话摘要索引（L0 → L4, ~500 tok）:
   ls agents/<name>/sessions/ | tail -10
   → 读取最近 1-2 个会话文件
   → 如果当前任务匹配某个会话 → 读取该会话获取上下文

4. 项目记忆（L0 → L4, ~1K tok）:
   ls agents/<name>/projects/
   → 如果 working_repo 匹配已有项目记忆 → 读取该记忆
   → 获得: 项目架构、长期方向、关键决策

5. 仓库地图（L4, ~2K tok，仅当 Step 1-4 不足时）:
   读取仓库的 AGENTS.md / REPO_GUIDE.md
   → 仅在任务涉及该仓库但 agent 无记忆时执行

6. HANDOFF.md（L4，仅当存在时）:
   检查仓库根目录的 HANDOFF.md
   → 包含上一次 agent 的详细交接信息
```

**恢复决策树：**
- 用户给出全新指令 → 跳过恢复，直接执行
- 用户说 "继续" → 从 Step 1 走到 Step 3（状态 + 最近会话）
- 用户指定仓库 → Step 1 + Step 4 + Step 5（状态 + 项目记忆 + 仓库地图）
- 用户说 "继续上次的 XXX" → Step 1 + 搜索会话文件名匹配 "XXX"

### 10.4 长期项目记忆（Long-term Project Memory）

项目记忆文件存储在每个 agent 的 `projects/<project-name>.md` 中。

**记忆分层结构（写文件时按此模板）：**

```markdown
# <项目名> — 项目记忆

## 元数据
- 仓库路径:
- 远端:
- 最后更新: YYYY-MM-DD
- 当前阶段:
- 维护 agent:

## 一句话摘要（<50字）
该项目的核心目标与当前状态。

## 关键决策记录（最近 5 条）
- [YYYY-MM-DD] 决策: ... | 原因: ... | 影响: ...
- ...

## 架构要点（要点列表，非长文）
- 入口: <path>
- 核心模块: <path>, <path>
- 数据流: A → B → C
- 关键依赖: <lib>

## 当前任务上下文
- 进行中:
- 阻塞项:
- 下一优先级:

## 避免事项
- 不要修改 <path>（原因）
- 不要在 <condition> 下 <action>
```

**记忆读写规则：**
- **写记忆**：仅在重大节点（阶段完成、架构决策、阻塞出现）时更新，不要在每行代码变更后更新
- **读记忆**：Step 10.3.4 的恢复链中读取，或跨 agent 协作时读取其他 agent 的记忆
- **记忆过期**：超过 30 天未更新的项目记忆，读取时需先验证仓库当前状态是否匹配
- **记忆大小**：控制在 2000 字以内（≈ 3000 tokens），超出则拆分到 `exports/<project>/` 下

### 10.5 AgentLab 配置调用（AgentLab Config）

AgentLab 配置位于 `truenas:/mnt/hdd2/AgentLab_WorkSpace/config/`。以下为按需读取策略：

**配置分层读取（不要全量加载所有 YAML）：**

| 场景 | 需要读取的配置 | 成本 |
|------|---------------|------|
| 选择模型 | `model_profiles.yml` + `model_providers.yml` | ~1K tok |
| 路由判断 | `routing_policy.yml` + `routing_rules.yml` | ~500 tok |
| 预算控制 | `budget_profiles.yml` | ~300 tok |
| 执行策略 | `execution_policy.yml` + `execution_modes.yml` | ~500 tok |
| 记忆策略 | `memory_policy.yml` | ~200 tok |
| Agent 注册 | `agent_registry.yml` | ~300 tok |
| 自检/验证 | `self_check_policy.yml` + `validation_gates.yml` | ~500 tok |
| Task 索引 | `task_index_policy.yml` | ~200 tok |
| 全量配置 | 仅在初始化 AgentLab 或调试时读取全部 | ~5K tok |

**规则：**
- 按任务需求读取最少配置，不要 "以防万一" 加载所有 YAML
- 配置有版本控制（`version_policy.yml`），读取时检查版本
- 如配置变更影响行为，在项目记忆中记录

### 10.6 用户对话管理（Conversation Management）

**会话摘要模板（每次 push 到 sessions/ 时使用）：**

```markdown
# 会话: YYYY-MM-DD_<简短描述>

## 用户意图
<1-2 句话概括用户的核心目标>

## 关键决策
- 决策: ... | 用户选择: ... | 原因: ...

## 产出
- 文件变更: <file> (+X -Y)
- 仓库: <path>, 分支: <branch>, commit: <hash>

## 用户偏好（新增/变更）
- 偏好: ... | 上下文: ...（记录用户在本次会话中表达的新偏好）

## 未完成
- <遗留事项>（供下次恢复参考）
```

**用户偏好管理：**
- 用户在对话中表达的偏好（"以后都这样"、"不要用 X"、"优先 Y"）→ 记录在会话摘要的 "用户偏好" 栏
- 重复出现 ≥2 次的偏好 → 提升到 agent 的本地指令文件（`CLAUDE.md` / `SOUL.md` / `AGENTS.md`）
- 与协议冲突的偏好 → 优先遵循用户偏好，但在摘要中标注冲突

**上下文窗口预算：**
- Agent 会话中，协议引用 + 仓库探索 + 项目记忆的总 token 消耗不应超过可用上下文的 30%
- 其余 70% 留给实际任务执行
- 如果发现自己在探索阶段消耗超过预算 → 立即切换策略，向用户提供简短摘要并请求定向指导

---

*最后更新: 2026-06-20 | 维护者: Claude Code (saintpeter)*
