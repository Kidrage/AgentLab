from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.governance.models import ProviderRoutingRecommendation
from agent_runtime.router_update.models import RouterUpdatePolicy


def load_routing_recommendations(path: Path) -> list[ProviderRoutingRecommendation]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = data.get("recommendations", data if isinstance(data, list) else [])
    recommendations: list[ProviderRoutingRecommendation] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        recommendations.append(
            ProviderRoutingRecommendation(
                provider_id=str(item.get("provider_id") or ""),
                recommendation=str(item.get("recommendation") or "keep"),
                reason=[str(reason) for reason in item.get("reason") or []],
                priority_delta=int(item.get("priority_delta") or 0),
                requires_human_review=item.get("requires_human_review") is True or item.get("apply_automatically") is True,
                apply_automatically=False,
            )
        )
    return recommendations


def load_router_policy(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def load_router_update_policy(path: Path) -> RouterUpdatePolicy:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = data.get("router_update_policy", data) if isinstance(data, dict) else {}
    if not isinstance(raw, dict):
        raw = {}
    return RouterUpdatePolicy(
        enabled=raw.get("enabled", True) is True,
        safety=dict(raw.get("safety") or {}),
        approval=dict(raw.get("approval") or {}),
        recommendations=dict(raw.get("recommendations") or {}),
        artifacts=dict(raw.get("artifacts") or {}),
    )
