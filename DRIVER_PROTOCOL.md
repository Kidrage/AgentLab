# AgentLab 外部 AI 驱动协议

> **适用对象**：Codex Plus（有额度的订阅用户）
> **跨端权威协议**：`_shared/AGENT_PROTOCOL.md`。端点、Agent、准确调用命令与
> 能力路由分别以 `config/shared_agent_directory.yml`、
> `config/worker_invocation_contracts.yml`、`config/capability_routing_policy.yml` 为准。
> 所有仓库读取前必须执行 `config/repository_handoff_policy.yml` 的 HandOff 门禁；
> 缺失时先运行 `./agentlab.sh repository-handoff --repo <path> --write`。
> **你的角色**：外部 IDE 调度与验收层——收取自然语言任务 → 写入 AgentLab task → 启动 AgentLab 自驱链路 → 验收结果 → 查漏补缺
> **目标**：让 AgentLab 自己完成规划、感知、执行、审计和归档；外部 IDE AI 不伪装成 AgentLab 多 agent/API 执行结果
> **注意**：Codex Plus、Cline、Claude、DeepSeek Chat 等外部 IDE/聊天 AI 默认只负责调度与验收。只有当 AgentLab Coder 阶段被显式切到 `external_ide_ai`，或用户明确授权手动接管时，外部 AI 才能编辑文件。

---

## 核心原则

```
你（外部 IDE AI）   AgentLab 大脑/感知/API Agents        AgentLab 执行/审计/归档
──────────────     ─────────────────────────────        ───────────────────────
收任务、启动、验收   规划、路由、分析、提示词、风险判断       Qwen Coder/API 或受控外部执行
薄薄一层             所有可自驱的思考工作                  写报告、记账、状态推进、记忆归档
```

- 你默认 **不做** 任务规划、架构分析、范围评估；这些必须由 Supervisor/RepoScout/InterfaceMapper 产出本地工件
- 你默认 **不做** 代码实现；这些必须由 AgentLab Coder API、受控外部 Coder handoff，或用户显式授权的手动接管完成
- 你默认 **不做** 代码审查；这些必须由 TesterAuditor/Verifier 产出本地工件
- 你可以做：创建 task、运行 CLI、检查 `workflow_plan.yml`/报告/状态、复述结果、指出缺口、要求重跑或补充验证
- 若你手动补写任何报告或执行任何文件改动，必须在报告中标明 `backend: external_ide_manual` 或 `codex_plus_manual`，不能把它记成 API agent 自驱结果

---

## Coder 模式切换规则

Coder 有三个执行模式。默认目标是 AgentLab 自驱；外部 IDE AI 是 fallback/验收工具，不是默认执行者。

| 模式 | 触发条件 | 行为 |
|------|---------|------|
| **AgentLab API Coder（默认目标）** | Coder profile 解析到 `qwen-coder`，且 `DASHSCOPE_API_KEY` 可用 | AgentLab 调 DashScope/Qwen Coder 生成 patch proposal 或结构化 edit block，按策略应用/等待审批。 |
| **External IDE Coder（显式）** | `AGENTLAB_EXTERNAL_CODER=1`、run_dir 中存在 `EXTERNAL_CODER_READY`，或用户明确要求 IDE 接管 | AgentLab 生成完整 handoff，外部 AI 只执行 Supervisor 批准范围内的 Coder 阶段。 |
| **Manual Rescue（救援）** | provider 缺失、配额不足、模型不可用，且用户明确授权 | 外部 IDE AI 可以临时代替某个阶段，但必须在工件中标明 `backend: external_ide_manual`，不能伪造成 API 调用。 |

### 外部 IDE 的默认职责

外部 IDE AI 接到用户任务时，默认做以下动作：

1. 创建/更新 `user_request.md`
2. 运行 `prepare --write-plan`
3. 按 `workflow_plan.yml` 启动 AgentLab agent/API
4. 遇到 `USER_DECISION_REQUIRED.md` 时向用户转述决策
5. 任务结束后运行 artifact/lifecycle/harness/model doctor 等验收命令
6. 只向用户反馈结论、风险、缺口和关键文件路径

**CLI 安全护栏**：`./agentlab.sh run-agent Coder --execute` 在 provider 为 `external_ide_ai` 时必须阻断自动执行并写 handoff。显式指定 `--provider qwen-coder`、`--provider qwen`、`--provider qwen3` 或 `--provider deepseek` 才可使用 API fallback。

---

## 标准流程（7 步）

### 步骤 0：识别触发

用户消息包含以下任一信号时，启动 AgentLab：

| 信号 | 示例 |
|------|------|
| 明确提及 AgentLab | "用 AgentLab 做..." |
| 多文件/跨模块改动 | "重构整个认证模块" |
| 需要分工协作 | "帮我规划然后实现..." |
| 附带文档/规格书 | 用户粘贴长文档或需求说明 |
| 明确说 task | "帮我做一个任务..." |
| Codex Plus 接管信号（见上节） | 审查/修改 AgentLab 自身源码或配置 |

**不触发**：单文件小修改、问答、解释代码、简单的"帮我写个函数"。

用户一句话就能触发：只需说"用 AgentLab"。

---

### 步骤 1：收集任务信息，写入 user_request.md

从用户输入中提取，不要自行补充需求分析：

```markdown
# User Request

## 自然语言任务描述
[用户的原始任务描述，逐字复制或精准摘要]

## 附加文档（如有）
[用户提供的规格、要求、上下文文档，原样保留]

## 约束条件（用户明确说的）
[仅提取用户明确提到的约束，不要自行推断]
```

**token 节省规则**：
- 不添加分析、不评估难度、不猜测范围
- 如果用户提供了长文档，原样放入 `## 附加文档` 区域
- 如果用户只给了一句话，就只写一句话

---

### 步骤 2：初始化任务

```bash
# 找到下一个可用 task_id
ls projects/<ProjectName>/runs/ | sort | tail -1
# 例如输出 task_0006 → 下一个用 task_0007

# 创建任务文件夹和占位报告
./agentlab.sh init-task \
  --project <ProjectName> \
  --task-id task_0007 \
  --request-file projects/<ProjectName>/runs/task_0007/user_request.md
```

> 注意：`init-task` 不会覆盖已有文件。如果 user_request.md 已由你写好，用 `--request-file` 直接引用；否则用 `--request-text`。

---

### 步骤 3：生成工作流计划

```bash
./agentlab.sh prepare \
  --project <ProjectName> \
  --task-id task_0007 \
  --write-plan
```

这一步是**纯本地操作**，不调任何模型 API。输出 `workflow_plan.yml`，包含：
- 路由决策（哪些 agent 参与）
- Token 预算
- 验证门禁
- 缺失的输入文件

**你只需确认**：输出没有报错，`missing_inputs` 为空或可控。

---

### 步骤 3.5：选择执行模式 ⚠️ 必须向用户确认

`workflow_plan.yml` 生成后，在执行 agent 之前，**你必须向用户确认执行模式**。

AgentLab 现在支持两种流水线执行模式：

| 模式 | CLI 命令 | 行为 | 费用 | 适用场景 |
|------|---------|------|------|---------|
| **🔍 Dry-Run（默认安全）** | `run-pipeline --dry-run` | 走完完整的 14 节点生命周期，但全部使用假数据（fake provider），不调任何 LLM API | **零费用** | 验证路由正确性、artifact 完整性、生命周期闭环；首次运行建议先用 dry-run |
| **⚡ Execute（自动执行）** | `run-pipeline --execute` | 走完完整的 14 节点生命周期，每个 agent 节点真正调用配置的模型 API（Supervisor→DeepSeek, RepoScout→Qwen, Coder→Qwen Coder 等） | **按 API 调用计费**（DeepSeek + Qwen token 消耗） | 正式执行任务，一次性自动跑完整个流水线 |

#### Dry-Run 模式下流水线自动完成的内容：

- 14 个生命周期节点全部标记 completed
- 每个 agent 报告写入占位内容（标明 `fake_provider`）
- artifact 完整性检查、self-check、sync 标记
- `lifecycle.yml`、`progress.yml`、`state.yml`、`task_card.yml` 全部写入

#### Execute 模式下流水线自动完成的内容：

Dry-Run 的全部内容 + 每个 agent 节点真正调用 LLM API 产出实际报告。遇到以下情况时流水线**自动暂停**：

| 暂停原因 | 触发条件 | 后续操作 |
|---------|---------|---------|
| `blocked_user_decision` | Agent 需要用户做出 yes/no 决策 | 读取 `USER_DECISION_REQUIRED.md`，向用户转述问题，用户回答后 resume |
| `fallback_handoff` | Provider 不可用（如 DeepSeek API 挂了） | 读取 `codex_fallback_<Agent>.md`，告诉用户，询问是否切换 provider 或手动接管 |

暂停的任务可通过以下命令恢复：
```bash
./agentlab.sh task-resume --project <ProjectName> --task-id <task_id>
```

#### ⚠️ 外部 AI 强制性规则：必须先问用户

在 `prepare --write-plan` 之后、任何 agent 执行之前，**你必须用以下话术询问用户**（不可跳过）：

```
AgentLab 工作流计划已生成：
  路由：Supervisor → RepoScout → ... → Archivist
  Token 预估预算：约 XXXX tokens
  项目体量：L1/L2/L3

请选择执行模式：
  🔍 Dry-Run（推荐先用）：零费用，验证流水线闭环是否完整
  ⚡ Execute：真正调 LLM API，预计产生 token 费用

你想用哪种模式？
```

**用户选择后**，执行对应命令：

```bash
# Dry-Run 模式
./agentlab.sh run-pipeline --project <ProjectName> --task-id <task_id> --dry-run

# Execute 模式
./agentlab.sh run-pipeline --project <ProjectName> --task-id <task_id> --execute
```

> `run-pipeline` 一次性自动完成所有 agent 的执行，**取代**下面步骤 4-7 的手动逐个 `run-agent` 接力。步骤 4-7 的手动方式仍然可用（用于需要精细控制的场景），但默认推荐 `run-pipeline`。

---

### 步骤 4（手动方式）：按顺序执行大脑层 Agent

> ⚠️ 如果你已通过步骤 3.5 使用 `run-pipeline --execute` 自动执行，则跳过步骤 4-7，直接用步骤 7 验收即可。以下手动方式适用于需要精细控制每个 agent 的场景。

`workflow_plan.yml` → `route.agents` 列表决定了执行顺序。按顺序逐个执行，**Coder 跳过**（见步骤 5）。

```bash
# 对 route.agents 中的每个 agent（除了 Coder），按顺序执行：

./agentlab.sh run-agent <AgentName> \
  --project <ProjectName> \
  --task-id task_0007 \
  --execute
```

执行顺序一般为：

```
Supervisor → RepoScout → Researcher(如有) → InterfaceMapper(如有) → [Coder 暂停] → TesterAuditor → Archivist
```

每个 `run-agent --execute` 会调用 API，产生 token 费用。

**你需要在每步之后检查**：

| 返回状态 | 含义 | 处理方式 |
|----------|------|---------|
| `completed` | 正常完成，报告已写入 | 继续下一个 agent |
| `blocked_user_decision` | 需要用户决策 | 阅读 `USER_DECISION_REQUIRED.md`，在对话中询问用户 yes/no，将答案传回 |
| `fallback_handoff` | API 不可用，生成了 handoff 文件 | 读取 `codex_fallback_<Agent>.md`，**停下来告诉用户**，询问是否切换 provider |

**token 节省规则**：
- 只读取报告的关键结论（summary、risks、next_steps），不读全文
- 如果一切正常，回复用户只需："AgentLab <AgentName> 完成，继续执行 <next_agent>"
- 不要把报告内容复制给用户看，除非用户要求

---

### 步骤 5：Coder 阶段——Codex Plus 出手

当轮到 Coder 时，**不要**执行 `run-agent Coder --execute`（Coder 的默认 profile 是 `external_ide_coder`，CLI 会自动阻断）。

**只有 Codex Plus 可执行此阶段。** 如果你不是 Codex Plus，跳过此步骤，用 `--provider qwen` 调 API。

**Codex Plus 充当 Coder**，按以下约束工作：

1. **读取上下文**（只读需要的文件）：
   - `supervisor_plan.md` → 确认可编辑文件列表和验收标准
   - `reposcout_report.md` → 了解仓库结构
   - `interface_map.md`（如有）→ 了解接口边界
   - `workflow_plan.yml` → 确认 token 预算和门禁

2. **执行编辑**：
   - 只编辑 Supervisor 明确批准的文件
   - 遵守 `shell_policy: non_destructive_only`
   - 每完成一个逻辑改动就记录

3. **写 `implementation_report.md`**，包含：
   ```markdown
   # Implementation Report
   ## Changed Files
   [文件列表]
   ## Commands Run
   [实际执行的命令]
   ## Backend
   codex_plus_manual
   ## Unresolved Risks
   [如有]
   ```

4. **记录事件**：
   ```bash
   ./agentlab.sh log-event \
     --project <ProjectName> \
     --task-id task_0007 \
     --agent Coder \
     --summary "简要实现摘要" \
     --files-changed "逗号分隔的文件列表" \
     --commands-run "逗号分隔的命令"
   ```

**token 节省规则**：
- 你的编辑过程不需要向用户解释细节，只管做
- 完成后一句话告知："实现完成，文件变更已写入 implementation_report.md"
- 如果有 `USER_DECISION_REQUIRED.md`（例如 Codex 配额不足），立即暂停并询问用户

---

### 步骤 6：继续大脑层（TesterAuditor + Archivist）

Coder 完成后，继续执行剩余的大脑层 agent：

```bash
./agentlab.sh run-agent TesterAuditor --project <ProjectName> --task-id task_0007 --execute
./agentlab.sh run-agent Archivist --project <ProjectName> --task-id task_0007 --execute
```

**如果 TesterAuditor 发现问题**：读取 `audit_report.md` 的 `## Outputs` 部分：

- 如果看到 `RECOMMEND CODER RE-ENTRY`：读取 fix items，**自动回到步骤 5（Coder 阶段）**逐项修复，修复后重新执行 TesterAuditor。循环直到 `READY FOR ARCHIVIST`。最多 3 轮，超过则询问用户。
- 如果看到 `READY FOR ARCHIVIST`：继续执行 Archivist。

---

### 步骤 7：完成确认

```bash
./agentlab.sh status --project <ProjectName> --task-id task_0007
```

给用户简短总结：

```
✅ AgentLab task_0007 完成
  路由：Supervisor → RepoScout → Coder → TesterAuditor → Archivist
  变更文件：xxx, yyy
  审计结果：[通过 / 有 n 个低风险项]
  Token 消耗：约 xxxx
```

---

## 快捷入口：一键启动

如果用户的消息非常清晰（任务描述 + 明确范围），你可以跳过步骤 1-4 的手动拆分，直接写入文件并调用：

```bash
# 一口气完成 init + prepare
./agentlab.sh init-task --project <Project> --task-id <task_id> --request-file <path>
./agentlab.sh prepare --project <Project> --task-id <task_id> --write-plan
```

然后立刻开始 `run-agent Supervisor --execute`。

---

## 特殊情况处理

### 用户附带长文档

1. 将文档内容完整放入 `user_request.md` 的 `## 附加文档` 区域
2. 不做摘要、不做分析——让 Supervisor 自己去理解
3. 其余流程不变

### DeepSeek 不可用

`run-agent --execute` 返回 `fallback_handoff` 时：

1. 读取 `codex_fallback_<Agent>.md`
2. 告诉用户："AgentLab 大脑（DeepSeek）当前不可用，无法执行 <Agent>。是否由我临时代替该角色？"
3. 等用户确认后再继续

### 用户决策

当 `USER_DECISION_REQUIRED.md` 出现时：

1. 读取该文件
2. 将问题用简洁中文转述给用户（带默认建议）
3. 用户回答后，继续执行

### Token 预算告警

`brain-status` 显示某个 agent `state: continue_with_warning` 时：
- 不中断，继续执行
- 在最终总结中提及："注意：<Agent> 接近 token 预算上限"

### Token 预算超限

`state: ask_user` 时：
- 立即暂停
- 告诉用户哪个 agent 超了、超了多少
- 等用户决定是继续还是缩减范围

---

## AgentLab 自身维护：Bug 反馈与调试闭环

> ℹ️ AgentLab 本身是软件项目，execute 模式需要长期维护。当外部 AI 发现 AgentLab 自身的衔接问题、API 调用异常或逻辑 bug 时，必须遵循本条规则进行诊断和记录。

### 何时触发 AgentLab 自身调试

以下信号出现时，外部 AI 应进入 AgentLab 自身调试模式：

| 信号 | 示例 |
|------|------|
| 流水线卡在某个节点不推进 | `run-pipeline` 返回 `"status": "paused"` 但无明显原因 |
| 生命周期节点状态不一致 | `lifecycle-status` 显示某节点标记 completed 但报告文件不存在 |
| API 调用返回意外状态 | `run-agent --execute` 返回不属于 `completed`/`blocked_user_decision`/`fallback_handoff` 的状态 |
| artifact check 反复失败 | `artifact-check` 出现同样的 missing files 即使 agent 已执行 |
| 报告内容被写入错误位置 | 某个 agent 的报告写到了不匹配的路径 |
| CLI 命令报 Python 异常 | `run-pipeline --execute` 抛出未捕获的 traceback |

### 调试档物清单（外部 AI 必须阅读的档）

进入调试模式后，按顺序读取以下文件来诊断问题：

```text
1. pipeline_error.log                    ← 流水线引擎记录的错误（可能不存在）
2. lifecycle.yml                         ← 逐个检查每个 node 的 status + error 字段
3. progress.yml                          ← 检查各 agent 的 provider_status 和 incidents
4. state.yml                             ← 检查 status / current_agent / blocked 字段
5. provider_incidents.yml                ← 查看 API 失败记录（可能不存在）
6. resume_plan.yml                       ← 查看上次暂停的原因和允许恢复的 provider
7. run_task.py / pipeline_runner.py / agent_runner.py / llm_provider.py
                                         ← 关键源码，理解断点处的代码逻辑
```

### 诊断流程（外部 AI 必须执行）

```
① 读取调试档物清单中的文件（按顺序）
    │
② 定位问题节点/阶段
    │
    ├── 是代码逻辑问题（pipeline_runner / agent_runner / llm_provider）？
    │   ├── 读对应源码，理解预期行为 vs 实际行为
    │   ├── 记录到 bug 反馈档（见下节）
    │   ├── 修复源码（如果确认是 AgentLab 自身的 bug）
    │   └── 修复后重新执行失败的节点
    │
    ├── 是配置问题（API key 缺失 / provider 配置错误）？
    │   ├── 读 config/ 下对应 YAML
    │   ├── 记录到 bug 反馈档
    │   └── 修正配置或告知用户
    │
    └── 是外部因素（API 配额不足 / 网络问题）？
        ├── 告知用户
        └── 记录到 bug 反馈档（标注为 external）
```

### Bug 反馈档：`BUG_REPORT.md`

每次发现 AgentLab 自身问题时，外部 AI 必须在 `projects/AgentLab/docs/` 下创建或追加 `BUG_REPORT.md`，格式如下：

```markdown
### [YYYY-MM-DD HH:MM] - task_xxxx - <Agent/Component>

**发现者**：外部 IDE AI（执行 task_xxxx 时触发）

**问题节点/阶段**：<lifecycle_node / agent_name / CLI 命令>

**症状**：
<实际行为描述，包含错误消息、返回状态>

**预期行为**：
<按照 AgentLab 设计，应该发生什么>

**调试档内容摘要**：
<从 lifecycle.yml / progress.yml / state.yml 等相关档中摘录的关键信息>

**根因分析**：
<外部 AI 的初步诊断结论>

**修复措施**：
<对源码或配置做的是什么修改，文件名 + 行号>

**验证结果**：
<修复后重新运行的结果>

**后续建议**：
<是否需要重构、是否需要增加自动化测试、是否需要更新协议>
```

### 调试记录的强制性规则

1. **读档必写**：你读了调试档物清单中的任何文件，就必须在 `BUG_REPORT.md` 中留下记录（哪怕最后发现不是 bug，也要写一条 `结论: 非bug，原因: ...`）
2. **改码必记**：修改了 `agent_runtime/` 下任何 `.py` 文件，必须记录文件名、行号和修改原因
3. **不可只说"已修复"**：必须有验证结果（重新运行命令后的输出摘要）
4. **长期维护视角**：每条记录末尾考虑"是否需要补充单元测试"、"是否需要更新协议/README"

### 外部 AI 的责任边界

- ✅ 可以：阅读 `pipeline_error.log` / `lifecycle.yml` / `state.yml` 等调试档
- ✅ 可以：阅读 `agent_runtime/*.py` 源码理解逻辑
- ✅ 可以：修改 `agent_runtime/*.py` 修复 bug
- ✅ 可以：修改 `config/*.yml` 修正配置
- ✅ 必须：将诊断和修复过程写入 `BUG_REPORT.md`
- ❌ 不可：修复 AgentLab 自身 bug 时不写 `BUG_REPORT.md`
- ❌ 不可：将 AgentLab 自身修复伪装成正常任务工件

---

## 禁止事项

- ❌ 代替 Supervisor 做路由决策
- ❌ 代替 RepoScout 做仓库分析
- ❌ 代替 TesterAuditor 做代码审查（除非 DeepSeek 不可用且用户明确授权）
- ❌ 跳过 `workflow_plan.yml` 直接开始编码
- ❌ 在没有 Supervisor 批准文件列表的情况下编辑源码
- ❌ 将 AgentLab 报告全文复制到对话中（除非用户要求）
- ❌ 伪造 token 消耗数据
- ❌ 把你自己（外部 AI）的推理过程写入 AgentLab 报告
- ❌ 非 Codex Plus 环境（cline/DeepSeek/Claude）执行 Coder 阶段的文件编辑
- ❌ 修复 AgentLab 自身 bug 时不写 `BUG_REPORT.md`
- ❌ 将 AgentLab 自身修复伪装成正常任务工件

---

## Codex Full-Driver 模式

从 v1.4 开始，AgentLab 支持两种 Codex 模式：

### codex_coder_only（原有）
API agents（DeepSeek 等）负责全部规划、审查和归档工作，Codex 仅执行 Coder 阶段的代码编辑和命令运行。

```
API agents → 规划/审查/归档
Codex → 文件编辑/命令执行
```

### codex_full_driver（新增）
当用户有 Codex 额度可用时，Codex 可临时执行所有 AgentLab 角色，但必须将每个角色的输出写入独立的本地工件文件。AgentLab 的本地文件仍然是唯一真理源。

```
Codex acting as Supervisor → RepoScout → Researcher → InterfaceMapper →
CodexPromptGenerator → Coder → TesterAuditor → Archivist
```

关键规则：
1. **角色分离**：每个角色必须产生独立文件，禁止将多个角色合并为一个未归档的聊天响应。
2. **工件完整性**：所有报告、决策、diff、checkpoint 和交接状态必须写入本地 `projects/<Project>/runs/<task_id>/`。
3. **交接包**：任务暂停或完成时必须创建 `handoff_packet.yml`，含完整的恢复说明。
4. **自检**：GitHub push 前必须通过 `codex-verify-artifacts` 自检。
5. **Codex → API 恢复**：通过 `./agentlab.sh continue-with-api` 使用 API agents 继续执行。

详见完整规范：`docs/AGENTLAB_CODEX_FULL_DRIVER_OPERATION_CHAIN_SPEC.md`

---

## 双端协作与同步协议 (Dual-End Collaboration and Sync Protocol)

从 v1.6 开始，AgentLab 引入了双端协作与数据同步协议，以支持本地（开发环境）与云端（运行/部署环境）之间的无缝协作，同时保持两者技能、MCP 服务以及运行记忆能力同步更新：

本节只描述同步链路。正式协作前的 peer discovery、角色分工、准确调用命令、
Skill/MCP/Tool 成本路由、显式点名委派和证据归属，统一服从
`_shared/AGENT_PROTOCOL.md`。任何新端点（包括 69 本地化端）必须先在
`config/shared_agent_directory.yml` 完成能力盘点和同伴登记，才能接收正式任务。

### 1. 物理链路拓扑 (Network Topology)
*   **本地开发端 (Local Mac)**：作为主开发环境和 Codebase/配置的源头真理（Source of Truth）。
*   **资源交换中转站 (Relay Hub)**：`<RELAY_HOST>:<RELAY_SSH_PORT>`，底座路径为 `<RELAY_WORKSPACE>/AgentLab/`。负责接收本地的备份更新，并作为中转站将数据分发给云端部署服务器。
*   **Cloud Runtime (Cloud Server)**：云端部署服务器 `<CLOUD_RUNTIME_HOST>`。作为任务运行/部署环境，可以直接通过 SSH 从本地直连，并配置了通过密钥连接至 Relay Hub 的快捷别名。

### 2. 双向同步流程 (Sync Workflow)
*   **本地 -> 中转站 (Relay Push)**：本地代码、定制 `skills/`、`config/` 或记忆库有更新时，在本地执行：
    `./agentlab.sh relay-sync --execute`
    或手动同步全部结构：
    `rsync -avz -e "ssh -p <RELAY_SSH_PORT>" --exclude '__pycache__' --exclude '.pytest_cache' --exclude '.venv' --exclude 'node_modules' /path/to/AgentLab/ <RELAY_SSH_USER>@<RELAY_HOST>:<RELAY_WORKSPACE>/AgentLab/`
*   **中转站 -> 云端部署端 (Remote Pull)**：云端 `<CLOUD_RUNTIME_HOST>` 通过 `rsync` 自动拉取 Relay Hub 中的最新快照进行同步更新：
    `ssh <CLOUD_SSH_USER>@<CLOUD_RUNTIME_HOST> "rsync -avz --exclude '__pycache__' --exclude '.pytest_cache' <RELAY_HOST>:<RELAY_WORKSPACE>/AgentLab/ <CLOUD_WORKSPACE>/AgentLab/"`
*   **云端 -> 中转站 -> 本地 (Remote Pullback)**：云端执行产生的 Task 运行记录、事件日志和内存变更，会在任务归档时先同步推送到 Relay Hub，本地拉回后自动对齐，从而保持双端环境下的 MCP、技能以及记忆的完美一致。

---

## 版本

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.6 | 2026-06-20 | 新增双端协作与同步协议，定义 Local Workstation -> Relay Hub (`<RELAY_HOST>`) -> Cloud Runtime (`<CLOUD_RUNTIME_HOST>`) 三点一线式的代码、MCP服务、Skills 与记忆快照同步规范 |
| 1.5 | 2026-06-02 | 新增 `run-pipeline --execute` 全自动流水线模式；新增步骤 3.5 强制用户确认执行模式（dry-run vs execute）；新增「AgentLab 自身维护：Bug 反馈与调试闭环」章节，定义 `BUG_REPORT.md` 长期维护机制 |

| 1.4 | 2026-05-31 | 新增 codex_full_driver 模式定义和工件规则 |
| 1.3 | 2026-05-30 | 收紧 Coder 接管范围：仅限 Codex Plus（有额度），排除 cline/DeepSeek/Claude 等 |
| 1.2 | 2026-05-30 | 新增 Coder 模式切换规则（Codex Plus 接管 / Qwen Fallback）；新增 IDE 自动信号检测；CLI 增加 Coder handoff 阻断护栏 |
| 1.1 | 2026-05-30 | 新增竞品研究关键词触发 Researcher；新增交互式需求澄清规则；新增 Tester→Coder 自动修复循环（最多3轮）；Researcher 模板支持竞品分析 |
| 1.0 | 2026-05-30 | 初始协议，覆盖标准 7 步流程 + 特殊情况处理 |
