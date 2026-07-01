"""M3-5 Cost System v2 — attribution, alerts, and efficiency report tests."""

from __future__ import annotations

from agent_runtime.costing.attribution import (
    attribute_cost_by_phase,
    attribute_cost_by_task,
    build_cost_efficiency_report,
    calculate_retry_cost_impact,
)
from agent_runtime.costing.alerts import check_budget_alerts


SAMPLE_CALLS = [
    {
        "task_id": "task_001",
        "stage": "phase_1",
        "agent": "coder",
        "model_alias": "deepseek-v4-pro",
        "estimated_cost_usd": 0.015,
        "input_tokens": 5000,
        "output_tokens": 2000,
    },
    {
        "task_id": "task_001",
        "stage": "phase_1",
        "agent": "supervisor",
        "model_alias": "qwen3.6-plus",
        "estimated_cost_usd": 0.012,
        "input_tokens": 3000,
        "output_tokens": 1000,
    },
    {
        "task_id": "task_002",
        "stage": "phase_2",
        "agent": "coder",
        "model_alias": "qwen3-coder-next",
        "estimated_cost_usd": 0.008,
        "input_tokens": 4000,
        "output_tokens": 1500,
    },
    {
        "task_id": "task_003",
        "stage": "phase_2",
        "agent": "tester_auditor",
        "model_alias": "qwen3.6-plus",
        "estimated_cost_usd": 0.005,
        "input_tokens": 2000,
        "output_tokens": 800,
    },
]


def test_attribute_cost_by_phase() -> None:
    """Cost should be correctly attributed to phases."""
    result = attribute_cost_by_phase(SAMPLE_CALLS, {})
    phases = result["phases"]
    assert "phase_1" in phases
    assert "phase_2" in phases
    assert phases["phase_1"]["call_count"] == 2
    assert phases["phase_1"]["total_cost"] == 0.027
    assert phases["phase_2"]["call_count"] == 2
    assert phases["phase_2"]["total_cost"] == 0.013
    assert result["phase_count"] == 2


def test_attribute_cost_by_task() -> None:
    """Cost should be correctly attributed to tasks."""
    result = attribute_cost_by_task(SAMPLE_CALLS)
    tasks = result["tasks"]
    assert tasks["task_001"]["call_count"] == 2
    assert tasks["task_001"]["total_cost"] == 0.027
    assert tasks["task_002"]["total_cost"] == 0.008
    assert tasks["task_003"]["total_cost"] == 0.005
    assert result["task_count"] == 3


def test_build_cost_efficiency_report() -> None:
    """Efficiency report should aggregate by model and executor."""
    report = build_cost_efficiency_report(SAMPLE_CALLS, accepted_phase_ids=["phase_1"])
    assert report["highest_cost_model"] is not None
    assert report["highest_cost_executor"] is not None
    assert report["total_cost"] == 0.04
    # cost_per_accepted_phase
    assert report["cost_per_accepted_phase"] == 0.04  # 1 accepted phase
    # by_model
    assert "qwen3.6-plus" in report["by_model"]
    assert "deepseek-v4-pro" in report["by_model"]
    # by_executor
    assert "coder" in report["by_executor"]


def test_calculate_retry_cost_impact() -> None:
    """Retry cost impact should correctly identify retried task costs."""
    retry_ledger = [
        {"task_id": "task_001", "retry_count": 1},
    ]
    result = calculate_retry_cost_impact(SAMPLE_CALLS, retry_ledger)
    assert result["total_retry_cost"] == 0.027
    assert result["retry_count"] == 1
    assert "task_001" in result["retried_task_ids"]
    assert result["retry_cost_pct"] > 0


def test_check_budget_alerts_no_alerts() -> None:
    """Under-threshold usage should produce no alerts."""
    alerts = check_budget_alerts(0.05, 50_000)
    # 0.05 < 0.10 approval_threshold → no alerts or just info (if above 0)
    # Actually, 0.05 < 0.10 so no approval threshold alert either
    assert len(alerts) == 0


def test_check_budget_alerts_approval_threshold() -> None:
    """Cost above approval threshold should produce info alert."""
    alerts = check_budget_alerts(0.12, 50_000)
    levels = {a["level"] for a in alerts}
    assert "info" in levels


def test_check_budget_alerts_warning_and_critical() -> None:
    """Cost near/at max should produce warning/critical alerts."""
    # at 80% of max (0.16 / 0.20)
    alerts = check_budget_alerts(0.16, 180_000)
    levels = {a["level"] for a in alerts}
    assert "warning" in levels  # cost warning
    assert "warning" in levels  # token warning

    # at max
    alerts2 = check_budget_alerts(0.25, 250_000)
    levels2 = {a["level"] for a in alerts2}
    assert "critical" in levels2


def test_attribute_empty_calls() -> None:
    """Empty calls should produce valid empty results."""
    assert attribute_cost_by_phase([], {})["phase_count"] == 0
    assert attribute_cost_by_task([])["task_count"] == 0
    report = build_cost_efficiency_report([])
    assert report["total_cost"] == 0.0
    assert report["highest_cost_model"] is None
    assert report["cost_per_accepted_phase"] is None
