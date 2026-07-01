from typing import Dict, Any, List
from agent_runtime.costs.budget_policy import BudgetPolicy
from agent_runtime.costs.spend_ledger import SpendLedger

def check_alerts(policy: BudgetPolicy, ledger: SpendLedger) -> List[Dict[str, Any]]:
    alerts = []

    total = ledger.get_total()
    if total > policy.project_hard_limit_usd:
        alerts.append({"type": "project_hard_limit_exceeded", "level": "blocking", "message": f"Project hard limit exceeded: {total} > {policy.project_hard_limit_usd}"})
    elif total > policy.project_soft_limit_usd:
        alerts.append({"type": "project_soft_limit_exceeded", "level": "warning", "message": f"Project soft limit exceeded: {total} > {policy.project_soft_limit_usd}"})

    by_phase = {}
    by_task = {}
    for e in ledger.entries:
        p = e.get("phase_id", "unknown")
        t = e.get("task_id", "unknown")
        cost = e.get("cost_usd", 0.0)
        by_phase[p] = by_phase.get(p, 0.0) + cost
        by_task[t] = by_task.get(t, 0.0) + cost

        if e.get("cost_source") == "external_unknown":
            alerts.append({"type": "unknown_external_cli_cost", "level": "blocking", "message": "Unknown external CLI cost requires approval."})

    for p, cost in by_phase.items():
        if cost > policy.phase_hard_limit_usd:
            alerts.append({"type": "phase_hard_limit_exceeded", "level": "blocking", "message": f"Phase {p} hard limit exceeded: {cost} > {policy.phase_hard_limit_usd}"})
        elif cost > policy.phase_soft_limit_usd:
            alerts.append({"type": "phase_soft_limit_exceeded", "level": "warning", "message": f"Phase {p} soft limit exceeded: {cost} > {policy.phase_soft_limit_usd}"})

    for t, cost in by_task.items():
        if cost > policy.task_hard_limit_usd:
            alerts.append({"type": "task_hard_limit_exceeded", "level": "blocking", "message": f"Task {t} hard limit exceeded: {cost} > {policy.task_hard_limit_usd}"})
        elif cost > policy.task_soft_limit_usd:
            alerts.append({"type": "task_soft_limit_exceeded", "level": "warning", "message": f"Task {t} soft limit exceeded: {cost} > {policy.task_soft_limit_usd}"})

    return alerts
