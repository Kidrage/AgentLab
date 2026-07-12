from __future__ import annotations

import pytest

from agent_runtime.costs.alerts import check_alerts
from agent_runtime.costs.attribution import attribute_spend, generate_attribution_report
from agent_runtime.costs.budget_policy import BudgetPolicy, load_budget_policy
from agent_runtime.costs.efficiency_review import generate_efficiency_review
from agent_runtime.costs.estimator import estimate_cost
from agent_runtime.costs.executor_cost_profile import load_executor_cost_profiles
from agent_runtime.costs.model_cost_profile import load_model_cost_profiles
from agent_runtime.costs.spend_ledger import (
    SpendLedger,
    load_spend_ledger,
    write_spend_ledger,
)
from agent_runtime.costs.worker_cost_profile import load_worker_cost_profiles
from agent_runtime.execution_economy.activation_cost import ActivationCost
from agent_runtime.execution_economy.effective_cost import (
    calculate_effective_tokens,
    estimate_cost_in_usd,
    get_cost_tier,
)
from agent_runtime.execution_economy.marginal_utility_gate import (
    evaluate_marginal_utility,
)


def test_activation_cost_round_trip() -> None:
    cost_dict = {
        "worker_id": "test_worker",
        "fixed_startup_cost": {
            "raw_prompt_tokens": 1000,
            "cacheable_prompt_tokens": 800,
            "expected_cache_hit_rate": 0.9,
            "effective_prompt_tokens": 280,
            "estimated_cached_input_discount": "high",
            "estimated_latency_s": 5.0,
            "operator_friction": "medium",
        },
        "cache_profile": {
            "stable_prefix_hash": "sha256:prefix",
            "skill_context_hash": "sha256:skills",
            "mcp_manifest_hash": "sha256:mcps",
            "last_cache_hit_observed": "true",
            "cache_confidence": "high",
        },
        "variable_cost": {
            "task_specific_context_tokens": 500,
            "context_tokens_per_kb": 10,
            "output_tokens_expected": 200,
            "dollars_per_call": "0.01",
        },
        "non_token_costs": {
            "coordination_cost": "medium",
            "permission_risk": "low",
            "state_mutation_risk": "low",
        },
        "hidden_costs": ["context_duplication"],
        "confidence": "high",
    }

    cost = ActivationCost.from_dict(cost_dict)
    assert cost.worker_id == "test_worker"
    assert cost.fixed_startup_cost.raw_prompt_tokens == 1000
    assert cost.cache_profile.last_cache_hit_observed == "true"
    assert cost.variable_cost.context_tokens_per_kb == 10
    assert cost.non_token_costs.coordination_cost == "medium"
    assert "context_duplication" in cost.hidden_costs

    serialized = cost.to_dict()
    assert serialized["worker_id"] == "test_worker"
    assert serialized["fixed_startup_cost"]["raw_prompt_tokens"] == 1000
    assert serialized["cache_profile"]["last_cache_hit_observed"] == "true"


def test_spend_attribution_and_report() -> None:
    ledger = SpendLedger("test_proj")
    ledger.record_spend({"task_id": "t1", "role": "coder", "cost_usd": 10.0})
    ledger.record_spend({"task_id": "t1", "role": "reviewer", "cost_usd": 5.0})

    attribution = attribute_spend(ledger)
    assert attribution["total_usd"] == 15.0
    assert attribution["by_task"]["t1"] == 15.0
    assert attribution["by_role"] == {"coder": 10.0, "reviewer": 5.0}
    report = generate_attribution_report(attribution)
    assert "Cost Attribution Report" in report
    assert "$15.00" in report


def test_budget_alert_levels() -> None:
    for spend, hard_limit, expected_level in (
        (15.0, 100.0, "warning"),
        (25.0, 20.0, "blocking"),
    ):
        policy = BudgetPolicy(
            project_soft_limit_usd=10.0,
            project_hard_limit_usd=hard_limit,
        )
        ledger = SpendLedger("test_proj")
        ledger.record_spend({"cost_usd": spend})
        alerts = check_alerts(policy, ledger)
        assert alerts
        assert alerts[0]["level"] == expected_level


def test_cost_profile_loaders(tmp_path) -> None:
    cases = (
        (
            "model_cost_profiles.yml",
            "models:\n  test_model:\n    input_usd_per_million_tokens: 1.0",
            load_model_cost_profiles,
            "test_model",
            "input_usd_per_million_tokens",
            1.0,
        ),
        (
            "executor_cost_profiles.yml",
            "executors:\n  test_exec:\n    billing_mode: unknown",
            load_executor_cost_profiles,
            "test_exec",
            "billing_mode",
            "unknown",
        ),
        (
            "worker_cost_profiles.yml",
            "workers:\n  test_worker:\n    role_markup: 2.0",
            load_worker_cost_profiles,
            "test_worker",
            "role_markup",
            2.0,
        ),
    )
    for index, (filename, content, loader, key, attribute, expected) in enumerate(cases):
        root = tmp_path / str(index)
        config_dir = root / "config"
        config_dir.mkdir(parents=True)
        (config_dir / filename).write_text(content, encoding="utf-8")
        profile = loader(root)[key]
        assert getattr(profile, attribute) == expected


def test_cost_estimation_marks_unknown_cli_cost_for_approval(tmp_path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "model_cost_profiles.yml").write_text(
        "models:\n  qwen:\n    input_usd_per_million_tokens: 1.0\n"
        "    output_usd_per_million_tokens: 2.0\n    cached_input_discount: 0.5",
        encoding="utf-8",
    )
    (config_dir / "executor_cost_profiles.yml").write_text(
        "executors:\n  cli:\n    direct_cost_visibility: unknown\n"
        "    requires_unknown_cost_approval: true",
        encoding="utf-8",
    )
    (config_dir / "worker_cost_profiles.yml").write_text(
        "workers:\n  coder:\n    role_markup: 1.5",
        encoding="utf-8",
    )
    packet = {
        "model": "qwen",
        "executor": "cli",
        "worker": "coder",
        "expected_input_tokens": 1_000_000,
        "cached_input_tokens": 500_000,
        "expected_output_tokens": 1_000_000,
    }

    result = estimate_cost(packet, tmp_path)

    assert "estimated_cost_usd" in result
    assert result["approval_required"] is True
    assert result["cost_visibility"] == "unknown_external_cli_cost"


def test_efficiency_review_reports_estimate_delta() -> None:
    ledger = SpendLedger("test_proj")
    ledger.record_spend({"task_id": "t1", "cost_usd": 15.0})

    report = generate_efficiency_review(ledger, {"t1": 10.0})

    assert "Efficiency Review for test_proj" in report
    assert "Est $10.00 | Act $15.00 | Diff $5.00" in report


def test_effective_cost_calculations() -> None:
    cost = ActivationCost.from_dict(
        {
            "worker_id": "claude_code",
            "fixed_startup_cost": {
                "raw_prompt_tokens": 10000,
                "cacheable_prompt_tokens": 8000,
                "expected_cache_hit_rate": 0.85,
            },
            "variable_cost": {"task_specific_context_tokens": 2000},
        }
    )

    effective_tokens = calculate_effective_tokens(cost)

    assert effective_tokens == 5200
    assert estimate_cost_in_usd(effective_tokens, "claude_code") == (5200 / 1000.0) * 0.015
    assert [get_cost_tier(value) for value in (0.0, 0.005, 0.05, 0.50)] == [
        "none",
        "low",
        "medium",
        "high",
    ]


def test_budget_policy_defaults_and_valid_override(tmp_path) -> None:
    default_policy = load_budget_policy(tmp_path)
    assert default_policy.version == 2
    assert default_policy.project_hard_limit_usd == 10.0

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cost_policy_v2.yml").write_text(
        "cost_policy:\n  project_hard_limit_usd: 100.0\n"
        "  project_soft_limit_usd: 50.0",
        encoding="utf-8",
    )
    assert load_budget_policy(tmp_path).project_hard_limit_usd == 100.0


def test_budget_policy_rejects_invalid_configuration(tmp_path) -> None:
    invalid_values = (
        "cost_policy: [invalid",
        "cost_policy:\n  project_hard_limit_usd: 10.0\n"
        "  project_soft_limit_usd: 50.0",
    )
    for index, value in enumerate(invalid_values):
        root = tmp_path / str(index)
        config_dir = root / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "cost_policy_v2.yml").write_text(value, encoding="utf-8")
        with pytest.raises(ValueError):
            load_budget_policy(root)


def test_marginal_utility_decisions() -> None:
    critical = ActivationCost.from_dict(
        {
            "worker_id": "claude_code",
            "non_token_costs": {"permission_risk": "critical"},
        }
    )
    assert evaluate_marginal_utility(critical, {})[:2] == (
        "require_approval",
        "unknown_requires_approval",
    )

    deterministic = ActivationCost.from_dict({"worker_id": "rg"})
    assert evaluate_marginal_utility(deterministic, {})[:2] == (
        "satisfy_by_deterministic",
        "justified",
    )

    high_risk = ActivationCost.from_dict(
        {
            "worker_id": "claude_code",
            "non_token_costs": {
                "permission_risk": "high",
                "state_mutation_risk": "high",
            },
        }
    )
    assert evaluate_marginal_utility(high_risk, {"quality_gain": "low"})[:2] == (
        "skip",
        "not_justified",
    )


def test_spend_ledger_round_trip(tmp_path) -> None:
    ledger = SpendLedger("test_proj")
    ledger.record_spend({"task_id": "t1", "cost_usd": 5.0})
    path = tmp_path / "ledger.yml"

    write_spend_ledger(ledger, path)
    loaded = load_spend_ledger(path)

    assert loaded.project == "test_proj"
    assert loaded.get_total() == 5.0
    assert loaded.get_total_by_task("t1") == 5.0
