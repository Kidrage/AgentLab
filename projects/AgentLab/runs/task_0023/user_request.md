# User Request

## Original Request
由 AgentLab 来添加 Task Discovery & Resume Index 功能。

## Attached Specification
用户提供了 `AGENTLAB_TASK_DISCOVERY_RESUME_INDEX_SPEC.md` 完整规范文档。

## Required Deliverables
1. `config/task_index_policy.yml` — 策略配置文件
2. `agent_runtime/task_index.py` — 任务索引构建
3. `agent_runtime/task_search.py` — 本地搜索（支持中英文）
4. `agent_runtime/task_card.py` — 任务卡片渲染
5. CLI 命令: task-index, task-find, task-open, task-resume-candidates, task-map, task-artifacts
6. Terminal Chat 命令: /find, /resume-list, /attach, /open-task, /task-map, /artifacts, /summarize-task
7. Web UI API 端点 (如可行)
8. 生成所有任务的 artifact_manifest.yml 和 task_card.yml

## Explicit Constraints
- 搜索必须完全本地化，不使用任何 LLM/API 调用
- 支持中英文查询（CJK n-gram + 英文 tokenization）
- 对缺失文件和损坏 YAML 必须健壮
- 不扫描 secrets、.env、.venv、node_modules、.git
- 不破坏现有 CLI 命令

## Forbidden Assumptions
- 不依赖外部搜索引擎或向量数据库
- 不调用 DeepSeek/Qwen/OpenAI/OpenRouter/Codex API 进行搜索

## Requested Execution Mode
Codex Full-Driver Mode

## Continuation Requirement
所有工件保存到本地，可通过 AgentLab API agents 恢复执行。