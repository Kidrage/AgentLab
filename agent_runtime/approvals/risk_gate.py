from typing import Dict, Any, List
from agent_runtime.approvals.approval_policy import ApprovalPolicy
from agent_runtime.approvals.decision_card import DecisionCard

def evaluate_risk(task_packet: Dict[str, Any], policy: ApprovalPolicy) -> List[DecisionCard]:
    cards = []

    # 1. Cost risk
    if task_packet.get("cost_visibility") == "unknown_external_cli_cost" and policy.require_approval_for_unknown_cli_cost:
        cards.append(DecisionCard.create(
            decision_type="cost",
            risk_level="high",
            reason="Unknown external CLI cost",
            task_id=task_packet.get("task_id", ""),
            project=task_packet.get("project", "")
        ))

    est_cost = task_packet.get("estimated_cost_usd", 0.0)
    if est_cost > policy.require_approval_above_usd:
        cards.append(DecisionCard.create(
            decision_type="budget",
            risk_level="medium",
            reason=f"Estimated cost {est_cost} exceeds approval threshold {policy.require_approval_above_usd}",
            task_id=task_packet.get("task_id", ""),
            project=task_packet.get("project", ""),
            estimated_cost_usd=est_cost
        ))

    # 2. Capability risk
    caps = task_packet.get("required_capabilities", [])
    if policy.require_approval_for_risky_capabilities:
        critical_found = [c for c in caps if c in policy.critical_capabilities]
        risky_found = [c for c in caps if c in policy.risky_capabilities]

        if critical_found:
            cards.append(DecisionCard.create(
                decision_type="capability",
                risk_level="critical",
                reason=f"Critical capabilities requested: {critical_found}",
                task_id=task_packet.get("task_id", ""),
                project=task_packet.get("project", ""),
                capabilities=critical_found
            ))
        elif risky_found:
            cards.append(DecisionCard.create(
                decision_type="capability",
                risk_level="high",
                reason=f"Risky capabilities requested: {risky_found}",
                task_id=task_packet.get("task_id", ""),
                project=task_packet.get("project", ""),
                capabilities=risky_found
            ))

    return cards
