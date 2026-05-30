# AgentLab 外部 AI 驱动协议

> **适用对象**：Codex Plus、Claude、或其他 IDE 内置 AI
> **你的角色**：轻量中继——收取自然语言任务 → 交给 AgentLab 大脑分发 → 必要时执行 Coder 阶段
> **目标**：每步消耗尽可能少的 token，不替代 AgentLab 的大脑层

---

## 核心原则

```
你（外部AI）      AgentLab 大脑（DeepSeek）      AgentLab 执行（Codex Plus / Qwen API）
───────────      ─────────────────────────      ─────────────────────────────────
收任务、写文件    规划、路由、分派、审查            实际写代码、编辑文件、跑命令
薄薄一层          所有思考工作                    只在你接管 Coder 阶段时介入
```

- 你 **不做** 任务规划、架构分析、范围评估——那些是 Supervisor 的活
- 你 **不做** 代码审查——那是 TesterAuditor 的活
- 你只在 **Coder 阶段** 实际编辑文件，以及遇到 `USER_DECISION_REQUIRED` 时询问用户

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

### 步骤 4：按顺序执行大脑层 Agent

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

每个 `run-agent --execute` 会调用 DeepSeek API，产生 token 费用。

**你需要在每步之后检查**：

| 返回状态 | 含义 | 处理方式 |
|----------|------|---------|
| `completed` | 正常完成，报告已写入 | 继续下一个 agent |
| `blocked_user_decision` | 需要用户决策 | 阅读 `USER_DECISION_REQUIRED.md`，在对话中询问用户 yes/no，将答案传回 |
| `fallback_handoff` | DeepSeek 不可用，生成了 handoff 文件 | 读取 `codex_fallback_<Agent>.md`，**停下来告诉用户**：DeepSeek 不可用，是否由你模拟该 agent |

**token 节省规则**：
- 只读取报告的关键结论（summary、risks、next_steps），不读全文
- 如果一切正常，回复用户只需："AgentLab <AgentName> 完成，继续执行 <next_agent>"
- 不要把报告内容复制给用户看，除非用户要求

---

### 步骤 5：Coder 阶段——你出手

当轮到 Coder 时，**不要**执行 `run-agent Coder --execute`（Coder 的 provider 是 `codex_plus_manual`，不会调 API）。

**你来充当 Coder**，按以下约束工作：

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

**如果 TesterAuditor 发现问题**：把 `audit_report.md` 的关键发现告诉用户，询问是否修复。如用户要修复，回到步骤 5（Coder 阶段）。

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

## 禁止事项

- ❌ 代替 Supervisor 做路由决策
- ❌ 代替 RepoScout 做仓库分析
- ❌ 代替 TesterAuditor 做代码审查（除非 DeepSeek 不可用且用户明确授权）
- ❌ 跳过 `workflow_plan.yml` 直接开始编码
- ❌ 在没有 Supervisor 批准文件列表的情况下编辑源码
- ❌ 将 AgentLab 报告全文复制到对话中（除非用户要求）
- ❌ 伪造 token 消耗数据
- ❌ 把你自己（外部 AI）的推理过程写入 AgentLab 报告

---

## 版本

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.0 | 2026-05-30 | 初始协议，覆盖标准 7 步流程 + 特殊情况处理 |