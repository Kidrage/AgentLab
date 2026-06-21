# AgentLab 企业架构与多端 Agents 协作协议
**（AgentLab Corp & Multi-End Collaboration Protocol）**

---

## 目录
1. [企业愿景与架构设计（Agent OS / Agent Corp）](#1-企业愿景与架构设计agent-os-agent-corp)
2. [工作站集中管理与工作区纪律](#2-工作站集中管理与工作区纪律)
3. [多端三方协作拓扑规范 (Mac - 61中转 - 250办公区)](#3-多端三方协作拓扑规范-mac---61中转---250办公区)
4. [Token 节约与高效检索规范](#4-token-节约与高效检索规范)
5. [共享 Skills 库与 MCP 服务规范](#5-共享-skills-库与-mcp-服务规范)
6. [工作区纪律与自检规范](#6-工作区纪律与自检规范)

---

## 1. 企业愿景与架构设计（Agent OS / Agent Corp）

AgentLab 演进为一个完整的 **Agent 软件公司 (Agent OS)**。本协议作为全公司多端 Agents（员工）的最高行为准则，确保在长期项目与日常任务中，多方 Agents 达到统一记忆与高效执行。

### 1.1 核心角色领域建模
*   **Agent 雇员 (Agent Employee)**：具有唯一在册标识（Agent ID）与专属财务账单（Budget Ledger）的执行 Agent（如 Claude Code, Antigravity 等）。
*   **审计与合规部 (Audit & Compliance)**：由 AgentLab 自动化验收门禁（Acceptance Check）与自检脚本（`rule_self_check.py`）组成，负责拦截越权变动与代码垃圾。
*   **财务部 (Finance Dept)**：监控 Token 与 API 消耗，确保不超过项目的安全配额。

### 1.2 协作机制
*   **小任务模式**：独立 Agent CLI（如 Claude Code）在承接日常微小 Bugfix 时，自动读取本地 MCP 记忆与项目 `agent_docs` 中的上下文，执行自检审计通过后归档。
*   **大项目模式**：由 Supervisor Agent (Hermes) 生成全局实施方案，并将模块开发任务作为 Task Pack 分配路由给独立 Coder Agents。
*   **财务与预算超额治理（试运营）**：
    *   **集中账本监控**：引入统一的财务审计。由 Supervisor (Hermes) 集中监管 Task Sandbox 中的 `cost_ledger.yml`（费用总账），记录所有 Agent 雇员的接口开销。
    *   **预算超额拦截 (Budget Grill)**：在下发下一步指令前，Supervisor 进行总账核销。若预算耗尽或超标，自动挂起任务运行并触发 `Budget Grill` 面试，由用户选择追加配额或削减 Scope。此机制目前处于试运营阶段，未来会根据执行损耗与效果进行微调。

---

## 2. 工作站集中管理与工作区纪律

所有 Agents 必须在统一的物理边界内活动，以实现配置和历史记忆的同步：

### 2.1 集中化工作站 (Centralized Workstations)
*   **绝对路径**：`AgentLab/.agents/workspaces/`
*   **运行机制**：
    *   所有 Agents 的配置文件夹（如 `.claude`, `.gemini`, `.hermes`, `.qwen`, `.codex` 等）统一存放在 `AgentLab/.agents/workspaces/` 内，随仓库一同进行多端同步。
    *   在本地 Mac 用户根目录 `/Users/saintpeter/` 下，创建对应的软链接（Symlinks）指向上述仓库目录，确保独立 CLI 终端可以正常读写，且不污染外部空间。

### 2.2 三层产物隔离规范 (Three-Tier Artifact Structure)
任何任务交付必须严格按照三层结构输出，坚决杜绝在仓库根目录直接写临时日志或混乱代码：
1.  **工作进行区 (Task Sandbox)**：`projects/<ProjectName>/runs/<task_id>/`，存放开发过程中的临时修改和日志。
2.  **阶段产物产生区 (Task Artifact Capture)**：`projects/<ProjectName>/runs/<task_id>/artifacts/`，存放本阶段生成的需要进行 QA 测试的待验证成果。
3.  **项目最终交付区 (Project Production Area)**：`projects/<ProjectName>/artifacts/`，当且仅当通过阶段验收测试后，由行政/归档 Agent 将结果整理发布至此，保持干净的最终交付区。

---

## 3. 多端三方协作拓扑规范 (Mac - 61中转 - 250办公区)

本项目的多端 Agents 协同架构基于**“本地开发 - 中转拉齐 - 云端算力”**的三端分布式体系。

```
+------------------------------------+        +------------------------------------+
|  本地 Mac 开发端                    | <----> |  Relay Hub (10.147.17.61 中转站)   |
|  - 独立 CLI 工具、软链接配置          |  Sync  |  - 共享技能、共享工作站、代码与快照  |
+------------------------------------+        +------------------------------------+
                   ^                                             ^
                   | Sync                                        | Sync
                   v                                             v
+----------------------------------------------------------------------------------+
|                   云端服务器 Cloud Runtime (10.147.17.250 办公区)                  |
|                   - 实际运行跑测容器、大模型离线部署与运行环境                       |
+----------------------------------------------------------------------------------+
```

### 3.1 三端角色定义
1.  **本地 Mac 开发端**：作为代码开发、协议微调的真理之源（Source of Truth）。
2.  **10.147.17.61 (Relay Hub 中转站)**：
    *   公司唯一的**信息与配置中转枢纽**。
    *   存储所有 Agents 的工作站配置、同步快照和共享 Skills 包。
    *   本地 Mac 通过 `./agentlab.sh truenas-sync --execute` 将变动推送至该节点。
3.  **10.147.17.250 (Cloud Runtime 办公区)**：
    *   作为分公司**重型办公与执行环境**。
    *   云端通过定时任务或 Git Hook 自动从 61 中转站拉取最新的 `.agents/workspaces/` 状态、代码仓库和技能，确保两端 Agents 在执行代码时拥有完全相同的运行时与会话历史。

### 3.2 双轨同步与安全审计纪律 (Double-Track Sync & Safety Policy)
1. **双轨同步机制**：
   * **方案 A (Git 仓库管理)**：适合对 AgentLab 系统自身结构、底层脚本、工作流定义（`agent_runtime/`, `config/` 等）进行修改时使用，走标准的 Git 提交并推送到公司内部代码库。
   * **方案 B (Rsync 专轨同步)**：适合日常项目运行数据、运行账本、以及各 Agent 的实时会话状态（`.agents/workspaces/`）在公司内部多端流转。通过执行专属同步脚本 `./agentlab.sh truenas-sync` 直接与 61 中转站（TrueNAS）进行高频对齐。
2. **资产安全与外部隔离规范**：
   * **项目资产专存**：所有项目产出的商业资产（`projects/` 目录下的产物及 Sandbox 记录）仅允许通过方案 B 同步至 61 中转站，**绝对禁止推送至公共/外置 GitHub 仓库**。
   * **凭证绝对隔离 (Credential Isolation)**：所有的 API 密钥、密钥配置文件（如 `.env`, `.git-credentials` 等）禁止上传到任何代码版本库（包括方案 A 的 Git 仓库），也禁止在中转站暴露，仅物理留存于本地 Mac 的沙箱保护区中。

---

## 4. Token 节约与高效检索规范

所有 Agent 在进行大规模仓库检索时，严禁使用盲目的全局 grep 以免耗尽上下文 Token。

### 4.1 检索优先级定义
1.  **第一优先级：MCP 知识图谱工具 (Codebase Graph Tools)**  
    使用 `codebase-memory-mcp` 专门工具来获取精确的数据，不加载冗余文本：
    *   `search_graph`：通过模式查找特定的函数、类或路由。
    *   `trace_path`：分析代码的调用栈（inbound / outbound）。
    *   `get_code_snippet`：仅获取目标代码块的源码。
2.  **第二优先级：传统 Grep (Fallback search)**  
    仅用于检索非代码文本、字面量、系统配置或 error 日志。

---

## 5. 共享 Skills 库与 MCP 服务规范

### 5.1 共享技能包 (Skills Vault)
*   **全局技能库**：`/Users/saintpeter/.agents/skills/`，内置 `agent-reach`、`bailian-cli`、`ponytail` 等 26 个通用技能。
*   **工作区技能库**：`AgentLab/.agents/skills/`，如 `repo-navigation-token-saver`。
*   **调用规矩**：在执行包含相关关键字的任务时，Agent 必须读取对应技能的 `SKILL.md` 指导，或者将任务托管给具备该技能的子 Agent 实例。

### 5.2 共享 MCP 配置 (Shared MCP Config)
*   各端 Agents 的配置文件（`~/.claude.json` 与 `~/.gemini/config/mcp_config.json`）中必须统一注册运行 `codebase-memory-mcp` 服务，实现图谱数据同源。

---

## 6. 质量验收网关与自检规范 (Quality Acceptance & Self-Check)

### 6.1 阶段交付双重验收网关 (Dual-Gate Acceptance Policy - 试运营)
所有由 Coder Agent 交付的成果在归档前必须通过以下双重网关审核：
1. **自动化检验**：自动执行单元测试、集成测试以及静态语法扫描（如 `pytest`），测试结果必须全绿。
2. **审计雇员同行评审**：自动拉起独立的 **Auditor Agent** 角色（如 TesterAuditor 或 Verifier），通过执行 `ponytail-review` 核查提交的代码中是否存在过度设计（Over-engineering）、Spec 偏离或不必要的依赖引入。审核无异议后方可完成任务关闭。

### 6.2 部门扩建与预算宽限期望 (Future Expansion & Budget Buffering)
* **业务扩充预期**：由于目前 Agent 公司部门设计尚不齐全，未来随着新业务（如重型重构、跨端测试）的开展，需不断引入新的 Agent 雇员角色。
* **财务宽限预算**：财务审批机制在编制项目预算时，必须为未来的角色扩建与新业务流转预留合理的 **Token 与 API 成本宽限系数 (Budget Buffer)**，防止试运营期间因频繁拦截导致正常业务流转挂起。

### 6.3 合规自检 (Compliance Self-Check)
* **零外部污染**：严禁把代码外的调试垃圾直接堆在项目根目录。
* **自检提交通道**：在进行 Git 提交或任务对齐之前，必须在工作区执行：
  ```bash
  python3 agent_runtime/rule_self_check.py
  ```
  由审计机制验证工作站目录合规，无凭证泄露风险，方可推送到 61 中转站。
