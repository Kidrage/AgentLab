from typing import Dict, Any
from agent_runtime.costs.attribution import attribute_spend
from agent_runtime.costs.spend_ledger import SpendLedger

def generate_efficiency_review(ledger: SpendLedger, estimates: Dict[str, float]) -> str:
    """
    Compare estimated vs actual costs and generate efficiency report.
    """
    attr = attribute_spend(ledger)

    lines = [
        f"# Efficiency Review for {ledger.project}",
        "",
        "## Overview",
        f"Total Actual Spend: ${attr['total_usd']:.2f}",
        ""
    ]

    lines.append("## Estimated vs Actual")
    for task_id, actual in attr["by_task"].items():
        est = estimates.get(task_id, 0.0)
        diff = actual - est
        lines.append(f"- **Task {task_id}**: Est ${est:.2f} | Act ${actual:.2f} | Diff ${diff:.2f}")

    lines.append("")
    lines.append("## Unknown-cost Events")
    unknown = attr["by_source"].get("external_unknown", 0.0)
    lines.append(f"- Total unknown external cost: ${unknown:.2f}")

    return "\n".join(lines)
