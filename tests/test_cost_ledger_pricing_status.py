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