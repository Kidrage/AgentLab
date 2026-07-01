from typing import Dict, Any, List
from agent_runtime.approvals.decision_card import DecisionCard

def render_pending_approvals(cards: List[DecisionCard], format_type: str = "text") -> str:
    if format_type == "json":
        import json
        return json.dumps([c.to_dict() for c in cards], indent=2)
    elif format_type == "yaml":
        import yaml
        return yaml.safe_dump([c.to_dict() for c in cards], sort_keys=False)

    if not cards:
        return "No pending approvals."

    lines = []
    for c in cards:
        lines.append(f"Decision ID: {c.decision_id}")
        lines.append(f"  Type: {c.decision_type}")
        lines.append(f"  Risk: {c.risk_level}")
        lines.append(f"  Reason: {c.reason}")
        lines.append(f"  Cost: ${c.estimated_cost_usd:.2f}")
        lines.append("")
    return "\n".join(lines)
