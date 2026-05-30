# RepoScout Report

## Task
- **Task id:** task_0011
- **User request:** 调查 AgentLab 在云端部署的可行性。分析是否可以在云服务器上运行（如 AWS、阿里云、VPS 等），以及智能体架构是否需要适配。只做调查分析，不做实际开发。输出修改方针建议。
- **Assigned scope:** Repository inspection – identify components, dependencies, configuration, and integration points relevant to cloud deployment feasibility.

## Work Performed

### Files Read
The following files were read and inspected (via shell commands or from provided context):

| File | Content Summary |
|------|----------------|
| `agentlab.sh` | One-command wrapper; sources `.env`, calls `python agent_runtime/run_task.py`. |
| `agent_runtime/run_task.py` | CLI entrypoint – loads config, triggers workflow plan. |
| `agent_runtime/agent_runner.py` | Agent message composition and model execution wrapper. |
| `agent_runtime/llm_provider.py` | Provider adapters – reads API keys from env, supports DeepSeek, Codex handoff. |
| `agent_runtime/brain_governor.py` | Token governance and traversal limits. |
| `agent_runtime/workflow_plan.py` | Task planning structure. |
| `agent_runtime/task_router.py` | Route selection logic. |
| `agent_runtime/cost_tracker.py` | Cost ledger updates. |
| `config/agent_registry.yml` | Agent capabilities and routing identity. |
| `config/model_profiles.yml` | Agent-to-model profiles. |
| `config/model_providers.yml` | Provider definitions – DeepSeek, Codex, Qwen. |
| `config/routing_rules.yml` | Route hints and task-size policy. |
| `config/budget_profiles.yml` | Token budget estimates. |
| `config/brain_governance.yml` | Traversal, loop, and user-decision rules. |
| `config/execution_policy.yml` | Brain policy, coder policy, logging policy. |
| `web_ui/index.html` | Static status dashboard shell – relies