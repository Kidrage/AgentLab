"""Quality-floor-first runtime route selection."""

from __future__ import annotations

from dataclasses import asdict
from math import exp, log
from typing import Any, Mapping

from agent_runtime.costing.catalog import PricingCatalog
from agent_runtime.runtime_registry import QuotaSnapshot, RuntimeRegistry, TaskDemand


def _capabilities(value: Mapping[str, Any] | None) -> dict[str, float]:
    return {
        str(name): max(0.0, min(1.0, float(score)))
        for name, score in ((value or {}).get("capabilities") or {}).items()
    }


def _weighted_geometric_mean(values: Mapping[str, float], weights: Mapping[str, float]) -> float:
    total_weight = sum(max(0.0, float(weight)) for weight in weights.values())
    if total_weight <= 0:
        return 0.0
    weighted_log = 0.0
    for name, weight in weights.items():
        normalized_weight = max(0.0, float(weight)) / total_weight
        weighted_log += normalized_weight * log(max(1e-9, float(values.get(name, 0.0))))
    return exp(weighted_log)


class DynamicRouteSelector:
    """Apply hard constraints, then quality floor, then effective task cost."""

    def __init__(
        self,
        registry: RuntimeRegistry,
        *,
        pricing: PricingCatalog | None = None,
        quota_snapshots: Mapping[str, QuotaSnapshot | Mapping[str, Any]] | None = None,
        route_states: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self.registry = registry
        self.pricing = pricing or PricingCatalog.load(registry.root)
        self.quota_snapshots = dict(quota_snapshots or {})
        self.route_states = dict(route_states or {})

    def select(
        self,
        demand: TaskDemand,
        *,
        candidate_route_ids: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        candidates = (
            [str(item) for item in candidate_route_ids]
            if candidate_route_ids is not None
            else self.registry.candidates_for(demand.role)
        )
        rejected: list[dict[str, Any]] = []
        eligible: list[dict[str, Any]] = []
        runtime_policy = self.registry.routing_policy.get("runtime_routing") or {}
        cost_weights = runtime_policy.get("effective_cost_weights") or {}

        for ordinal, route_id in enumerate(candidates):
            route = self.registry.routes.get(route_id) or {}
            identity = self.registry.route_identity(route_id)
            model = self.registry.models.get(identity.model_id) or {}
            shell = self.registry.shells.get(identity.shell_id) or {}
            adapter = self.registry.adapters.get(identity.adapter_id) or {}
            provider = self.registry.providers.get(identity.provider_id) or {}

            reason = self._hard_rejection(
                demand,
                route=route,
                model=model,
                shell=shell,
                adapter=adapter,
                provider=provider,
                identity=identity,
                ordinal=ordinal,
                route_state=self.route_states.get(route_id) or {},
            )
            if reason:
                rejected.append({"route_id": route_id, "stage": "hard_filter", "reason": reason})
                continue

            effective_dimensions: dict[str, float] = {}
            shell_caps = _capabilities(shell)
            adapter_caps = _capabilities(adapter)
            model_caps = _capabilities(model)
            canary_caps = _capabilities(route.get("capability_evidence") or {"capabilities": {}})
            for dimension in demand.capability_weights:
                effective_dimensions[dimension] = min(
                    shell_caps.get(dimension, 0.0),
                    adapter_caps.get(dimension, 0.0),
                    model_caps.get(dimension, 0.0),
                    canary_caps.get(dimension, 1.0),
                )
            confidence = float(route.get("evidence_confidence", 0.0))
            reliability = float(route.get("reliability", 0.0))
            quality = confidence * reliability * _weighted_geometric_mean(
                effective_dimensions, demand.capability_weights
            )
            if quality < demand.quality_floor:
                rejected.append({
                    "route_id": route_id,
                    "stage": "quality_floor",
                    "reason": "quality_below_floor",
                    "quality": round(quality, 6),
                    "quality_floor": demand.quality_floor,
                    "effective_capabilities": effective_dimensions,
                })
                continue

            quote = self.pricing.quote(
                identity.model_id,
                input_tokens=demand.predicted_input_tokens,
                output_tokens=demand.predicted_output_tokens,
            )
            cash_cny = quote.cny_amount
            if cash_cny is None:
                rejected.append({"route_id": route_id, "stage": "cost", "reason": "unknown_cash_cost"})
                continue
            quota_penalty = self._quota_scarcity_penalty(identity.credential_pool_id, demand)
            retry_penalty = float(route.get("retry_expectation", 0.0)) * float(cost_weights.get("retry", 1.0))
            latency_penalty = float(route.get("latency_penalty", 0.0)) * float(cost_weights.get("latency", 1.0))
            switch_penalty = (float(cost_weights.get("switch", 0.0)) if ordinal else 0.0)
            effective_cost = cash_cny + quota_penalty + retry_penalty + latency_penalty + switch_penalty
            eligible.append({
                "route_id": route_id,
                "ordinal": ordinal,
                "identity": asdict(identity),
                "quality": round(quality, 6),
                "quality_floor": demand.quality_floor,
                "effective_capabilities": effective_dimensions,
                "cost": {
                    **quote.to_dict(),
                    "quota_scarcity_penalty_cny": round(quota_penalty, 8),
                    "retry_penalty_cny": round(retry_penalty, 8),
                    "latency_penalty_cny": round(latency_penalty, 8),
                    "switch_penalty_cny": round(switch_penalty, 8),
                    "effective_cost_cny": round(effective_cost, 8),
                },
                "reliability": reliability,
                "independence": float(route.get("independence", 0.0)),
                "latency": float(route.get("latency_penalty", 0.0)),
            })

        if not eligible:
            return {
                "status": "blocked",
                "route_id": None,
                "role": demand.role,
                "quality_floor": demand.quality_floor,
                "rejected_routes": rejected,
                "reason": "no_route_satisfies_hard_constraints_and_quality_floor",
            }
        eligible.sort(
            key=lambda item: (
                item["cost"]["effective_cost_cny"],
                -item["quality"],
                -item["reliability"],
                -item["independence"],
                item["latency"],
            )
        )
        selected = eligible[0]
        return {
            "status": "selected",
            "route_id": selected["route_id"],
            "role": demand.role,
            "identity": selected["identity"],
            "quality": selected["quality"],
            "quality_floor": selected["quality_floor"],
            "effective_capabilities": selected["effective_capabilities"],
            "cost": selected["cost"],
            "selection_policy": "hard_filters_then_quality_floor_then_min_effective_cost",
            "fallback_at_checkpoint_only": True,
            "rejected_routes": rejected,
            "eligible_routes": [item["route_id"] for item in eligible],
        }

    def _hard_rejection(
        self,
        demand: TaskDemand,
        *,
        route: Mapping[str, Any],
        model: Mapping[str, Any],
        shell: Mapping[str, Any],
        adapter: Mapping[str, Any],
        provider: Mapping[str, Any],
        identity: Any,
        ordinal: int,
        route_state: Mapping[str, Any],
    ) -> str | None:
        route_status = str(route_state.get("status") or "")
        if route_status in {"blocked", "unknown"}:
            return str(
                route_state.get("failure_class")
                or (
                    "runtime_route_blocked"
                    if route_status == "blocked"
                    else "unclassified_runtime_failure"
                )
            )
        if str(route.get("status") or "active") != "active":
            return f"route_{route.get('status') or 'inactive'}"
        if str(shell.get("status") or "active") != "active":
            return f"shell_{shell.get('status') or 'inactive'}"
        if shell.get("automatic_use") is False:
            return "shell_automatic_use_disabled"
        if str(model.get("status") or "active") != "active":
            return f"model_{model.get('status') or 'inactive'}"
        if model.get("automatic_use") is False:
            return "model_automatic_use_disabled"
        if str(adapter.get("status") or "active") != "active":
            return "adapter_inactive"
        if str(provider.get("status") or "active") != "active":
            return f"provider_{provider.get('status') or 'inactive'}"
        if provider.get("automatic_use") is False:
            return "provider_automatic_use_disabled"
        if demand.required_modalities:
            supported = {str(item).lower() for item in model.get("input_modalities") or []}
            missing = set(demand.required_modalities) - supported
            if missing:
                return "unsupported_modalities:" + ",".join(sorted(missing))
        allowed_classes = {str(item) for item in provider.get("allowed_data_classes") or []}
        if demand.data_class not in allowed_classes:
            return "privacy_data_class_not_allowed"
        if demand.allowed_provider_ids and identity.provider_id not in demand.allowed_provider_ids:
            return "provider_not_in_project_allowlist"
        if ordinal and not demand.checkpoint_complete:
            return "provider_switch_requires_checkpoint_boundary"
        snapshot = self.quota_snapshots.get(identity.credential_pool_id)
        pool = self.registry.credential_pools.get(identity.credential_pool_id) or {}
        quota_policy = (
            self.registry.routing_policy.get("runtime_routing") or {}
        ).get("quota") or {}
        if (
            not snapshot
            and demand.long_batch
            and bool(quota_policy.get("long_batch_requires_fresh_telemetry", True))
            and str(pool.get("billing_mode") or "") == "oauth_subscription"
        ):
            return "quota_telemetry_missing_for_long_batch"
        if snapshot:
            raw = snapshot.to_dict() if isinstance(snapshot, QuotaSnapshot) else dict(snapshot)
            status = str(raw.get("status") or "unknown")
            if status in {"blocked", "waiting_for_quota", "auth_missing", "quota_reserve"}:
                return status
            if status in {"unknown", "stale", "telemetry_degraded"} and demand.long_batch:
                return "quota_telemetry_degraded_for_long_batch"
            remaining = raw.get("remaining_percent")
            if (
                demand.long_batch
                and str(pool.get("billing_mode") or "") == "oauth_subscription"
                and remaining is None
            ):
                return "quota_telemetry_degraded_for_long_batch"
            if remaining is not None:
                floor = max(5.0, demand.predicted_quota_percent + demand.risk_reserve_percent)
                if float(remaining) <= floor:
                    return "quota_admission_floor"
        return None

    def _quota_scarcity_penalty(self, pool_id: str, demand: TaskDemand) -> float:
        snapshot = self.quota_snapshots.get(pool_id)
        if not snapshot:
            return 0.0
        raw = snapshot.to_dict() if isinstance(snapshot, QuotaSnapshot) else dict(snapshot)
        remaining = raw.get("remaining_percent")
        if remaining is None:
            return 0.0
        runtime = self.registry.routing_policy.get("runtime_routing") or {}
        weight = float((runtime.get("effective_cost_weights") or {}).get("quota_scarcity", 1.0))
        headroom = max(0.1, float(remaining) - 5.0)
        return weight / headroom
