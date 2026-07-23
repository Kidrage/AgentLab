"""Decision card builder — creates human decision point cards for mission contracts."""

from __future__ import annotations

from typing import Any

from agent_runtime.approvals.approval_policy import ApprovalPolicy
from agent_runtime.approvals.policy_engine import decide_approval


def build_decision_cards(
    project_type: str,
    risk_flags: list[str],
    non_goal_hits: list[str],
    capability_gaps: list[str],
    project_types: dict[str, Any] | None = None,
    approval_policy: ApprovalPolicy | None = None,
) -> list[dict[str, Any]]:
    """Build auditable human and policy-auto decisions for a mission contract.

    One card per decision point. Cards are deterministic — no LLM needed.
    """
    if project_types is None:
        from agent_runtime.brain.project_type_classifier import load_project_types
        project_types = load_project_types()
    typedef = project_types.get(project_type, project_types.get("unknown_project", {}))
    policy = approval_policy or ApprovalPolicy()
    cards: list[dict[str, Any]] = []

    # Card 1: Project type confirmation (always present for unknown)
    if project_type == "unknown_project":
        cards.append({
            "decision_id": "dc_project_type_unknown",
            "title": "Project type could not be determined",
            "reason": "No keyword match found for project type classification.",
            "available_options": ["provide_more_detail", "select_manually", "proceed_as_unknown"],
            "recommended_action": "provide_more_detail",
            "status": "human_required",
            "decision_mode": "human_required",
            "risk_notes": ["Cannot infer phases, capabilities, or artifacts without project type."],
        })

    # Card 2: Safety flag if non-goal patterns detected
    if non_goal_hits:
        cards.append({
            "decision_id": "dc_safety_concern",
            "title": "Safety concern detected in prompt",
            "reason": f"Prompt matched non-goal patterns: {', '.join(non_goal_hits)}",
            "available_options": ["clarify_with_user", "reject", "proceed_with_warnings"],
            "recommended_action": "clarify_with_user",
            "status": "human_required",
            "decision_mode": "human_required",
            "risk_notes": [
                "M-series safety policy may block or gate this project.",
                "These patterns are associated with prohibited activities.",
            ],
        })

    # Card 3: Capability gaps
    if capability_gaps:
        cards.append({
            "decision_id": "dc_capability_gaps",
            "title": "Required capabilities not available",
            "reason": f"Missing capabilities: {', '.join(capability_gaps)}",
            "available_options": ["install_capability", "use_alternative", "proceed_without", "block"],
            "recommended_action": "block",
            "status": "human_required",
            "decision_mode": "human_required",
            "risk_notes": [
                "Required capabilities must have active backends before execution.",
                "Run `./agentlab.sh capability-list` to inspect available backends.",
            ],
        })

    # Card 4: Approval points from project type definition
    approval_points = typedef.get("human_approval_points", [])
    for i, point in enumerate(approval_points):
        decision = decide_approval(
            {
                "action": "plan_approval_point",
                "project_type": project_type,
                "approval_point": point,
                "bounded_scope": True,
                "reversible": True,
                "estimated_cost_usd": 0.0,
            },
            policy,
            now="1970-01-01T00:00:00Z",
        )
        cards.append({
            "decision_id": f"dc_approval_{i + 1}",
            "title": f"Approval gate: {point}",
            "reason": f"Project type '{project_type}' declares an approval point at: {point}",
            "available_options": ["approve", "reject", "request_changes"],
            "recommended_action": "approve",
            "status": decision.mode,
            "decision_mode": decision.mode,
            "policy_id": policy.policy_id,
            "runtime_recheck_required": True,
            "risk_notes": [],
        })

    # Card 5: External executor recommended
    if typedef.get("external_executor_recommended", False):
        decision = decide_approval(
            {
                "action": "plan_external_executor",
                "project_type": project_type,
                "bounded_scope": True,
                "reversible": True,
                "estimated_cost_usd": 0.0,
            },
            policy,
            now="1970-01-01T00:00:00Z",
        )
        cards.append({
            "decision_id": "dc_external_executor",
            "title": "External executor recommended",
            "reason": f"Project type '{project_type}' may benefit from an external executor.",
            "available_options": ["enable_executor", "use_local_only", "defer_decision"],
            "recommended_action": "defer_decision",
            "status": decision.mode,
            "decision_mode": decision.mode,
            "policy_id": policy.policy_id,
            "runtime_recheck_required": True,
            "risk_notes": [
                "The concrete executor, cost, data egress, and scope are rechecked at runtime.",
                "All external executor results must pass evidence and review gates.",
            ],
        })

    return cards
