from datetime import datetime, timezone
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from agent_runtime.cli_executor import _write_runtime_usage_receipt, resolve_cli_profile
from agent_runtime.routing.dynamic_selector import DynamicRouteSelector
from agent_runtime.runtime_registry import RuntimeRegistry, resolve_dynamic_profile


ROOT = Path(__file__).resolve().parents[1]


def test_repository_runtime_registry_is_closed_and_secret_free():
    registry = RuntimeRegistry.load(ROOT)

    assert registry.validate() == []
    assert all("capacity_route" not in route for route in registry.routes.values())
    assert set(registry.data["role_routes"]) >= {
        "supervisor",
        "writer",
        "reviewer",
        "visual_reviewer",
        "narrative_planner",
    }


def test_registry_secret_scan_descends_into_nested_sequences():
    registry = RuntimeRegistry.load(ROOT)
    data = deepcopy(registry.data)
    data["shells"]["claude"]["nested_test"] = [
        {"headers": [{"api_key": "must-not-be-inline"}]}
    ]

    issues = RuntimeRegistry(
        root=ROOT,
        data=data,
        routing_policy=registry.routing_policy,
    ).validate()

    assert any(
        item["issue"] == "inline_secret_forbidden"
        and "nested_test.0.headers.0.api_key" in item["scope"]
        for item in issues
    )


def test_dynamic_profile_compiles_to_existing_executor_contract():
    profiles = yaml.safe_load(
        (ROOT / "config" / "agent_model_profiles.yml").read_text(encoding="utf-8")
    )

    supervisor = resolve_cli_profile(profiles, "supervisor", budget_mode="full")
    writer = resolve_cli_profile(profiles, "writer", budget_mode="performance")

    assert supervisor["resolved_schema"] == "dynamic_runtime_v1"
    assert supervisor["runtime_route_id"] == "supervisor_codex"
    assert supervisor["cli_agent"] == "hermes"
    assert supervisor["default"] == "codex_gpt_5_5_high_hermes_oauth"
    assert supervisor["invocation_contract"] == "hermes_supervisor"
    assert supervisor["execution_channel"] == "json_rpc_ws"
    assert supervisor["runtime_channel_config"]["auto_start"] is True
    assert "capacity_route" not in supervisor
    assert writer["runtime_route_id"] == "writer_pro"
    assert writer["cli_agent"] == "claude_code"
    assert writer["default"] == "deepseek_v4_pro"
    assert "capacity_route" not in writer


def test_dynamic_profile_uses_task_tokens_and_run_local_quota_ledger(tmp_path: Path):
    profiles = yaml.safe_load(
        (ROOT / "config" / "agent_model_profiles.yml").read_text(encoding="utf-8")
    )
    ledger = tmp_path / "model_capacity_ledger.yml"
    ledger.write_text(
        yaml.safe_dump(
            {
                "pools": {
                    "openai_codex_agentic": {
                        "status": "open",
                        "remaining_percent": 4.0,
                        "quota_observed_at": "2099-07-15T01:00:00Z",
                        "quota_stale_at": "2099-07-15T01:10:00Z",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    profile = resolve_dynamic_profile(
        profiles,
        agent_role="supervisor",
        resolved_mode="full_cli",
        resolved_tier="full",
        root=ROOT,
        routing_context={
            "predicted_input_tokens": 8_000,
            "predicted_output_tokens": 4_000,
            "predicted_quota_percent": 3.0,
            "risk_reserve_percent": 3.0,
            "checkpoint_complete": True,
            "quota_ledger_path": ledger,
            "checkpoint_id": "task_001:Supervisor",
        },
    )

    assert profile is not None
    assert profile["runtime_route_id"] == "supervisor_deepseek"
    assert profile["route_decision"]["demand"]["predicted_input_tokens"] == 8_000
    assert profile["route_decision"]["demand"]["predicted_output_tokens"] == 4_000
    assert profile["route_decision"]["cost"]["native_amount"] > 0
    assert profile["route_decision"]["checkpoint_id"] == "task_001:Supervisor"


def test_registry_keeps_grok_route_quarantined():
    registry = RuntimeRegistry.load(ROOT)

    route = registry.routes["researcher_grok_quarantined"]
    model = registry.models[route["identity"]["model_id"]]

    assert route["status"] == "quarantined"
    assert model["status"] == "quarantined"


def test_every_registered_role_has_a_route_in_every_runtime_tier():
    registry = RuntimeRegistry.load(ROOT)
    selector = DynamicRouteSelector(registry)

    for tier in ("full", "performance", "low"):
        for role in registry.data["role_routes"]:
            decision = selector.select(registry.task_demand(role, preset=tier))
            assert decision["status"] == "selected", (tier, role, decision)


def test_dynamic_runtime_does_not_fall_back_to_legacy_matrix(monkeypatch):
    profiles = yaml.safe_load(
        (ROOT / "config" / "agent_model_profiles.yml").read_text(encoding="utf-8")
    )
    monkeypatch.setattr(
        "agent_runtime.runtime_registry.resolve_dynamic_profile",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(RuntimeError, match="failed closed"):
        resolve_cli_profile(profiles, "writer", budget_mode="performance")


def test_compatibility_matrix_is_compiled_from_current_runtime_routes():
    registry = RuntimeRegistry.load(ROOT)
    selector = DynamicRouteSelector(registry)
    profiles = yaml.safe_load(
        (ROOT / "config" / "agent_model_profiles.yml").read_text(encoding="utf-8")
    )
    tiers = profiles["modes"]["full_cli"]["tiers"]

    for tier_name, tier in tiers.items():
        for role in registry.data["role_routes"]:
            decision = selector.select(registry.task_demand(role, preset=tier_name))
            compiled = registry.compile_legacy_profile(
                decision["route_id"],
                resolved_mode="full_cli",
                resolved_tier=tier_name,
            )
            compatibility = tier[role]
            assert compatibility["cli_agent"] == compiled["cli_agent"]
            assert compatibility["invocation_contract"] == compiled["invocation_contract"]
            assert compatibility["default"] == compiled["default"]


def test_dynamic_execution_writes_versioned_native_and_cny_receipt(tmp_path: Path):
    started = datetime(2026, 7, 15, 1, 0, tzinfo=timezone.utc)
    completed = datetime(2026, 7, 15, 1, 1, tzinfo=timezone.utc)

    path, error = _write_runtime_usage_receipt(
        agentlab_root=ROOT,
        run_dir=tmp_path,
        agent_name="Writer",
        role_profile={"runtime_route_id": "writer_pro"},
        usage={
            "input_tokens": 1000,
            "output_tokens": 500,
            "usage_source": "provider_reported",
            "exact_usage_available": True,
        },
        started_at=started,
        completed_at=completed,
        execution_status="completed",
        execution_channel="cli_subprocess",
    )

    assert error is None
    receipt = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["usage_receipt"]
    assert receipt["route_id"] == "writer_pro"
    assert receipt["identity"]["shell_id"] == "claude"
    assert receipt["native_currency"] == "USD"
    assert receipt["native_cost"] > 0
    assert receipt["cost_cny"] > receipt["native_cost"]
    assert receipt["pricing_version"] == "2026-07-15.2"
    assert receipt["pricing_source"] == "config/model_pricing.yml#deepseek-v4-pro"
    assert receipt["fx_version"] == "2026-07-15-operational"
    assert receipt["execution_channel"] == "cli_subprocess"


def test_dynamic_execution_does_not_price_inexact_cli_estimates(tmp_path: Path):
    path, error = _write_runtime_usage_receipt(
        agentlab_root=ROOT,
        run_dir=tmp_path,
        agent_name="Writer",
        role_profile={"runtime_route_id": "writer_pro"},
        usage={
            "input_tokens": 999,
            "output_tokens": 333,
            "usage_source": "external_cli_estimate",
            "exact_usage_available": False,
        },
        started_at=datetime(2026, 7, 15, 1, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 7, 15, 1, 1, tzinfo=timezone.utc),
        execution_status="completed",
        execution_channel="cli_subprocess",
    )

    assert error is None
    receipt = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["usage_receipt"]
    assert receipt["input_tokens"] is None
    assert receipt["output_tokens"] is None
    assert receipt["native_cost"] is None
    assert receipt["cost_cny"] is None
    assert receipt["cost_exact"] is False


def test_subscription_receipt_keeps_exact_zero_cash_without_token_telemetry(
    tmp_path: Path,
):
    path, error = _write_runtime_usage_receipt(
        agentlab_root=ROOT,
        run_dir=tmp_path,
        agent_name="Supervisor",
        role_profile={"runtime_route_id": "supervisor_codex"},
        usage={
            "usage_source": "external_cli_unavailable",
            "exact_usage_available": False,
        },
        started_at=datetime(2026, 7, 15, 1, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 7, 15, 1, 1, tzinfo=timezone.utc),
        execution_status="completed",
        execution_channel="hermes_json_rpc_ws",
    )

    assert error is None
    receipt = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["usage_receipt"]
    assert receipt["input_tokens"] is None
    assert receipt["output_tokens"] is None
    assert receipt["native_cost"] == 0.0
    assert receipt["cost_cny"] == 0.0
    assert receipt["cost_exact"] is True
    assert receipt["cash_basis"] == "marginal_task_cash"


def test_runtime_usage_receipts_are_immutable_per_attempt(tmp_path: Path):
    kwargs = {
        "agentlab_root": ROOT,
        "run_dir": tmp_path,
        "agent_name": "Writer",
        "role_profile": {"runtime_route_id": "writer_pro"},
        "usage": {
            "input_tokens": 100,
            "output_tokens": 20,
            "usage_source": "provider_reported",
            "exact_usage_available": True,
        },
        "started_at": datetime(2026, 7, 15, 1, 0, tzinfo=timezone.utc),
        "completed_at": datetime(2026, 7, 15, 1, 1, tzinfo=timezone.utc),
        "execution_status": "completed",
        "execution_channel": "cli_subprocess",
    }

    first, first_error = _write_runtime_usage_receipt(**kwargs)
    second, second_error = _write_runtime_usage_receipt(**kwargs)

    assert first_error is None
    assert second_error is None
    assert first != second
    assert len(list(tmp_path.glob("usage_receipt_writer_*.yml"))) == 2
