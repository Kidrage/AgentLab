# Agent Protocol — Multi-Endpoint Shared Workspace Convention

> **权威版本位置**: `<RELAY_HOST>:<RELAY_WORKSPACE>/_shared/AGENT_PROTOCOL.md`
> 本文件是 AgentLab、接线层、执行 Agent 与专用工具之间的**唯一共享协议**，
> 覆盖核心三端（Local Workstation / Relay Hub / Cloud Runtime）及登记扩展端点。
> 各 agent 的本地指令文件不得重复本文内容；只保留 agent 特有指令 + 指向本文的指针。

---

## 1. 工作原则：本地优先，三端镜像

| 端点 | 位置 | 角色 | 用途 |
|------|------|------|------|
| **Local Workstation** | `<LOCAL_USER>@<LOCAL_WORKSTATION>` | 主开发端 | 日常编码、运行、测试，所有 agent 的本地主战场 |
| **Relay Hub** | `<RELAY_HOST>:<RELAY_WORKSPACE>/` | 共享镜像 | 备份 + 跨 agent 共享读取 + 向 Cloud Runtime 分发 |
| **Cloud Runtime** | `<CLOUD_USER>@<CLOUD_RUNTIME_HOST>` | 执行端 | 远程运行、部署、持续任务执行 |
| **Localization 69** | 由该端在清单中登记 | 本地化落地端 | 本地部署、能力盘点、协议适配；登记完成前不得参与正式协作 |

- 所有 agent **默认工作在本地**，不直接操作远端。
- 重要产出（项目记忆、会话摘要、导出文件）**推送到 Relay Hub 对应命名空间** → 由 Cloud Runtime 从 Relay Hub 拉取。
- 任何 agent 可以**只读访问**其他 agent 的 Relay Hub 命名空间来获取上下文。
- **AgentLab 主目录**（`~/AgentLab/`）在三端之间保持同步（详见 Section 11）。
- 不要向 Relay Hub 推送：`node_modules/`、`.venv/`、`__pycache__/`、构建产物、缓存、日志、二进制文件、密钥。

---

## 2. Agent 角色分工

| Agent | 定位 | 擅长的任务 |
|-------|------|-----------|
| **AgentLab** (`./agentlab.sh`) | 治理与事实源 | 编译任务合同、路由、审批、证据、验收、归档；不替代专业执行 Agent |
| **OpenClaw** (`openclaw`) | 接线层 | 用户入口、审批展示、显式委派、结果回传；委派时不得自行实现任务 |
| **Claude Code** (`~/.claude/`) | 深度编码主力 | 复杂重构、深层代码分析、多文件架构变更、设计系统、Workflow 编排 |
| **Hermes** (`~/.hermes/`) | 系统协调员 | 系统级操作、跨工具协调、CLI 执行监控、全局记忆管理、MCP 网关 |
| **Codex** (`~/.codex/`) | 快速交付 | 快速代码片段、API 集成、仓库 onboarding、CI/CD 确认、PR 工作流 |
| **Qwen Code** (`qwen`) | 通用执行 Agent | 规划、分析、有限范围实现与审计 |
| **Agy** (`agy`) | 轻量探索 | 极速探索、轻量分析、Prompt 交接；不承担高风险静默修改 |
| **Bailian CLI** (`bl`) | 云端专用能力工具 | 多模态、媒体、语音、RAG、百炼搜索；不是通用接线员或默认代码 Agent |

### 2.1 开工前互相认识（强制握手）

任何端点或 Agent 第一次进入协作任务前，必须读取：

1. `_shared/AGENT_PROTOCOL.md`
2. `config/shared_agent_directory.yml`
3. `config/capability_routing_policy.yml`
4. `config/agent_collaboration.yml`

然后确认自身端点、自身 Agent ID、其他端点、其他 Agent、目标 Agent 的准确
调用合同、目标状态文件和任务锁。未知端点、未知 Agent、未知调用命令均不得猜测；
必须停止并报告 inventory gap。结构化清单是事实源，本文只解释规则。

### 2.2 准确调用与职责边界

- 所有跨 Agent 调用必须使用 `config/shared_agent_directory.yml` 或
  `config/worker_invocation_contracts.yml` 中登记且验证过的命令。
- 不得把 `--help` 成功当作任务调用合同有效的证据。
- 不得把 Worker、Skill、MCP、专用云工具视为等价能力。
- 调用者负责合同、权限、上下文和结果验收；被调用者只负责分配给它的角色。
- 目标不可用或合同无效时，停止并报告；不得静默切换到其他 Agent。

---

## 3. 命名空间与所有权

```
<RELAY_HOST>:<RELAY_WORKSPACE>/
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
- `_shared/` 只有获得用户授权的协议维护者写入；维护者身份不限于某个 Agent。

---

## 4. 状态发布与任务锁（本地优先 + 远程镜像同步）

为了确保本地开发的高效性（无需频繁通过 SSH 检查远程锁文件导致延迟），协同锁与状态发布采取**"本地读写，双向同步"**的机制。

### 4.1 锁与状态的目录结构
* **本地主路径**：`AgentLab/.agents/locks/` 和 `AgentLab/.agents/agent_states/`
* **远程镜像路径**：`<RELAY_HOST>:shared_protocols/locks/` 和 `<RELAY_HOST>:shared_protocols/agent_states/`

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
2. **上锁**：在本地 `.agents/locks/` 创建 `<任务名>.lock` 文件（内容包含 agent 标识与时间戳），并立即执行一次 `rsync` 同步上传到 Relay Hub，以同步状态。
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
- 必须做全仓库“路径与元数据”安全盘点；禁止全仓库内容暴力读取
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

### 6.6 Skill / MCP / Tool / Agent 选择顺序

统一使用 `config/capability_routing_policy.yml`，默认按以下顺序逐级升级：

1. 本地确定性工具（`rg`, `git`, AST, tests, linters）
2. 精确命中的已验证本地 Skill
3. 已登记的本地 STDIO MCP
4. 本地 Agent CLI
5. 经批准的云端专用能力
6. 远端 Agent handoff

每次升级必须有能力缺口证据。禁止为了“走流程”进行模型调用；生成工作交给
模型后，验证优先交给确定性工具。只加载命中的 Skill，禁止批量灌入所有 Skill
正文；MCP 必须先读 schema，再调用单个必要工具。

### 6.7 用户显式点名其他 Agent 时的接线层规则

当用户对 OpenClaw、聊天适配器或其他接线层明确说“调用/让/交给某个 Agent”时：

- 接线层进入 `relay_only`，不得自行规划后实现任务，不得编辑任务目标文件。
- 只允许：记录原始请求、解析目标 Agent、验证调用合同、生成 handoff、调用目标、
  监控、读取结果、检查实际 Git/file diff、向用户报告。
- 不得静默 fallback，不得冒充被调用 Agent，不得把自己的推断写成目标 Agent 结果。
- 目标 Agent 失败或不可用时，只报告失败、证据和下一选择，等待用户决定。
- 接线层允许写入的只有 handoff、事件、状态、日志和结果索引等治理工件。

最终报告必须包含：用户点名 Agent、实际调用 Agent、调用合同、Agent 结果摘要、
实际变更文件、diff 摘要、验证结果与剩余风险。文件变化必须由调用前后快照或 Git
证据确认，不能只相信 Agent 自述。

### 6.8 归属与证据

- 每个产出记录 `requested_agent`、`invoked_agent`、`reporting_agent`。
- 代码/文件修改归属实际执行者，接线层只拥有转交与报告工件。
- token 与费用仅记录真实遥测；本地 CLI 无遥测时写 `unavailable`，不得估算成事实。
- 被调用 Agent 的原始结果与接线层摘要分开保存，禁止覆盖原文。

### 6.9 端点能力发布

每个新端点在正式协作前必须向 `config/shared_agent_directory.yml` 发布：工作区、
已安装 Agent、准确命令、Skill 清单、MCP 清单、确定性工具、认证可用状态（不得
包含密钥）和版本。69 端在完成此登记前只能做本地化盘点，不能接收正式委派。

### 6.10 仓库记忆与 HandOff 强制门禁

所有端点、接线层和执行 Agent 处理任何新旧代码仓库、文献集、图片集、音频集或
混合项目时，必须执行 `config/repository_handoff_policy.yml`：

1. 读取项目内容前，先依次查找 `.agentlab/HandOff.md`、
   `agent_docs/HandOff.md`、兼容旧名 `HandOff.md` / `HANDOFF.md`，以及
   `memory/repositories/<repository_id>/HandOff.md` 共享镜像。
2. 不存在时，必须在深度读取前立即创建；当前 Agent 无写权限时，立即请求创建，
   同时至少在共享记忆区创建只读仓库镜像。确定性命令为：
   `./agentlab.sh repository-handoff --repo <path> --write`。
3. 允许且要求完整盘点路径、文件类型、大小等元数据和有限 Git 历史；禁止递归
   `cat`、读取二进制负载/密钥、跟随目录软链接、扫描依赖缓存或倾倒全部历史。
4. HandOff 必须记录仓库/数据结构、目录路线、入口、变更历史、当前状态、相关
   仓库、媒体/文献路线、验证风险和可保留的 Agent 注记。
5. 分支、commit、文件、目录、schema、接口、相关仓库或任务状态发生实质变化后，
   以及最终报告前，实际修改者必须刷新本地和共享双副本。

该门禁适用于“全新任务”和“继续任务”，不得因已有聊天上下文、Agent 身份或前端
接线角色跳过。接线层在 `relay_only` 下可创建/刷新 HandOff 治理工件，但仍不得
编辑用户点名委派的任务目标文件。

---

## 7. Agent 特有指令位置

每个 agent 的**唯一本地指令文件**（只含该 agent 特有内容）：

| Agent | 本地文件 | 用途 |
|-------|----------|------|
| AgentLab | `AGENTS.md` | 仓库治理规则 + 指向本协议 |
| OpenClaw | `~/.openclaw/workspace/AGENTS.md` | 接线层特有通道规则 + 指向本协议 |
| Claude Code | `~/.claude/CLAUDE.md` | Claude 特有工作流、skills、repo-scout |
| Hermes | `~/.hermes/SOUL.md` | 人格定义 + relay 指针 |
| Codex | `~/.codex/AGENTS.md` | Codex 特有：onboarding 协议、`.codex/` 目录约定、codebase-memory-mcp |
| Agy | `~/.agy/AGENTS.md` | Agy 特有配置 |
| Qwen Code | `~/.qwen/AGENTS.md`（若存在） | Qwen 特有配置 + 指向本协议 |

**禁止事项：**
- ❌ 不得在两个 agent 的指令文件中写相同的规则
- ❌ 不得在本协议之外另立跨 agent 规则
- ❌ 不得绕过本协议直接修改其他 agent 的命名空间
- ❌ 不得在旧 `shared_protocols/AGENT_COORDINATION_PROTOCOL.md` 中添加内容（该文件已废弃，仅保留指针）

---

## 8. SSH 连接信息

### Relay Hub

```
Host:      <RELAY_HOST>:<RELAY_SSH_PORT>
User:      <RELAY_SSH_USER>
Key:       <RELAY_SSH_KEY> (ED25519)
Workspace: <RELAY_WORKSPACE>
Disk:      large capacity
```

### Cloud Runtime

```
Host:      <CLOUD_RUNTIME_HOST>
User:      <CLOUD_SSH_USER>
Key:       <CLOUD_SSH_KEY> (RSA)
Workspace: /home/<CLOUD_SSH_USER>/AgentLab
OS:        Linux
Disk:      standard cloud disk
```

SSH 配置位于 `~/.ssh/config`，所有 agent 共享使用。本地系统在开机时自动建立到 Relay Hub 的保活连接（LaunchAgent / systemd service）。

---

## 9. 协议更新流程

1. 修改本文件以及对应结构化清单并运行协议校验测试
2. 更新 `config/shared_agent_directory.yml` 时不得写入密钥或私有 token
3. 如需更新 Agent 特有指令，只修改对应 Agent 的本地文件并保留本协议指针
4. 在 commit message 中标注 `[protocol]` 前缀
5. 先同步代码与协议，再同步状态；其他 Agent 在下一任务握手时读取新版本

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

进入任意仓库/项目的标准流程。必须安全盘点全部路径与元数据，禁止全量读取内容：

```
Step 0 (L0) — HandOff 门禁（始终最先执行）:
  ./agentlab.sh repository-handoff --repo <path>
  → found: 先读 HandOff，再进入 Step 1
  → missing: 立即加 --write 创建本地 + 共享记忆双副本；无写权限则请求创建

Step 1 (L0+L1) — 安全路径/元数据快照（始终执行）:
  git rev-parse --show-toplevel
  git status -sb
  git branch --show-current
  git remote -v
  git ls-files -co --exclude-standard | wc -l
  # 非 Git 项目使用 rg --files，并排除缓存、依赖、产物目录

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

`git ls-files` / `rg --files` 的全路径枚举和文件元数据统计不属于“暴力扫描”；它们
是必需的安全盘点。路径清单不能扩展为批量文件内容读取。

**codebase-memory-mcp 优先（如可用）：**
- `search_graph(name_pattern="...")` → 定位函数/类，无需 grep 全仓库
- `trace_path(function_name="...")` → 追踪调用链，无需逐文件阅读
- `get_code_snippet(qualified_name="...")` → 精确取源码，无需定位行号
- `get_architecture()` → 高层面包屑，替代手动探索

### 10.3 任务进度恢复（Task Resumption）

Agent 启动或切换任务时，按以下顺序增量恢复（低 token 消耗）：

```
恢复链（从最便宜到最完整）:

1. Repository HandOff（L4，始终执行）:
   搜索 `.agentlab/HandOff.md`、`agent_docs/HandOff.md`、兼容旧名和共享镜像
   → 找到：先读再继续
   → 缺失：立即创建/请求创建，深度仓库读取在此之前不得开始

2. Agent 状态 JSON（L5 快速通道, ~200 tok）:
   读取 .agents/agent_states/<name>_state.json
   → 获取: 当前任务、仓库路径、分支、状态
   → 如果 status = "idle" → 无进行中任务，等待用户指令

3. Git 现场恢复（L1, ~50 tok）:
   git status -sb
   git branch --show-current
   → 确认工作区是否有未提交变更

4. 会话摘要索引（L0 → L4, ~500 tok）:
   ls agents/<name>/sessions/ | tail -10
   → 读取最近 1-2 个会话文件
   → 如果当前任务匹配某个会话 → 读取该会话获取上下文

5. 项目记忆（L0 → L4, ~1K tok）:
   ls agents/<name>/projects/
   → 如果 working_repo 匹配已有项目记忆 → 读取该记忆
   → 获得: 项目架构、长期方向、关键决策

6. 仓库地图（L4, ~2K tok，仅当前述信息不足时）:
   读取仓库的 AGENTS.md / REPO_GUIDE.md
   → 仅在任务涉及该仓库但 agent 无记忆时执行

```

**恢复决策树：**
- 用户给出全新指令 → 仍执行 HandOff 门禁，然后直接执行
- 用户说 "继续" → 从 Step 1 走到 Step 4（HandOff + 状态 + Git + 最近会话）
- 用户指定仓库 → Step 1 + Step 3 + Step 5 + Step 6
- 用户说 "继续上次的 XXX" → Step 1 + Step 4 搜索会话文件名匹配 "XXX"

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
- **读记忆**：Step 10.3.5 的恢复链中读取，或跨 agent 协作时读取其他 agent 的记忆
- **记忆过期**：超过 30 天未更新的项目记忆，读取时需先验证仓库当前状态是否匹配
- **记忆大小**：控制在 2000 字以内（≈ 3000 tokens），超出则拆分到 `exports/<project>/` 下

### 10.5 AgentLab 配置调用（AgentLab Config）

AgentLab 配置位于 `<RELAY_HOST>:<RELAY_WORKSPACE>/config/`。以下为按需读取策略：

**配置分层读取（不要全量加载所有 YAML）：**

| 场景 | 需要读取的配置 | 成本 |
|------|---------------|------|
| 选择模型 | `agent_model_profiles.yml` + `model_providers.yml` | ~1K tok |
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

## 11. 三端 AgentLab 主目录同步

> **核心原则**: AgentLab 主目录（`~/AgentLab/`）的代码、配置、协议文件**必须在三端之间保持同步**。
> 以 GitHub (`Kidrage/AgentLab.git`) 为 git 中枢，Relay Hub 为 workspace 中转站。

### 11.1 三端同步拓扑

```
Local Workstation  ←──git push/pull──→  GitHub (Kidrage/AgentLab.git)
         │                                        │
         │ rsync workspace mirror                 │ git pull
         ▼                                        ▼
   Relay Hub         ←──rsync pull workspace──  Cloud Runtime
         │                                        │
         └────────── ssh git push ────────────────→┘  (Relay 无法访问 GitHub 时的替代路径)
```

### 11.2 AgentLab 主目录同步规则

**以下内容属于 AgentLab 主目录同步范围（必须保持三端一致）：**

| 内容 | 同步方式 | 频率 |
|------|----------|------|
| 源代码（`agent_runtime/`, `agent_templates/`, `web_ui/`, `scripts/`, `skills/`） | Git (GitHub) | 每次 commit |
| 配置文件（`config/`） | Git (GitHub) | 每次 config 变更 |
| 协议文件（`_shared/`, `shared_protocols/`） | Git (GitHub) | 协议更新时 |
| 项目记忆（`projects/`） | rsync (via Relay Hub) | 任务完成时 |
| Agent 状态（`shared_protocols/agent_states/`） | rsync (via Relay Hub) | 状态变化时 |
| 测试、文档 | Git (GitHub) | 每次 commit |

**以下内容 NOT 同步（各端独立）：**

| 内容 | 原因 |
|------|------|
| `.agents/` (locks, states) | 本地锁，仅通过 rsync 到 Relay Hub |
| `.env` | 各端密钥不同 |
| `.cache/`, `__pycache__/`, `.pytest_cache/` | 构建缓存 |
| `executor_runs/`, `router_update_runs/` | 运行时产物，本地独立 |
| `git-repos/` | 裸仓库，各端按需维护 |

### 11.3 同步操作手册

#### 从 Local Workstation 同步到其他端

```bash
# 1. 代码提交；只有用户明确授权同步到远端时才 push
cd ~/AgentLab
git status -sb
git add <approved-paths> && git commit -m "..."
git push origin HEAD:main  # requires explicit user authorization

# 2. Workspace 同步到 Relay Hub（agentlab.sh 或手动 rsync）
./agentlab.sh relay-sync --execute
# 或:
rsync -avz -e "ssh -p <RELAY_SSH_PORT>" \
  --exclude '.git' --exclude '__pycache__' --exclude '.pytest_cache' \
  --exclude '.env' --exclude '.venv' --exclude '.cache' \
  --exclude 'executor_runs' --exclude 'router_update_runs' \
  --exclude 'git-repos' \
  ~/AgentLab/ <RELAY_SSH_USER>@<RELAY_HOST>:<RELAY_WORKSPACE>/
```

#### Cloud Runtime 从 GitHub 拉取代码

```bash
# 在 Cloud Runtime 上；工作区不干净时停止并报告，不得覆盖
cd ~/AgentLab
git fetch origin main
git status --short
git merge --ff-only origin/main
```

#### Cloud Runtime 从 Relay Hub 拉取 workspace 镜像

```bash
# 在 Cloud Runtime 上:
rsync -avz --exclude '.git' --exclude '__pycache__' --exclude '.cache' \
  <RELAY_SSH_USER>@<RELAY_HOST>:<RELAY_WORKSPACE>/ ~/AgentLab/
```

#### Relay Hub 无法访问 GitHub 时的替代路径

```bash
# 从 Local Workstation 直接推送 git 对象到 Relay Hub:
cd ~/AgentLab
git push ssh://<RELAY_HOST><RELAY_WORKSPACE> main:refs/heads/sync-temp
# 然后在 Relay Hub 上:
ssh <RELAY_HOST> "cd <RELAY_WORKSPACE> && git reset --hard sync-temp && git branch -D sync-temp"
```

### 11.4 同步纪律

1. **任何端修改 AgentLab 代码后，必须准备可同步提交；push/远端写入仍需用户授权**
2. **协议文件（`_shared/AGENT_PROTOCOL.md`）变更优先同步**——这是跨 agent 的合同
3. **主目录同步前先检查各端状态**：确认没有未提交的修改
4. **三端 AgentLab 的 git HEAD 必须指向同一个 commit**（允许 Relay Hub 短暂滞后，但必须在下一个工作周期开始前追上）
5. **禁止在三端并行修改同一文件**——如果不可避免，先在本地合并，再推送
6. **定期自检**：任何 agent 在进入 AgentLab 主目录时，运行 `git fetch origin && git status -sb` 确认同步状态
7. **协作前握手**：确认 `shared_agent_directory.yml` 中能看到自己、目标端点和目标 Agent；69 端还必须把 `inventory_required` 更新为已盘点状态

### 11.5 三端同步自检命令

```bash
# 在任何端点运行，确认三端一致:
echo "=== Local ===" && cd ~/AgentLab && git rev-parse --short HEAD
echo "=== Relay ===" && ssh <RELAY_HOST> "cd <RELAY_WORKSPACE> && git rev-parse --short HEAD"
echo "=== Cloud ===" && ssh <CLOUD_USER>@<CLOUD_RUNTIME_HOST> "cd ~/AgentLab && git rev-parse --short HEAD"
```

三端应输出相同的 commit hash。

---

*最后更新: 2026-06-23 | 维护者: AgentLab protocol maintainers*
