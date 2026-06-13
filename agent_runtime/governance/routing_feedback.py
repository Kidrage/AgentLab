from __future__ import annotations

from pathlib import Path

from agent_runtime.executors.policy import load_executor_router_policy
from agent_runtime.governance.models import GovernanceDecision, ProviderRoutingRecommendation


def generate_routing_recommendations(
    decisions: list[GovernanceDecision],
    router_policy_path: Path,
    output_dir: Path | None = None,
) -> tuple[list[ProviderRoutingRecommendation], list[str]]:
    policy = load_executor_router_policy(router_policy_path)
    known = {str(item.get("provider_id")) for item in policy.providers}
    warnings: list[str] = []
    recommendations: list[ProviderRoutingRecommendation] = []
    for decision in decisions:
        if decision.provider_id not in known:
            warnings.append(f"provider not found in router policy: {decision.provider_id}")
        recommendations.append(_recommendation_for_decision(decision))
    return recommendations, warnings


def _recommendation_for_decision(decision: GovernanceDecision) -> ProviderRoutingRecommendation:
    if decision.status == "HEALTHY":
        return ProviderRoutingRecommendation(decision.provider_id, "keep", decision.reasons or ["provider healthy"], 0, False, False)
    if decision.status == "INSUFFICIENT_DATA":
        return ProviderRoutingRecommendation(decision.provider_id, "insufficient_data", decision.reasons, 0, False, False)
    if decision.status == "MANUAL_APPROVAL_REQUIRED":
        return ProviderRoutingRecommendation(decision.provider_id, "require_manual_approval", decision.reasons, 0, True, False)
    if decision.status == "WATCHLIST":
        return ProviderRoutingRecommendation(decision.provider_id, "watchlist", decision.reasons, -1, True, False)
    if decision.status == "DOWNGRADED":
        return ProviderRoutingRecommendation(decision.provider_id, "downgrade", decision.reasons, -2, True, False)
    if decision.status == "QUARANTINE_RECOMMENDED":
        return ProviderRoutingRecommendation(decision.provider_id, "quarantine", decision.reasons, -99, True, False)
    return ProviderRoutingRecommendation(decision.provider_id, "keep", decision.reasons, 0, False, False)
