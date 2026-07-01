from typing import Dict, Any, List
from agent_runtime.costs.spend_ledger import SpendLedger

def attribute_spend(ledger: SpendLedger) -> Dict[str, Any]:
    """
    Aggregate ledger entries by multiple dimensions.
    """
    by_task: Dict[str, float] = {}
    by_phase: Dict[str, float] = {}
    by_role: Dict[str, float] = {}
    by_worker: Dict[str, float] = {}
    by_model: Dict[str, float] = {}
    by_executor: Dict[str, float] = {}
    by_source: Dict[str, float] = {}

    for e in ledger.entries:
        cost = e.get("cost_usd", 0.0)

        task_id = e.get("task_id", "unknown")
        by_task[task_id] = by_task.get(task_id, 0.0) + cost

        phase_id = e.get("phase_id", "unknown")
        by_phase[phase_id] = by_phase.get(phase_id, 0.0) + cost

        role = e.get("role", "unknown")
        by_role[role] = by_role.get(role, 0.0) + cost

        worker = e.get("worker", "unknown")
        by_worker[worker] = by_worker.get(worker, 0.0) + cost

        model = e.get("model", "unknown")
        by_model[model] = by_model.get(model, 0.0) + cost

        executor = e.get("executor", "unknown")
        by_executor[executor] = by_executor.get(executor, 0.0) + cost

        source = e.get("cost_source", "unknown")
        by_source[source] = by_source.get(source, 0.0) + cost

    return {
        "project": ledger.project,
        "total_usd": ledger.get_total(),
        "by_task": by_task,
        "by_phase": by_phase,
        "by_role": by_role,
        "by_worker": by_worker,
        "by_model": by_model,
        "by_executor": by_executor,
        "by_source": by_source,
    }

def generate_attribution_report(attribution: Dict[str, Any]) -> str:
    lines = [
        f"# Cost Attribution Report for Project: {attribution['project']}",
        f"**Total Spend:** ${attribution['total_usd']:.2f}",
        ""
    ]
    for key in ["by_task", "by_phase", "by_role", "by_worker", "by_model", "by_executor", "by_source"]:
        lines.append(f"## {key.replace('_', ' ').title()}")
        for k, v in attribution[key].items():
            lines.append(f"- **{k}**: ${v:.2f}")
        lines.append("")
    return "\n".join(lines)
