from typing import Dict, Any

def render_cost_estimate(estimate: Dict[str, Any], format_type: str = "text") -> str:
    if format_type == "json":
        import json
        return json.dumps(estimate, indent=2)
    elif format_type == "yaml":
        import yaml
        return yaml.safe_dump(estimate, sort_keys=False)

    lines = [
        f"Cost Estimate: ${estimate['estimated_cost_usd']:.2f} {estimate['currency']}",
        f"Visibility: {estimate['cost_visibility']}",
        f"Requires Approval: {estimate['approval_required']}",
        "Breakdown:"
    ]
    for k, v in estimate["breakdown"].items():
        lines.append(f"  - {k}: {v}")
    if estimate["warnings"]:
        lines.append("Warnings:")
        for w in estimate["warnings"]:
            lines.append(f"  - {w}")
    return "\n".join(lines)
