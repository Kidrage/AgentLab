from datetime import datetime, timedelta, timezone
from copy import deepcopy
from pathlib import Path

from agent_runtime.routing.dynamic_selector import DynamicRouteSelector
from agent_runtime.runtime_registry import QuotaSnapshot, RuntimeRegistry


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc)


def _snapshot(pool: str, status: str, remaining: float | None) -> QuotaSnapshot:
    return QuotaSnapshot(
        credential_pool_id=pool,
        status=status,
        observed_at=NOW.isoformat(),
        stale_at=(NOW + timedelta(minutes=10)).isoformat(),
        remaining_percent=remaining,
        reset_at=(NOW + timedelta(hours=1)).isoformat(),
        confidence="high",
    )


def test_presets_are_quality_floors_not_fixed_model_matrices():
    registry = RuntimeRegistry.load(ROOT)
    selector = DynamicRouteSelector(registry)

    full = selector.select(registry.task_demand("writer", preset="full"))
    performance = selector.select(registry.task_demand("writer", preset="performance"))
    low = selector.select(registry.task_demand("writer", preset="low"))

    assert full["route_id"] == "writer_pro"
    assert performance["route_id"] == "writer_pro"
    assert low["route_id"] == "writer_flash"
    assert low["cost"]["effective_cost_cny"] < full["cost"]["effective_cost_cny"]


def test_subscription_route_wins_only_after_quality_and_quota_filters():
    registry = RuntimeRegistry.load(ROOT)
    demand = registry.task_demand("supervisor", preset="full")

    healthy = DynamicRouteSelector(registry).select(demand)
    exhausted = DynamicRouteSelector(
        registry,
        quota_snapshots={"codex_oauth": _snapshot("codex_oauth", "quota_reserve", 4.0)},
    ).select(demand)

    assert healthy["route_id"] == "supervisor_codex"
    assert exhausted["route_id"] == "supervisor_deepseek"
    assert any(item["reason"] == "quota_reserve" for item in exhausted["rejected_routes"])


def test_fallback_switch_is_rejected_mid_checkpoint():
    registry = RuntimeRegistry.load(ROOT)
    demand = registry.task_demand("supervisor", preset="full", checkpoint_complete=False)
    decision = DynamicRouteSelector(
        registry,
        quota_snapshots={"codex_oauth": _snapshot("codex_oauth", "quota_reserve", 4.0)},
    ).select(demand)

    assert decision["status"] == "blocked"
    assert any(
        item["reason"] == "provider_switch_requires_checkpoint_boundary"
        for item in decision["rejected_routes"]
    )


def test_long_batch_rejects_oauth_route_without_fresh_quota_telemetry():
    registry = RuntimeRegistry.load(ROOT)
    demand = registry.task_demand("observer", preset="performance", long_batch=True)

    decision = DynamicRouteSelector(registry).select(demand)

    assert decision["status"] == "blocked"
    assert decision["rejected_routes"]
    assert all(
        item["reason"] == "quota_telemetry_missing_for_long_batch"
        for item in decision["rejected_routes"]
    )


def test_long_batch_rejects_reachability_without_remaining_quota():
    registry = RuntimeRegistry.load(ROOT)
    snapshot = _snapshot("agy_gemini", "available", None)
    decision = DynamicRouteSelector(
        registry,
        quota_snapshots={"agy_gemini": snapshot},
    ).select(registry.task_demand("researcher", preset="performance", long_batch=True))

    assert decision["status"] == "blocked"
    assert decision["rejected_routes"][0]["reason"] == (
        "quota_telemetry_degraded_for_long_batch"
    )


def test_qwen_is_selected_by_exact_capability_not_visual_family_label():
    registry = RuntimeRegistry.load(ROOT)
    selector = DynamicRouteSelector(registry)

    ordinary = selector.select(registry.task_demand("visual_reviewer", preset="performance"))
    video = selector.select(
        registry.task_demand(
            "visual_reviewer",
            preset="performance",
            required_modalities=["video"],
        )
    )

    assert ordinary["route_id"] == "visual_reviewer_gemini"
    assert video["route_id"] == "visual_reviewer_gemini"
    assert "visual_reviewer_qwen" not in video["eligible_routes"]


def test_visual_reviewer_uses_independent_agy_claude_pool_before_metered_qwen():
    registry = RuntimeRegistry.load(ROOT)
    decision = DynamicRouteSelector(
        registry,
        quota_snapshots={
            "agy_gemini": _snapshot("agy_gemini", "quota_reserve", 4.0),
            "agy_claude": _snapshot("agy_claude", "available", 80.0),
        },
    ).select(
        registry.task_demand(
            "visual_reviewer",
            preset="performance",
            required_modalities=["image"],
        )
    )

    assert decision["route_id"] == "visual_reviewer_claude"
    assert decision["identity"]["credential_pool_id"] == "agy_claude"


def test_visual_reviewer_does_not_use_claude_or_qwen_for_unsupported_video():
    registry = RuntimeRegistry.load(ROOT)
    decision = DynamicRouteSelector(
        registry,
        quota_snapshots={
            "agy_gemini": _snapshot("agy_gemini", "quota_reserve", 4.0),
            "agy_claude": _snapshot("agy_claude", "available", 80.0),
        },
    ).select(
        registry.task_demand(
            "visual_reviewer",
            preset="performance",
            required_modalities=["video"],
        )
    )

    assert decision["status"] == "blocked"
    reasons = {item["route_id"]: item["reason"] for item in decision["rejected_routes"]}
    assert reasons["visual_reviewer_claude"].startswith("unsupported_modalities")
    assert reasons["visual_reviewer_qwen"].startswith("unsupported_modalities")


def test_qwen_model_strengths_are_all_reachable_behind_quality_floors():
    registry = RuntimeRegistry.load(ROOT)
    selector = DynamicRouteSelector(registry)

    selected = {}
    for tier in ("full", "performance", "low"):
        decision = selector.select(
            registry.task_demand(
                "visual_reviewer",
                preset=tier,
                required_modalities=["image"],
                allowed_provider_ids=["dashscope_api"],
                predicted_input_tokens=1_000_000,
                predicted_output_tokens=1_000_000,
            )
        )
        assert decision["status"] == "selected", decision
        selected[tier] = decision["identity"]["model_id"]

    assert selected == {
        "full": "qwen3_7_max_dashscope",
        "performance": "qwen3_6_plus_dashscope",
        "low": "qwen3_6_flash_dashscope",
    }


def test_project_provider_allowlist_is_a_hard_privacy_gate():
    registry = RuntimeRegistry.load(ROOT)
    demand = registry.task_demand(
        "visual_reviewer",
        preset="performance",
        allowed_provider_ids=["deepseek_api"],
    )

    decision = DynamicRouteSelector(registry).select(demand)

    assert decision["status"] == "blocked"
    assert all(item["reason"] == "provider_not_in_project_allowlist" for item in decision["rejected_routes"])


def test_disabled_provider_cannot_be_reactivated_by_an_active_route():
    base = RuntimeRegistry.load(ROOT)
    data = deepcopy(base.data)
    data["providers"]["deepseek_api"]["status"] = "disabled"
    registry = RuntimeRegistry(root=base.root, data=data, routing_policy=base.routing_policy)

    decision = DynamicRouteSelector(registry).select(
        registry.task_demand(
            "writer",
            preset="performance",
            allowed_provider_ids=["deepseek_api"],
        )
    )

    assert decision["status"] == "blocked"
    assert all(item["reason"] == "provider_disabled" for item in decision["rejected_routes"])


def test_model_scoped_failure_does_not_downgrade_below_quality_floor():
    registry = RuntimeRegistry.load(ROOT)
    decision = DynamicRouteSelector(
        registry,
        route_states={
            "visual_reviewer_qwen": {
                "status": "blocked",
                "failure_class": "model_unavailable",
            }
        },
    ).select(
        registry.task_demand(
            "visual_reviewer",
            preset="full",
            required_modalities=["image"],
            allowed_provider_ids=["dashscope_api"],
        )
    )

    assert decision["status"] == "blocked"
    assert any(
        item["route_id"] == "visual_reviewer_qwen"
        and item["reason"] == "model_unavailable"
        for item in decision["rejected_routes"]
    )


def test_unclassified_failure_does_not_repeat_the_same_route_at_next_checkpoint():
    registry = RuntimeRegistry.load(ROOT)
    decision = DynamicRouteSelector(
        registry,
        route_states={
            "supervisor_codex": {
                "status": "unknown",
                "failure_class": "unknown",
            }
        },
    ).select(registry.task_demand("supervisor", preset="full"))

    assert decision["route_id"] == "supervisor_deepseek"
    assert any(
        item["route_id"] == "supervisor_codex" and item["reason"] == "unknown"
        for item in decision["rejected_routes"]
    )
