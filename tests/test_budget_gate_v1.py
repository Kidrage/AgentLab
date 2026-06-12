from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from costing.budget import evaluate_budget_gate
from costing.ledger import CostCall, CostLedger


def test_budget_gate_warns_when_cost_over_threshold() -> None:
    ledger = CostLedger(task_id="task_cost", calls=[
        CostCall(
            stage="Coder",
            agent="Coder",
            model_alias="known",
            input_tokens=1000,
            output_tokens=1000,
            estimated_cost_usd=0.12,
            pricing_confidence="high",
            price_source="config/model_pricing.yml",
        )
    ])

    decision = evaluate_budget_gate(ledger, {"require_approval_over_usd": 0.10, "max_total_tokens": 200000})

    assert decision.status == "pending_approval"
    assert decision.approval_required is True
    assert decision.warnings


def test_budget_gate_warns_on_unknown_price_high_tokens() -> None:
    ledger = CostLedger(task_id="task_tokens", calls=[
        CostCall(
            stage="Supervisor",
            agent="Supervisor",
            model_alias="unknown",
            input_tokens=150000,
            output_tokens=60000,
            estimated_cost_usd=None,
            pricing_confidence="none",
            price_source="unknown",
        )
    ])

    decision = evaluate_budget_gate(ledger, {
        "require_approval_over_usd": 0.10,
        "max_total_tokens": 200000,
        "unknown_price_warning": True,
    })

    assert decision.status == "warning"
    assert decision.approval_required is False
    assert any("Unknown pricing" in warning for warning in decision.warnings or [])
