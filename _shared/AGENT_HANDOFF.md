# Agent 协作 Handoff — 共享服务、Skills、MCP、工具链

> 本文件是跨端能力快照，不是具体仓库记忆。仓库级状态遵循
> `config/repository_handoff_policy.yml`，唯一权威存放在仓库根目录
> `PROJECT_HANDOFF.md`；共享镜像仅按需写入
> `memory/repositories/<repository_id>/HandOff.md`。

> **位置**: `<RELAY_HOST>:<RELAY_WORKSPACE>/_shared/AGENT_HANDOFF.md`
> 本文件是所有 agent 的共享能力清单。新 agent 加入或现有 agent 更新能力时，更新本文件。
> 配合 `_shared/AGENT_PROTOCOL.md` 使用。

---

## 1. 环境总览

```
主机: <LOCAL_WORKSTATION>, Darwin
工作区: ~/AgentLab/
远端: <RELAY_HOST>:<RELAY_SSH_PORT> <RELAY_WORKSPACE>/
Shell: zsh
Node: <install_path>/node/bin/node
Python: <install_path>/bin/python3
包管理: brew, npm, pip
```

---

## 2. Agent CLI 入口

| Agent | 二进制路径 | 安装方式 | 默认模型 |
|-------|-----------|---------|---------|
| **Claude Code** | `~/.local/bin/claude` → `@anthropic-ai/claude-code` | npm global | deepseek-v4-pro[1m] |
| **Hermes** | `~/anaconda3/bin/hermes` | pip | gemini-3.1-pro-preview |
| **Codex** | `~/.local/bin/codex` → `/Applications/Codex.app/...` | macOS .app | gpt-5.5 |
| **Agy** | `/usr/local/bin/agy` | ? (Mach-O binary) | ? |

---

## 3. 共享 MCP 服务器

### 3.1 codebase-memory-mcp

**最重要的共享基础设施。**

```
二进制: ~/.local/bin/codebase-memory-mcp
使用者: Claude Code ✓ | Hermes ✓ | Codex ✓ | Agy ✗
```

**功能：**
- `search_graph` — 按名称/模式/语义查找函数、类、路由
- `trace_path` — 追踪调用链（inbound/outbound/data_flow/cross_service）
- `get_code_snippet` — 精确读取函数/类源码
- `query_graph` — Cypher 图查询
- `get_architecture` — 项目高层架构
- `search_code` — 图增强的代码搜索
- `index_repository` — 索引仓库入知识图谱
- `list_projects` / `index_status` — 项目管理

**项目索引状态：**
- 使用前先 `list_projects` 查看是否已索引
- 未索引则 `index_repository(repo_path="...")` 进行索引
- 模式：full（全量+语义）、moderate（过滤+语义）、fast（过滤无语义）、cross-repo-intelligence（跨仓库关联）

**配置要点：**
- Claude Code: 通过插件/内置支持加载（`mcp__codebase-memory-mcp__*` 工具组）
- Hermes: `config.yaml` → `mcp_servers.codebase-memory-mcp`
- Codex: `config.toml` → `[mcp_servers.codebase-memory-mcp]` + SessionStart hook

### 3.2 代理网络

```
HTTP_PROXY:  http://127.0.0.1:7890
HTTPS_PROXY: http://127.0.0.1:7890
ALL_PROXY:   socks5h://127.0.0.1:7891
```

- Claude Code 通过 `settings.json` → `env` 配置
- Hermes 和 Codex 需要各自配置代理（如需要）
- Agy 需单独验证代理支持

### 3.3 Antigravity Proxy（Agy 网关）

```
路径: ~/.local/bin/antigravity-proxy → .../antigravity-proxy/src/server.ts
启动: ~/.local/bin/start-agy-proxy.sh
```

用于 Agy 的代理/网关层。

---

## 4. 共享 Skills 清单

### 4.1 三 Agent 共有（Claude Code + Hermes + Codex）

以下 skills 在 Claude Code 和 Hermes 中同时存在，功能等价。Codex 有其自己的实现或通过 Hermes 调用：

| Skill | 用途 | Claude | Hermes | Codex |
|-------|------|--------|--------|-------|
| `codebase-memory` | 知识图谱代码查询 | ✓ | ✓ | 内置 |
| `repo-scout` | 创建/刷新仓库指南 | ✓ | ✓ | 内置 |
| `review` | 代码审查 | ✓ | ✓ | ✗ |
| `diagnosing-bugs` | Bug 诊断循环 | ✓ | ✓ | ✗ |
| `tdd` | 测试驱动开发 | ✓ | ✓ | ✗ |
| `phase-repair` | 分阶段仓库修复 | ✓ | ✓ | ✗ |
| `handoff` | 任务交接 | ✓ | ✓ | ✗ |
| `qa` | 交互式 QA / 提 issue | ✓ | ✓ | ✗ |
| `resolving-merge-conflicts` | 合并冲突解决 | ✓ | ✓ | ✗ |
| `setup-pre-commit` | Husky pre-commit hooks | ✓ | ✓ | ✗ |
| `git-guardrails-claude-code` | Git 安全 hooks | ✓ | ✓ | ✗ |

### 4.2 设计与建模（Claude Code + Hermes）

| Skill | 用途 |
|-------|------|
| `codebase-design` | 深层模块接口设计 |
| `design-an-interface` | 多方案接口生成 |
| `domain-modeling` | 领域建模/通用语言 |
| `ubiquitous-language` | 维护领域术语表 |
| `improve-codebase-architecture` | 架构改进 |
| `request-refactor-plan` | 重构计划 + issue |

### 4.3 写作与文档（Claude Code + Hermes）

| Skill | 用途 |
|-------|------|
| `writing-beats` | 文章作为节拍旅程 |
| `writing-fragments` | 碎片化素材收集 |
| `writing-shape` | 素材整形为文章 |
| `edit-article` | 文章编辑 |
| `writing-great-skills` | **仅 Claude Code** — 编写优质 skill |

### 4.4 项目流程（Claude Code + Hermes）

| Skill | 用途 |
|-------|------|
| `implement` | 实现 |
| `prototype` | 原型 |
| `to-issues` | 转为 GitHub issues |
| `to-prd` | 转为 PRD |
| `triage` | 分类/优先级 |
| `grilling` / `grill-me` / `grill-with-docs` | 方案压力测试 |
| `scaffold-exercises` | 脚手架练习结构 |
| `decision-mapping` | 决策映射 |
| `obsidian-vault` | Obsidian 笔记管理 |
| `ask-matt` | Matt Pocock 咨询 |
| `migrate-to-shoehorn` | TypeScript shoehorn 迁移 |
| `setup-matt-pocock-skills` | 安装 Matt 技能集 |

### 4.5 Hermes 独占 Skills

这些 skills 利用 Hermes 的系统协调员角色：

| Skill | 用途 |
|-------|------|
| `apple` | Apple 生态集成 |
| `autonomous-ai-agents` | 自主 agent 管理 |
| `creative` | 创意生成 |
| `data-science` | 数据科学 |
| `devops` | DevOps 操作 |
| `dogfood` | 自测/内部试用 |
| `email` | 邮件处理 |
| `github` | GitHub 操作 |
| `media` | 媒体处理 |
| `mlops` | MLOps |
| `note-taking` | 笔记 |
| `productivity` | 生产力工具 |
| `research` | 深度研究 |
| `smart-home` | 智能家居 |
| `social-media` | 社交媒体 |
| `software-development` | 软件开发 |
| `yuanbao` | 元宝集成 |

### 4.6 Codex 独占 Skills

| Skill | 用途 |
|-------|------|
| `repo-guide-bootstrap` | 仓库引导初始化 |
| `repo-navigation-token-saver` | Token 节省的仓库导航 |
| `hatch-pet` | Codex pet 管理 |

### 4.7 Agy

Agy 支持插件系统（`agy plugin`），但当前无独立 skills 目录。其轻量探索角色适合快速任务。

---

## 5. 共享 Hooks（PreToolUse / SessionStart）

### 5.1 token-guard.py（Claude Code）

```
路径: ~/.claude/hooks/token-guard.py
类型: PreToolUse
作用: 拦截高噪音 Bash 命令（ls -R, grep -r, find . -type f, cat lockfiles, 
      读取 node_modules/.venv/dist/build/coverage/.git/）
逃生: CLAUDE_ALLOW_NOISY=1 前缀绕过
```

### 5.2 pre_bash_token_guard.py（Hermes）

```
路径: ~/.hermes/hooks/pre_bash_token_guard.py
类型: PreToolUse
作用: 与 token-guard.py 功能等价，适配 Hermes
```

### 5.3 cbm-session-reminder（Claude Code）

```
路径: ~/.claude/hooks/cbm-session-reminder
类型: SessionStart
作用: 每次会话启动时提醒优先使用 codebase-memory-mcp 工具
```

### 5.4 Codex SessionStart hook

```
类型: SessionStart（嵌入 config.toml）
作用: 等价于 cbm-session-reminder
命令: echo "Code discovery: prefer codebase-memory-mcp..."
```

---

## 6. 共享配置目录

### 6.1 AgentLab Config（远端共享）

```
<RELAY_HOST>:<RELAY_WORKSPACE>/config/
├── agent_model_profiles.yml    # 模型 profile 定义
├── agent_registry.yml          # Agent 注册表
├── auto_sync_policy.yml        # 自动同步策略
├── backup_policy.yml           # 备份策略
├── brain_governance.yml        # Brain 治理
├── budget_profiles.yml         # Token 预算
├── evaluation_policy.yml       # 评估策略
├── execution_modes.yml         # 执行模式
├── execution_policy.yml        # 执行策略
├── github_policy.yml           # GitHub 策略
├── harness_policy.yml          # Harness 策略
├── memory_policy.yml           # 记忆策略
├── model_catalog.yml           # 模型目录
├── model_providers.yml         # 模型提供商
├── routing_policy.yml          # 路由策略
├── routing_rules.yml           # 路由规则
├── self_check_policy.yml       # 自检策略
├── task_index_policy.yml       # 任务索引策略
├── validation_gates.yml        # 验证门禁
└── version_policy.yml          # 版本策略
```

### 6.2 本地配置

| Agent | 配置目录 | 关键文件 |
|-------|---------|---------|
| Claude Code | `~/.claude/` | `settings.json`, `CLAUDE.md`, `hooks/`, `skills/`, `plugins/` |
| Hermes | `~/.hermes/` | `config.yaml`, `SOUL.md`, `hooks/`, `skills/` |
| Codex | `~/.codex/` | `config.toml`, `AGENTS.md`, `skills/`, `hooks/` |
| Agy | `~/.agy/` | `AGENTS.md` |

---

## 7. 共享协议文件

| 文件 | 位置 | 用途 |
|------|------|------|
| **AGENT_PROTOCOL.md** | `<RELAY_HOST>:_shared/AGENT_PROTOCOL.md` | 唯一权威跨 agent 协议 |
| **AGENT_HANDOFF.md** | `<RELAY_HOST>:_shared/AGENT_HANDOFF.md` | 本文件 — 共享能力清单 |
| AGENT_COORDINATION_PROTOCOL.md | `<RELAY_HOST>:shared_protocols/` | ⚠ 已废弃 → 指针指向 AGENT_PROTOCOL.md |

---

## 8. Agent 间协作：谁该做什么

### 按任务类型路由

| 任务类型 | 首选 Agent | 原因 |
|---------|-----------|------|
| 复杂重构、架构变更 | Claude Code | Workflow 编排、深层分析 |
| 系统操作、多工具协调 | Hermes | 系统协调员角色 |
| 快速代码片段、API 集成 | Codex | 快速交付定位 |
| 快速探索、轻量问答 | Agy | 极速、低开销 |
| 创建仓库指南 | Claude Code / Codex | repo-scout / repo-guide-bootstrap |
| 代码审查 | Claude Code / Hermes | review skill |
| Bug 诊断 | Claude Code / Hermes | diagnosing-bugs skill |
| TDD 开发 | Claude Code / Hermes | tdd skill |
| 写作/文档 | Claude Code / Hermes | writing-* skills |
| 知识图谱查询 | 任意（Claude/Hermes/Codex） | codebase-memory-mcp 共享 |
| 全局记忆管理 | Hermes | 系统协调员 |

### 冲突避免

1. 开始大任务前 → 检查 `.agents/locks/` 和 `.agents/agent_states/`
2. 任务被某 agent 认领 → 其他 agent 只读
3. 不确定时 → 检查对方的 agent 状态 JSON

---

## 9. 新 Agent 加入检查清单

新 agent CLI 加入本环境时：

1. [ ] 在 `~/.ssh/config` 中确认 relay hub SSH 可用
2. [ ] 创建本地指令文件（参考第 7 节协议模板）
3. [ ] 在 `<RELAY_HOST>:agents/<name>/` 创建命名空间
4. [ ] 在 `<RELAY_HOST>:shared_protocols/agent_states/` 创建初始状态 JSON
5. [ ] 配置 `codebase-memory-mcp`（如适用）
6. [ ] 配置 token guard hook（如适用）
7. [ ] 更新本文件的 Agent 清单和 skills 表
8. [ ] 更新 `AGENT_PROTOCOL.md` 的 Agent 角色分工表

---

## 10. 维护信息

```
最后更新: 2026-06-23
维护者: Claude Code
相关协议: _shared/AGENT_PROTOCOL.md (v3)
relay commit: pending
```

### 更新日志

- 2026-06-20: 初始版本 — 完整盘点 4 agent 的 skills、MCP、hooks、配置
