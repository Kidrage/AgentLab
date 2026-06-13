from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_runtime.executors.policy import load_executor_router_policy
from agent_runtime.governance.models import (
    GovernanceInputBundle,
    ProviderCostProfile,
    ProviderGovernancePolicy,
    ProviderPerformanceProfile,
)


FREE_COST_MODES = {"none", "free"}
UNKNOWN_COST_MODES = {"unknown", "subscription_or_credit_external", "user_controlled_external"}
METERED_COST_MODES = {"api_model", "external_harness"}


def build_provider_cost_profiles(
    input_bundle: GovernanceInputBundle,
    provider_profiles: list[ProviderPerformanceProfile],
    policy: ProviderGovernancePolicy,
    router_policy_path: Path | None = None,
) -> list[ProviderCostProfile]:
    cost_modes = _provider_cost_modes(router_policy_path)
    estimated_costs = _estimated_costs(input_bundle)
    profiles: list[ProviderCostProfile] = []
    for profile in provider_profiles:
        cost_mode = cost_modes.get(profile.provider_id, "unknown")
        costs = estimated_costs.get(profile.provider_id, [])
        total = round(sum(costs), 6) if costs else None
        average = round(sum(costs) / len(costs), 6) if costs else None
        unknown_events = max(profile.attempts - len(costs), 0) if cost_mode in UNKNOWN_COST_MODES else 0
        risk = _cost_risk(cost_mode, average, policy)
        requires_manual = cost_mode in UNKNOWN_COST_MODES and policy.cost.get("unknown_cost_requires_manual_approval", True) is True
        notes: list[str] = []
        if unknown_events:
            notes.append("one or more attempts had unknown estimated cost")
        profiles.append(
            ProviderCostProfile(
                provider_id=profile.provider_id,
                cost_mode=cost_mode,
                estimated_total_cost_usd=total,
                estimated_average_cost_usd=average,
                unknown_cost_events=unknown_events,
                cost_risk_level=risk,
                requires_manual_approval=requires_manual,
                notes=notes,
            )
        )
    return profiles


def _provider_cost_modes(router_policy_path: Path | None) -> dict[str, str]:
    if not router_policy_path:
        return {}
    policy = load_executor_router_policy(router_policy_path)
    return {str(item.get("provider_id")): str(item.get("cost_mode") or "unknown") for item in policy.providers}


def _estimated_costs(input_bundle: GovernanceInputBundle) -> dict[str, list[float]]:
    costs: dict[str, list[float]] = {}
    for ledger in input_bundle.retry_attempt_ledgers:
        for attempt in ledger.get("attempts") or []:
            _append_cost(costs, attempt)
    for ledger in input_bundle.execution_ledgers:
        for entry in ledger.get("entries") or []:
            _append_cost(costs, entry)
    return costs


def _append_cost(costs: dict[str, list[float]], item: Any) -> None:
    if not isinstance(item, dict):
        return
    provider_id = str(item.get("provider_id") or "")
    if not provider_id:
        return
    value = item.get("estimated_cost_usd")
    if value is None:
        return
    costs.setdefault(provider_id, []).append(float(value))


def _cost_risk(cost_mode: str, average: float | None, policy: ProviderGovernancePolicy) -> str:
    if cost_mode in FREE_COST_MODES:
        return "low"
    if cost_mode in UNKNOWN_COST_MODES:
        return "unknown"
    if cost_mode in METERED_COST_MODES:
        if average is None:
            return "medium"
        if average > float(policy.cost.get("max_estimated_cost_usd_per_task", 0.25)):
            return "high"
        return "medium" if average > float(policy.cost.get("warn_estimated_cost_usd_per_task", 0.08)) else "low"
    return "unknown"
