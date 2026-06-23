"""Human-readable route-decision rendering."""

from __future__ import annotations

from agent_runtime.routing.route_decision import RouteDecision


def render_route_explanation(decision: RouteDecision) -> str:
    selected = decision.selected_worker or "none"
    lines = [
        f"Role: {decision.role}",
        f"Selected worker: {selected}",
        f"Activation: {decision.activation_decision}",
        f"Mode / tier: {decision.mode} / {decision.tier}",
        f"Approval required: {str(decision.approval_required).lower()}",
        "Selection reasons:",
    ]
    lines.extend(f"  - {reason}" for reason in decision.selection_reason)
    lines.append("Rejected workers:")
    lines.extend(f"  - {item.worker}: {item.reason}" for item in decision.rejected_workers)
    lines.append("Fallback workers: " + (", ".join(decision.fallback_workers) or "none"))
    return "\n".join(lines)
