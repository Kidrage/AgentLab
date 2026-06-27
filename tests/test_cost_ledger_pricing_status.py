from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from costing.ledger import CostCall, CostLedger, render_cost_summary


def test_pricing_status_partial_with_unknown_call() -> None:
    ledger = CostLedger(task_id="task", calls=[
        CostCall(stage="A", agent="A", model_alias="known", estimated_cost_usd=0.01),
        CostCall(stage="B", agent="B", model_alias="qwen3.6-flash", estimated_cost_usd=None),
    ])
    assert ledger.total()["pricing_status"] == "partial"
    summary = render_cost_summary(ledger)
    assert "Pricing status: partial" in summary
    assert "- qwen3.6-flash" in summary


def test_pricing_status_unknown_all_unknown() -> None:
    ledger = CostLedger(task_id="task", calls=[CostCall(stage="A", agent="A", model_alias="unknown")])
    assert ledger.total()["pricing_status"] == "unknown"


def test_pricing_status_complete_all_known() -> None:
    ledger = CostLedger(task_id="task", calls=[CostCall(stage="A", agent="A", model_alias="known", estimated_cost_usd=0.01)])
    assert ledger.total()["pricing_status"] == "complete"


def test_usage_status_partial_with_estimated_cli_call() -> None:
    ledger = CostLedger(task_id="task", calls=[
        CostCall(
            stage="A",
            agent="A",
            model_alias="api-model",
            input_tokens=10,
            output_tokens=5,
            usage_source="api_usage",
            exact_usage_available=True,
            estimated_cost_usd=0.01,
            exact_cost_available=True,
        ),
        CostCall(
            stage="B",
            agent="B",
            model_alias="hermes",
            input_tokens=100,
            output_tokens=20,
            usage_source="external_cli_estimate",
            exact_usage_available=False,
            token_estimation_method="chars_div_4_packet_command_stdout_stderr",
        ),
    ])
    total = ledger.total()
    assert total["usage_status"] == "partial"
    assert total["pricing_status"] == "partial"
    summary = render_cost_summary(ledger)
    assert "Usage status: partial" in summary
    assert "Estimated usage calls:" in summary
    assert "external_cli_estimate" in summary
