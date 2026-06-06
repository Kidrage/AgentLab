### [2026-06-02 17:27] - task_0009_scnet-rollback - PipelineRunner

**发现者**：外部 IDE AI（执行 task_0009_scnet-rollback 时触发）

**问题节点/阶段**：`run-pipeline --execute` / lifecycle `SUPERVISOR_PLAN` → `VERIFY`

**症状**：
`run-pipeline --execute` 第一次在 `SUPERVISOR_PLAN` 因 `network_error. Connection error.` 暂停；提权重跑后推进到 `VERIFY` 又因同类网络错误暂停。期间 `RepoScout`、`InterfaceMapper`、`Coder`、`TesterAuditor` 已有 API token 记账，但对应报告文件仍是初始化的 `TBD` 占位内容，导致 lifecycle 显示节点 completed 而报告不可用。

**预期行为**：
execute 模式中，模型调用成功后必须把 `result.content` 写入对应报告文件；模型调用失败或需要用户决策时，必须写出 `blocked_*.md` / `USER_DECISION_REQUIRED.md` 并更新 state，不能留下“已完成但报告为空”的任务状态。

**调试档内容摘要**：
`lifecycle.yml` 显示 `SUPERVISOR_PLAN: failed`、`VERIFY: failed`，但 `REPO_CONTEXT`、`INTERFACE_OPTIONAL`、`CODER_IMPLEMENTATION`、`VALIDATION`、`AUDIT` 为 completed。`state.yml` 显示 `status: blocked`、`current_agent: Verifier`、`last_event: Blocked at VERIFY: network_error. Connection error.`。`progress.yml` 显示当前阶段为 `verifying`，`status: running`。`01_supervisor_plan.md` 和 `06_implementation_report.md` 仍为 `TBD`。`cost_ledger.yml` 记录了多个成功 API 调用。

**根因分析**：
`agent_runtime/pipeline_runner.py` 的 execute 分支调用 `run_agent_model(...)` 后只记录 token 并标记节点完成，没有把 `result.content` 写入 `report_path`。同时 `agent_runtime/agent_runner.py` 调用 `generate_text(...)` 时未传入 `agent_name`、`run_dir`、`project`、`task_id`，导致 provider guard/progress 无法生成完整阻断文件与进度记录。

**修复措施**：
`agent_runtime/agent_runner.py:165` 开始向 `generate_text(...)` 传入 agent/task/run_dir 上下文，并新增 `_role_for_agent(...)`。`agent_runtime/pipeline_runner.py:223` 开始在 blocked/fallback 分支写出阻断文件，在 `agent_runtime/pipeline_runner.py:244` 将成功的 `result.content` 写入报告文件。

**验证结果**：
已运行 `python3 -B -m py_compile agent_runtime/agent_runner.py agent_runtime/pipeline_runner.py`，语法检查通过。

**后续建议**：
补充一个本地 fake LLM 单元测试：execute 分支模拟 `LLMCallResult(status="completed", content="...")` 后断言目标报告不再是 `TBD`，并断言 blocked 分支会写出 `USER_DECISION_REQUIRED.md`。

### [2026-06-02 17:31] - task_0010_scnet-rollback - ProgressTracker

**发现者**：外部 IDE AI（执行 task_0010_scnet-rollback 时触发）

**问题节点/阶段**：`run-pipeline --execute` / lifecycle `SUPERVISOR_PLAN`

**症状**：
修复报告落盘后重新执行干净 task，流水线在 `SUPERVISOR_PLAN` 立即返回 `Final status: error`。`state.yml` 显示 `last_event: Blocked at SUPERVISOR_PLAN: 'provider_status'`，`lifecycle.yml` 显示 `SUPERVISOR_PLAN: failed`，`progress.yml` 只有简化字段 `current_stage/percent/current_agent/status`，缺少完整的 `provider_status` 和 `agents` 结构。

**预期行为**：
pipeline 在调用 provider 前应创建完整的 progress 结构；进度更新函数也应兼容旧任务或半写入任务文件，不应因为缺少 `provider_status` 抛 KeyError。

**调试档内容摘要**：
`progress.yml` 内容为简化结构：`current_stage: planning`、`percent: 20`、`current_agent: Supervisor`、`status: running`。`state.yml` 记录当前 agent 为 Supervisor 且 status 为 blocked。`pipeline_error.log` 不存在，错误只写入 lifecycle/state。

**根因分析**：
`agent_runtime/pipeline_runner.py` 在没有 progress 文件时使用 `{}` 并直接 `save_progress(...)`，绕过了 `create_progress(...)` 的完整结构初始化。`agent_runtime/progress_tracker.py` 的 `mark_agent_started(...)` 直接访问 `data["provider_status"]`，对简化 progress 文件没有防御。

**修复措施**：
`agent_runtime/pipeline_runner.py:79` 开始在 progress 缺失或缺少 `provider_status` 时调用 `create_progress(...)`，并在 `agent_runtime/pipeline_runner.py:132` 写入 `percent_complete`。`agent_runtime/progress_tracker.py:109`、`:128`、`:149` 增加 `setdefault(...)` 防御，`agent_runtime/progress_tracker.py:117` 对 `provider_status` 做兼容初始化。

**验证结果**：
已运行 `python3 -B -m py_compile agent_runtime/agent_runner.py agent_runtime/pipeline_runner.py agent_runtime/progress_tracker.py`，语法检查通过。

**后续建议**：
为 `run_next_node(...)` 增加一个无 progress 文件启动的回归测试，断言第一轮 execute 会创建完整 progress schema，并且 `mark_agent_started(...)` 不会因旧 schema 崩溃。

### [2026-06-02 17:39] - task_0011_scnet-rollback - Agent Output Gate

**发现者**：外部 IDE AI（执行 task_0011_scnet-rollback 时触发）

**问题节点/阶段**：`run-pipeline --execute` / `REPO_CONTEXT`、`CODER_IMPLEMENTATION`

**症状**：
`RepoScout` 报告内容只有一个 `<tool_call>{"shell": "ls -la ..."}</tool_call>` 字符串，说明模型请求执行 shell 读取，但 pipeline 没有执行该工具调用，也没有将节点标为需要外部执行。`Coder` 报告明确写着 “No source edits have been performed yet” 和 “plan-only phase”，但 lifecycle 仍将 `CODER_IMPLEMENTATION` 标记为 completed。

**预期行为**：
如果 agent 输出未形成可用报告、包含未执行的工具调用，或 Coder 明确表示未执行实现，pipeline 应暂停并写出 `USER_DECISION_REQUIRED.md` 或 `codex_fallback_*.md`，而不是将节点标记 completed。

**调试档内容摘要**：
`02_reposcout_report.md` 长度仅 106 bytes，内容为 `<tool_call>`；`06_implementation_report.md` 约 3 KB，但正文说明没有读取文件、没有运行命令、没有修改源码，只是占位报告。`lifecycle.yml` 显示 `REPO_CONTEXT`、`INTERFACE_OPTIONAL`、`CODER_IMPLEMENTATION` 均 completed，随后 `VALIDATION` 因 qwen-flash 网络错误 blocked。

**根因分析**：
当前 execute pipeline 对模型返回内容只做落盘和 token 记账，没有输出质量门禁；agent registry 虽标注 `can_run_shell: true`，但 LLM 输出的 `<tool_call>` 未被解析/执行/拦截。Coder 阶段也没有检测 “plan-only/placeholder/no source edits” 这类不满足实现门禁的输出。

**修复措施**：
本轮未修复该较大设计问题，仅记录为阻断性缺口。短期应在 `pipeline_runner.py` 写报告前加入内容门禁：检测 `<tool_call>`、`TBD`、`Placeholder`、`No source edits have been performed` 等模式并暂停；长期应实现受控 shell tool 执行或明确禁止 agent 生成工具调用。

**验证结果**：
已通过人工检查 `02_reposcout_report.md`、`06_implementation_report.md`、`lifecycle.yml` 确认问题存在。未进行代码修复。

**后续建议**：
新增 `artifact_contract` 级别的 semantic artifact gate，避免“文件存在但内容不可用”通过生命周期检查。
### [2026-06-03 18:42 CST] - task_0012 - run-pipeline / Coder

**发现者**：外部 IDE AI（执行 task_0012 时触发）

**问题节点/阶段**：`run-pipeline --execute` / `CODER_IMPLEMENTATION` / status reporting

**症状**：
用户要求将 `/Users/saintpeter/Desktop/Coding/AO-SpatialAuthoring-Modular` 的新版本上传到 `http://10.0.1.2:3000/Ao/AO-SpatialAuthoring-Modular`，并要求外部 AI 只做验收。`./agentlab.sh run-pipeline --project CodingWorkspace --task-id task_0012 --execute` 返回 `Final status: completed`、`Pipeline complete: True`、`Artifact pass_rate: 1.0 (14/14)`，但 `06_implementation_report.md` 明确写着 Coder phase not executed、Commands run: None、no upload performed。`./agentlab.sh status` 的 `last_event` 还写着 `Task completed via dry-run pipeline`，与 execute 模式矛盾。

**预期行为**：
如果 Supervisor 判定缺少上传协议/认证/目标 artifact，应生成 `USER_DECISION_REQUIRED.md` 并暂停，不应标记 pipeline completed。若 Coder 被执行并计入真实 token，应产出真实执行证据或明确 blocked/fallback 状态，而不是 plan-only 占位报告。

**调试档内容摘要**：
`lifecycle-status` 显示 all completed，Validation PASS，11/14 completed、3 skipped。`state.yml` 显示 `status: completed`、`last_event: Task completed via dry-run pipeline`。`progress.yml` 显示 Supervisor/Coder/TesterAuditor 均 completed，并记录 Coder provider `qwen-coder`、model `qwen3-coder-next`、total tokens `20746`，但 report_path 为 `runs/task_0012/coder_report.md`，该文件不存在；实际目录中只有 numbered artifact `06_implementation_report.md`。Supervisor report 声称生成了 `USER_DECISION_REQUIRED.md`，但该文件不存在。

**根因分析**：
初步判断为 pipeline 状态推进与 agent 报告内容缺少语义门禁：artifact completeness 只检查文件存在，不检查报告是否为 placeholder/blocker；同时 progress report_path 与实际输出路径不一致。Coder agent 可能把用户的“你只负责验收”错误理解为 Coder 自身也只做验收，导致真实 API 调用产出 plan-only 报告。

**修复措施**：
本次未修改 AgentLab 源码。为避免越过用户要求，未由外部 AI 手动上传或补写正常任务工件。

**验证结果**：
额外运行 `./agentlab.sh run-agent Coder --project CodingWorkspace --task-id task_0012 --execute --overwrite-report`，provider `qwen-coder` 返回 completed，total tokens `20948`，但新 `06_implementation_report.md` 仍写明 `Commands run: None`、`no implementation work performed`。`curl` 验证目标 URL 返回 `200 text/html; charset=utf-8`，只能证明 Gitea 页面可访问，不能证明新版本已上传。目标仓库本地 `git status --short` 无输出。

**后续建议**：
为 `implementation_report.md` / `validation_report.md` 增加 placeholder/blocker 语义检测；当 Supervisor 输出 blockers 或声称 `USER_DECISION_REQUIRED.md` 时，pipeline 必须校验文件存在并暂停。修正 `progress.yml` 的 report_path 映射，避免指向不存在的 `coder_report.md`。建议补充回归测试：execute pipeline 不得在 Coder 报告包含 `Commands run: None` 且任务要求执行上传时标记 completed。

### [2026-06-03 18:57 CST] - task_0012 - AgentLab operational upload repair

**发现者**：外部 IDE AI（执行 task_0012 时触发）

**问题节点/阶段**：Coder execution / TesterAuditor validation / artifact contract / final status

**症状**：
用户要求继续让 AgentLab 自己执行上传，并授权针对该任务修理 AgentLab。原执行链路无法把明确的“本地 Git 仓库上传到 Gitea URL”转换成真实 `git push`，且占位报告可通过 artifact check。

**预期行为**：
对于明确指定本地 Git 仓库和 Gitea HTTP URL 的上传任务，AgentLab Coder 应执行可审计的 git/curl 命令，TesterAuditor 应独立验证 local HEAD、remote HEAD、本地 clean 状态和 HTTP 页面可达性。占位报告不得通过 artifact check。

**调试档内容摘要**：
`06_implementation_report.md` 曾显示 `Commands run: None`。修复后 Coder 报告记录 `git push origin HEAD:main` 成功，远端从 `708adb40632e4e88c2164e8d3e5a6b99b4070423` 更新到 `34ddb38907044c54f98ad8983f880e807de3a881`。`07_validation_report.md` 和 `08_audit_report.md` 均记录 remote HEAD 与 local HEAD 一致，HTTP 返回 200。

**根因分析**：
AgentLab API Coder 原本只生成文本/patch 报告，不具备针对部署任务的安全命令执行入口；artifact contract 只检查文件存在和 TBD，占位报告语义没有被识别；pipeline/status 在终态和 progress report path 上存在不一致。

**修复措施**：
- 新增 `agent_runtime/operational_uploader.py`，第 28-49 行只匹配明确的本地 Git 仓库到 Gitea URL 上传任务；第 52-128 行执行 `git status`、`git push`、远端 HEAD 验证和 HTTP 检查；第 147-185 行提供 TesterAuditor 独立验证。
- 在 `agent_runtime/agent_runner.py` 第 185-189 行接入 operational uploader，命中窄场景时跳过普通 LLM 报告生成。
- 在 `agent_runtime/artifact_contract.py` 第 15-30 行新增执行占位模式，第 140-142 行拒绝 Coder/validation/audit 的 no-command 占位报告。
- 在 `agent_runtime/pipeline_runner.py` 第 200-203 行和第 326-331 行修正 execute/dry-run 终态文案和 terminal state 收口。
- 在 `agent_runtime/llm_provider.py` 第 221-238 行修正 progress report path，从 `coder_report.md` 映射到标准 numbered artifact。
- 在 `agent_runtime/run_task.py` 第 930-932 行让单 agent 执行在路由 agent 全部完成后写入 `completed` 状态。

**验证结果**：
`python3 -B -m py_compile` 覆盖修改过的 runtime 文件并通过。随后执行 `./agentlab.sh run-agent Coder --project CodingWorkspace --task-id task_0012 --execute --overwrite-report`，返回 provider `agentlab-operational-uploader`、model `git-push-v1`、`upload_success: True`。执行 TesterAuditor 写入 `07_validation_report.md` 和 `08_audit_report.md`，均返回 `validation_passed: True`。`./agentlab.sh run-pipeline --project CodingWorkspace --task-id task_0012 --execute` 终态为 completed，artifact pass rate `1.0 (14/14)`。外部验收 `git ls-remote origin refs/heads/main` 返回 `34ddb38907044c54f98ad8983f880e807de3a881`，HTTP URL 返回 `200 text/html; charset=utf-8`。

**后续建议**：
为 `operational_uploader` 增加单元测试和一个 fixture 化的 fake git remote 测试；后续若要支持非 Git/Gitea 上传，应新增显式协议处理器，不要扩大该窄执行器为通用 shell runner。

### [2026-06-04] - task_0002_longterm-knowledgebase-research - Archivist/Coder Memory Persistence

**发现者**：外部 IDE AI（验收 AO-SpatialAuthoring-Modular 知识库任务时触发）

**问题节点/阶段**：`run-pipeline --execute` / Coder + Archivist / durable `agent_docs` update

**症状**：AgentLab full-route execute 返回 completed，14 lifecycle steps completed，但验收发现 `projects/AO-SpatialAuthoring-Modular/agent_docs/` 仍基本为 baseline scanner 输出；原 `06_implementation_report.md` 写着 planning phase/无命令证据，artifact-check 报 implementation report 缺少 command evidence。

**预期行为**：知识库/Archivist 任务完成时，应将验证后的 repo map、interface registry、risk register、development log、build/runtime guide、Xcode research 等持久化到 `agent_docs`，或至少生成可应用的结构化编辑/handoff。

**调试档内容摘要**：`state.yml` 显示 completed；`progress.yml` 显示 Supervisor/RepoScout/Researcher/InterfaceMapper/Coder/TesterAuditor/Verifier/Archivist 均 completed；`artifact-check` 初始 pass_rate 0.95 且 issue 为 `06_implementation_report.md: execution placeholder or no command evidence`。

**根因分析**：当前 pipeline 主要生成 per-task agent 报告；Archivist 的 `can_write_agent_docs` 能力没有对应的落盘执行机制，Coder patch application 也不会自动处理 Archivist/project-memory edits。

**修复措施**：本次未改 AgentLab runtime；采用透明 `external_ide_manual` rescue，仅补写 AO-SpatialAuthoring-Modular 的 AgentLab project memory 和 task implementation report。

**验证结果**：后续通过 artifact-check、关键词检查和文件存在性检查验证。

**后续建议**：为 Archivist 增加专用 memory writer 或结构化 `AGENTLAB_EDIT` 应用路径；artifact-check 应验证声称更新的 durable memory 是否实际变化。
