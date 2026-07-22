from typing import Dict, Any, List
from agent_runtime.approvals.approval_policy import ApprovalPolicy
from agent_runtime.approvals.decision_card import DecisionCard
from agent_runtime.approvals.policy_engine import decide_approval

def evaluate_risk(task_packet: Dict[str, Any], policy: ApprovalPolicy) -> List[DecisionCard]:
    """Evaluate a runtime packet and return its auditable policy decision card."""
    capabilities = task_packet.get("required_capabilities")
    decision = decide_approval(
        {
            "action": task_packet.get("action", ""),
            "task_id": task_packet.get("task_id", ""),
            "project": task_packet.get("project", ""),
            "capabilities": capabilities,
            "bounded_scope": task_packet.get("bounded_scope"),
            "reversible": task_packet.get("reversible"),
            "cost_visibility": task_packet.get("cost_visibility", "unknown"),
            "estimated_cost_usd": task_packet.get("estimated_cost_usd", 0.0),
        },
        policy,
    )
    reasons = ";".join(decision.reasons)
    if "cost" in reasons:
        decision_type = "cost"
    elif capabilities:
        decision_type = "capability"
    else:
        decision_type = "policy"
    grant = decision.grant or {}
    return [DecisionCard.create(
        decision_id=grant.get("grant_id"),
        decision_type=decision_type,
        status={
            "auto_approved": "approved",
            "human_required": "pending",
            "forbidden": "rejected",
        }[decision.mode],
        risk_level="critical" if decision.mode == "forbidden" else "high" if decision.requires_human else "low",
        reason=reasons,
        requested_by=grant.get("actor", "system"),
        task_id=task_packet.get("task_id", ""),
        project=task_packet.get("project", ""),
        capabilities=list(capabilities or []),
        estimated_cost_usd=task_packet.get("estimated_cost_usd", 0.0),
        expires_at=grant.get("expires_at", ""),
        authorization={"decision_mode": decision.mode, **grant},
    )]
