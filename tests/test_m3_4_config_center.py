"""M3-4 Config Center — source tracing, views, and change gating tests."""

from __future__ import annotations

from agent_runtime.config_center.source_trace import trace_config_source, trace_all_config_sources, _deep_get, _MISSING
from agent_runtime.config_center.change_gate import (
    gate_config_change,
    _classify_risk,
    is_external_execution_disabled_by_default,
    HIGH_RISK_KEY_PREFIXES,
    DOUBLE_APPROVAL_KEYS,
)


def test_deep_get_finds_nested_value() -> None:
    """_deep_get should find values at any depth."""
    data = {"a": {"b": {"c": "found"}}}
    assert _deep_get(data, ["a", "b", "c"]) == "found"


def test_deep_get_returns_missing_for_absent_key() -> None:
    """_deep_get should return _MISSING for absent keys."""
    data = {"a": {"b": "val"}}
    result = _deep_get(data, ["a", "c"])
    assert result is _MISSING


def test_trace_config_source_finds_origin() -> None:
    """trace_config_source should identify the first layer that defines a key."""
    layers = {
        "global_defaults": {"budget_policy": {"max_task_cost_usd": 0.20}},
        "project_overrides": {"budget_policy": {"max_task_cost_usd": 0.50}},
        "runtime_overrides": {},
    }
    merged = {"budget_policy": {"max_task_cost_usd": 0.50}}
    result = trace_config_source("budget_policy.max_task_cost_usd", merged, layers)
    assert result["source_layer"] == "global_defaults"
    assert result["value"] == 0.50
    assert "project_overrides" in result["overridden_by"]


def test_trace_all_config_sources_multiple_keys() -> None:
    """trace_all_config_sources should find all leaf keys."""
    layers = {
        "defaults": {"key_a": "a_val", "key_b": "b_val"},
    }
    merged = {"key_a": "a_val", "key_b": "b_val"}
    results = trace_all_config_sources(merged, layers)
    assert len(results) == 2
    keys = {r["key"] for r in results}
    assert "key_a" in keys
    assert "key_b" in keys


def test_classify_risk_critical_keys() -> None:
    """Critical keys (executor enablement, public bind) must be risk-critical."""
    for key in DOUBLE_APPROVAL_KEYS:
        assert _classify_risk(key) == "critical", f"{key} should be critical"


def test_classify_risk_high_keys() -> None:
    """High-risk keys must be risk-high."""
    non_critical_high = [k for k in HIGH_RISK_KEY_PREFIXES if k not in DOUBLE_APPROVAL_KEYS]
    for key in non_critical_high:
        assert _classify_risk(key) == "high", f"{key} should be high risk"


def test_classify_risk_low_keys() -> None:
    """Unknown keys should be low risk."""
    assert _classify_risk("unknown.random.config") == "low"


def test_gate_config_change_no_change_allowed() -> None:
    """No-change should be auto-allowed."""
    result = gate_config_change("budget_policy.max_task_cost_usd", 0.20, 0.20)
    assert result["allowed"] is True
    assert result["risk_level"] == "low"


def test_gate_config_change_critical_blocked() -> None:
    """Critical config changes must be blocked without approval."""
    result = gate_config_change(
        "execution_policy.external_executor_enablement",
        False, True,
    )
    assert result["allowed"] is False
    assert result["requires_approval"] is True
    assert result["requires_double_approval"] is True


def test_gate_config_change_high_requires_approval() -> None:
    """High-risk changes must require approval."""
    result = gate_config_change(
        "budget_policy.max_task_cost_usd",
        0.20, 5.00,
    )
    assert result["allowed"] is False
    assert result["requires_approval"] is True


def test_external_execution_default_disabled() -> None:
    """Default config must have external executor disabled."""
    config = {"execution_policy": {"external_executor_enablement": False}}
    assert is_external_execution_disabled_by_default(config) is True

    config2 = {"execution_policy": {"external_executor_enablement": True}}
    assert is_external_execution_disabled_by_default(config2) is False
