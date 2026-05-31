# User Request

## Original Request
由 agentlab 来完成 Capability & Budget-Saving Evaluation 并出结果文档。

## Attached Specification
`AGENTLAB_CAPABILITY_BUDGET_EVALUATION_SPEC.md` — 评估套件规范

## Required Deliverables
1. `config/evaluation_policy.yml`
2. `agent_runtime/evaluation/system_audit.py` + 6 个评估模块
3. CLI 命令: system-audit, eval-lifecycle, eval-task-discovery, eval-provider-failover, eval-sync-safety, budget-eval, capability-eval, eval-report
4. 运行所有评估命令
5. 结果文档: `evaluation_runs/reports/final_evaluation_summary.md`

## Explicit Constraints
- 本地优先，离线测试不调用 LLM API
- 所有报告保存到 projects/AgentLab/evaluation_runs/
- 不往 GitHub 推送（除非显式 --confirm-push）

## Requested Execution Mode
Codex Full-Driver Mode