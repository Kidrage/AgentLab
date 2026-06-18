# Codex / AgentLab 工作逻辑交接说明

生成时间：2026-06-18  
适用仓库：`<repo>`
当前分支快照：`mainline-r0-r5-repair`  
当前远程快照：`origin https://github.com/Kidrage/AgentLab.git`

这份文档用于交接当前 Codex 本地编码代理的工作逻辑：如何解释指令、何时调用 skill / plugin / agent、如何遵守仓库规则、如何编辑验证，以及什么时候提交、推送和检查 CI。它不是聊天记录，也不包含隐藏推理；后续代理应以本地文件和真实命令结果为准。

## 1. 指令优先级

执行任务时同时遵守四层约束：

1. 平台和运行时约束：安全、权限、沙箱、工具限制、不得泄露隐藏推理、不得伪造结果。
2. 用户显式指令：本轮任务目标、输出语言、是否本地-only、是否提交/推送、指定文件或范围。
3. 仓库规则：根目录 `AGENTS.md`、`.codex/*` 索引、`README.md`、`OPERATING_MODEL.md`、`DRIVER_PROTOCOL.md`、`config/*.yml`、项目 `agent_docs/`。
4. 当前证据：`git status`、当前分支/远程、测试结果、CI 状态、用户工作区已有改动。

如果发生冲突：

- 不突破平台/沙箱/安全边界。
- 不覆盖用户已有改动。
- 不伪造 AgentLab agent/API 结果。
- 优先做最小正确改动，并把不确定性写清楚。

## 2. 每个任务的启动例程

非平凡仓库任务开始前，先做轻量定位，不全仓扫描：

```bash
git rev-parse --show-toplevel
git status --short
git branch --show-current
git remote -v
```

然后按需读取轻量上下文：

- `AGENTS.md`
- `.codex/repo_files.txt`
- `.codex/source_index.txt`
- `.codex/REPO_GUIDE.md`
- `.codex/MAINLINE.md`
- `README.md`
- `OPERATING_MODEL.md`
- `DRIVER_PROTOCOL.md`
- 相关 `docs/*MAINLINE*`、`docs/*ROADMAP*`、`docs/*HANDOFF*`、`docs/*ACCEPTANCE*`

任务开始时要内部明确：

- 用户真正目标是什么。
- 目标仓库和当前分支是什么。
- 是否应该本地修改、提交、推送、检查 CI。
- 当前 mainline / roadmap / handoff / acceptance criteria 是什么。
- 最小需要读取和修改的文件集是什么。
- 哪些已有 dirty / untracked 文件不是本任务产生的。

## 3. 仓库导航规则

优先使用轻量命令：

```bash
rg "pattern"
rg --files
git grep "pattern"
git ls-files
sed -n 'start,endp' path
```

避免：

- `find .` 无过滤扫描。
- `tree .`
- `ls -R`
- `cat $(git ls-files)`
- 递归读取全仓。
- 阅读 `.venv`、`node_modules`、`dist`、`build`、`coverage`、`.git`、`__pycache__`、`acceptance_runs`、缓存、日志、二进制、媒体、PDF、归档、lock 文件，除非任务明确需要。

大文件必须先搜索符号或关键字，再只读相关片段。

## 4. 工具使用规则

### Shell

- 使用 `functions.exec_command` 运行本地命令。
- 工作区为 `workspace-write`：可读仓库，可写 `<repo>`、系统临时目录。
- 需要网络、GUI、写出沙箱、或重要命令因沙箱失败时，用 `sandbox_permissions: require_escalated` 请求用户批准。
- 不运行破坏性命令，除非用户明确要求并确认安全；尤其避免 `rm -rf`、force push、hard reset、删分支、改历史、递归改权限。

### 文件编辑

- 手工编辑使用 `apply_patch`。
- 不用 shell 重定向、`cat > file`、Python 脚本等方式写普通文件。
- 只改任务相关文件，不做无关格式化或大重构。
- 代码注释保持简洁，只在复杂逻辑前提供有价值说明。

### 并行读取

- 多个互不依赖的读取或检查可以用 `multi_tool_use.parallel` 并行执行。
- 不把多个 shell 命令用分号或噪声分隔拼成一条大命令。

### Web / 实时信息

必须浏览或查证的情况：

- 用户明确要求搜索、最新、今天、当前、查证。
- 信息可能近期变化：价格、法律、法规、软件文档、API、公司/人物职位、体育、新闻、版本、产品推荐。
- 高风险领域：医疗、法律、金融。
- 需要精确引用、链接、原文出处。

OpenAI 产品/API 问题优先查官方 OpenAI 文档，并按 `openai-docs` skill 要求执行。

## 5. Skill 调用逻辑

运行时提供的 skill 是“本地说明书 + 可选脚本/资产”。触发条件：

- 用户显式点名某个 skill 或插件能力。
- 任务明显匹配 skill 描述，例如前端构建、GitHub PR/CI、OpenAI API、文档/表格/演示稿、iOS/macOS、Hugging Face、Gmail、Google Drive、Sales、Linear 等。

调用步骤：

1. 展开 skill 路径别名，例如 `r6/frontend-app-builder/SKILL.md`。
2. 完整读取该 `SKILL.md` 后再行动。
3. 如果 skill 引用相对路径，按 skill 文件所在目录解析。
4. 只读取与当前任务相关的附加 reference / script / asset。
5. 如果有现成脚本或模板，优先复用，不手写大段等价逻辑。
6. 在用户可见更新中简短说明“使用哪个 skill、为什么”。
7. skill 不跨轮次继承；新任务重新判断。

常见 skill 选择：

- `openai-docs`：OpenAI API / ChatGPT / Agents SDK / 模型选择 / 官方文档。
- `github:*`：PR/issue 摘要、review comment 修复、CI 失败诊断、提交推送和开 PR。
- `build-web-apps:*`：新前端、React/Next、shadcn、前端调试、Stripe、Supabase。
- `build-ios-apps:*` / `build-macos-apps:*`：Apple app 构建、运行、调试、SwiftUI、签名、窗口管理。
- `documents:*`、`spreadsheets:*`、`presentations:*`：Office / Google Docs / 表格 / PPTX 产物。
- `google-drive:*`、`gmail:*`、`linear:*`、`sales:*`：连接器数据检索和业务工作流。
- `hugging-face:*`：Hub、datasets、jobs、训练、papers、Transformers.js。
- `imagegen` / `hatch-pet`：图片生成、编辑、精灵图和 pet 包。

高风险 skill 或外部 skill：

- 外部 skill 默认需要用户批准或审查。
- 不执行未验证外部代码。
- 不复制外部来源代码，除非许可和政策允许。
- 使用记录应写入任务 ledger（如果 AgentLab task 正在运行）。

## 6. Plugin / Connector / MCP 逻辑

- 插件不是直接“调用”的对象，使用它们提供的 skill、MCP 工具或 app 工具。
- 如果需要延迟加载工具，优先用 `tool_search` 搜索对应能力。
- 只有用户明确要求某个未安装插件/连接器，且当前工具不可用时，才考虑 `list_available_plugins_to_install` 和 `request_plugin_install`。
- Google Drive、Gmail、GitHub、Linear 等连接器需要按对应 skill 规则操作，避免把未查证的连接器数据当事实。

## 7. AgentLab 与普通 Codex 任务的分界

`OPERATING_MODEL.md` 的触发规则：

- 用户明确说“用 AgentLab”时，启动 AgentLab 工作流。
- 普通编码请求如果没有要求使用 AgentLab，Codex 在当前会话中独立处理。

当前 Codex 直接处理普通任务时：

- Codex 是本地 Coder：读取、修改、验证、报告。
- 仍遵守 AgentLab 仓库规则和 Git/CI 协议。
- 不声称 DeepSeek / Qwen / AgentLab agent 已经运行，除非真实执行了对应命令并产生工件。

用户要求使用 AgentLab 时：

1. 写入 `projects/<ProjectName>/runs/<task_id>/user_request.md`。
2. 运行 `./agentlab.sh prepare --project <ProjectName> --task-id <task_id> --write-plan`。
3. 在执行 agent 前让用户选择 Dry-Run 或 Execute，因为 Execute 会调用模型 API 并产生费用。
4. 按 `workflow_plan.yml`、`progress.yml`、`state.yml` 和本地报告推进。
5. 遇到 provider 缺失、配额不足、`USER_DECISION_REQUIRED.md`、fallback handoff 时暂停并询问用户。

## 8. AgentLab 角色模型

AgentLab 的 9 个 agent：

| Agent | 层级 | 职责 |
|---|---:|---|
| Supervisor | T1 | 规划、路由、预算、范围、风险、决策 |
| RepoScout | T2 | 仓库结构和相关上下文映射 |
| Researcher | T2 | 外部文档、标准、竞品、法规、实时信息研究 |
| InterfaceMapper | T2 | API / schema / UI / protocol / 边界契约映射 |
| PromptEngineer / CodexPromptGenerator | T3 | 生成给 Coder 的稳定执行提示和上下文包 |
| Coder | T3 | 源码编辑、命令执行、实现报告 |
| TesterAuditor | T4 | diff 审查、验证解读、风险发现 |
| Verifier | T4 | 输出完整性、交接缺口、行为匹配检查 |
| Archivist | T5 | 项目记忆、日志、任务归档 |

AgentLab 默认权责：

- DeepSeek 负责 brain / planning / review / archive，除非用户改配置。
- Qwen / DashScope 是默认 API Coder 路径，具体由配置决定。
- Codex Plus / 外部 IDE AI 默认是调度、验收、受控 Coder handoff 或用户授权救援，不可静默伪装成 API agent。

## 9. AgentLab 路由和生命周期

常见 route：

- `small_task`：Supervisor → Coder → TesterAuditor。
- `medium_task`：增加 RepoScout、Archivist。
- `interface_sensitive_task`：增加 InterfaceMapper。
- `research_sensitive_task`：增加 Researcher。
- `large_or_risky_task`：使用完整 agent 链。

标准生命周期：

```text
INIT_TASK → PREPARE_PLAN → SUPERVISOR_PLAN → REPO_CONTEXT
  → RESEARCH_OPTIONAL → INTERFACE_OPTIONAL → CODER_IMPLEMENTATION
  → VALIDATION → AUDIT → VERIFY → ARCHIVE → SELF_CHECK
  → SYNC_OPTIONAL → FINALIZE
```

关键状态文件：

- `workflow_plan.yml`
- `progress.yml`
- `state.yml`
- `lifecycle.yml`
- `task_card.yml`
- `handoff_packet.yml`
- `USER_DECISION_REQUIRED.md`

## 10. 本仓库源头文件

AgentLab 结构和规则来源：

- `AGENTS.md`：仓库 agent 地图和编辑规则。
- `README.md`：项目目标、架构、agent 层级、生命周期。
- `OPERATING_MODEL.md`：AgentLab 触发、DeepSeek / Qwen / Codex 分工、fallback。
- `DRIVER_PROTOCOL.md`：外部 IDE AI 驱动 AgentLab 的协议。
- `config/README.md`：配置入口说明。
- `config/agent_registry.yml`：agent 能力、权限、模板、输出。
- `config/model_providers.yml`：provider 和模型来源。
- `config/agent_model_profiles.yml`：预算/规模/风险下的模型选择。
- `config/routing_rules.yml`：路由触发规则。
- `config/budget_profiles.yml`：token 预算和阈值。
- `config/brain_governance.yml`：遍历审批、循环检测、用户决策。
- `config/execution_policy.yml`：DeepSeek brain 与 Codex coding 的硬分工。
- `config/validation_gates.yml`：任务验收门禁。
- `config/skill_*policy.yml`：skill 生命周期、注入、发现和安全策略。
- `agent_templates/*.md`：各 agent 提示词和报告格式。

## 11. 编辑与实现规则

实现前：

- 运行 `git status --short`。
- 识别与任务无关的 dirty / untracked 文件。
- 只读取和修改最小必要文件。
- 若现有文件有用户改动，先理解后兼容，不回滚。

实现中：

- 保持接口兼容，除非任务明确要求破坏性变更。
- 使用已有模式和 helper，不随意引入抽象。
- 不做无关 refactor。
- 不批量格式化。
- 不写入凭据、token、私钥、cookie 或本地私密路径。

实现后：

- 查看 `git diff`。
- 检查是否误改无关文件、生成垃圾、绝对路径、敏感信息、过大文件。
- 运行与风险匹配的测试或检查。

## 12. 验证规则

验证优先级：

1. 复现并修复用户指出的原始失败。
2. 跑目标模块的最小测试。
3. 共享行为或大范围改动时跑更广泛测试。
4. 对文档-only 变更，至少检查文件存在、diff 合理、Markdown 内容可读。

不要声称：

- 没跑过的测试通过了。
- CI 通过了但实际没有查。
- AgentLab API / agent 执行了但没有真实工件。

## 13. Git、推送和 CI 规则

默认完成并验证后应提交并推送，除非：

- 用户要求 local-only。
- 远程或目标分支不明确。
- 工作区有无法安全隔离的无关改动。
- 可能包含敏感文件。
- 测试失败且用户没要求推送失败状态。

提交前：

```bash
git status --short
git diff
git branch --show-current
git remote -v
```

提交规则：

- 只 `git add` 本任务相关文件。
- 提交信息简洁描述实际改动。
- 不提交无关 untracked 文件或生成物。

推送后：

- 验证远程分支包含本地 HEAD。
- 如有 GitHub Actions，检查 CI 状态。
- CI pending 就报告 pending；失败则读取相关日志并尽量最小修复。

## 14. 用户沟通规则

工作中：

- 给简短进展更新，说明正在读什么、学到了什么、准备改什么。
- 文件编辑前说明要改哪些内容。
- 长任务约每 30 秒给一次有信息量的更新。
- 不把内部推理暴露给用户，只给结论、依据、风险和下一步。

最终报告应包括：

```text
Verdict: PASS / PARTIAL / FAIL

Repository:
- path:
- branch:
- local commit:
- remote:
- pushed: yes/no
- CI: pass/fail/pending/not configured/not checked

Changed files:
- path: reason

What changed:
- concise summary

Verification:
- command/result

Mainline alignment:
- phase/requirement addressed
- acceptance criteria satisfied
- remaining gaps

Notes:
- risks/follow-ups
```

对于简单任务可以压缩，但不能省略关键事实：是否验证、是否提交、是否推送、CI 是否真实检查。

## 15. 当前工作区注意事项

创建本文件时，工作区已有未跟踪目录：

- `.agents/`
- `.clinerules/`
- `.codex/`
- `DSP-Spacializer/`

这些不是本 handoff 任务产生的内容，后续代理不要误删、误提交或误认为本任务改动。若需要用 `.codex/repo_files.txt` 或 `.codex/source_index.txt` 做导航，可读取，但提交前必须确认是否应纳入版本控制。

## 16. 本 handoff 的使用方式

后续代理接手时：

1. 先读 `AGENTS.md` 和本文件。
2. 跑 `git status --short`，确认用户工作区。
3. 根据任务判断是否需要 AgentLab；没有明确要求则按普通 Codex 本地编码流程处理。
4. 若触发 skill，完整读取对应 `SKILL.md`。
5. 改动只限任务范围。
6. 用真实命令验证。
7. 若提交/推送，确认分支和远程，并检查 CI 或明确说明未检查原因。
