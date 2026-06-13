from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_runtime.governance.models import ProviderGovernancePolicy


DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "provider_governance.yml"


DEFAULT_POLICY: dict[str, Any] = {
    "enabled": True,
    "minimum_data": {
        "min_attempts_for_scoring": 2,
        "min_attempts_for_quarantine": 3,
    },
    "thresholds": {
        "healthy_acceptance_rate": 0.75,
        "watchlist_acceptance_rate": 0.50,
        "quarantine_acceptance_rate_below": 0.35,
        "high_retry_rate": 0.60,
        "high_blocked_rate": 0.20,
        "min_average_quality_score": 0.60,
    },
    "cost": {
        "max_estimated_cost_usd_per_task": 0.25,
        "warn_estimated_cost_usd_per_task": 0.08,
        "unknown_cost_requires_manual_approval": True,
        "penalize_unknown_cost": True,
    },
    "routing_feedback": {
        "enabled": True,
        "apply_as_recommendation_only": True,
        "never_modify_router_policy_directly": True,
        "prefer_high_quality_low_cost": True,
        "downgrade_high_retry_providers": True,
        "quarantine_repeated_blocked_providers": True,
    },
    "watchlist": {
        "enabled": True,
        "reasons": [
            "low_acceptance_rate",
            "high_retry_rate",
            "unknown_cost",
            "repeated_needs_revision",
            "blocked_result",
        ],
    },
    "quarantine": {
        "enabled": True,
        "requires_human_review": True,
        "reasons": [
            "repeated_blocked",
            "secret_exposure",
            "external_script_execution",
            "remote_clone",
            "unreviewed_result_attempted_acceptance",
        ],
    },
    "artifacts": {
        "write_provider_performance_profiles": True,
        "write_provider_governance_report": True,
        "write_cost_governance_report": True,
        "write_routing_recommendations": True,
    },
}


def load_provider_governance_policy(path: Path | None = None) -> ProviderGovernancePolicy:
    policy_path = path or DEFAULT_POLICY_PATH
    data: dict[str, Any] = {}
    if policy_path.exists():
        loaded = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            data = loaded.get("provider_governance", loaded)
    merged = _deep_merge(DEFAULT_POLICY, data if isinstance(data, dict) else {})
    return ProviderGovernancePolicy(
        enabled=merged.get("enabled", True) is True,
        minimum_data=dict(merged.get("minimum_data") or {}),
        thresholds=dict(merged.get("thresholds") or {}),
        cost=dict(merged.get("cost") or {}),
        routing_feedback=dict(merged.get("routing_feedback") or {}),
        watchlist=dict(merged.get("watchlist") or {}),
        quarantine=dict(merged.get("quarantine") or {}),
        artifacts=dict(merged.get("artifacts") or {}),
    )


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in base.items():
        if isinstance(value, dict):
            result[key] = _deep_merge(value, {})
        elif isinstance(value, list):
            result[key] = list(value)
        else:
            result[key] = value
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
