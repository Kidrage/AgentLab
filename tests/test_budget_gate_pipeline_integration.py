from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from cost_tracker import append_cost_ledgers
from costing.budget import evaluate_budget_gate
from costing.ledger import CostCall, CostLedger


def test_budget_decision_written_after_cost_ledger(tmp_path: Path) -> None:
    project_root = tmp_path / "projects" / "Demo"
    run_dir = project_root / "runs" / "task_budget"
    (project_root / "agent_docs").mkdir(parents=True)
    append_cost_ledgers(project_root, run_dir, {
        "task_id": "task_budget",
        "agent": "Supervisor",
        "model": "unknown",
        "input_tokens": 1,
        "output_tokens": 1,
        "estimated_cost": 0.0,
    })
    assert (run_dir / "budget_gate_decision.yml").exists()
    data = yaml.safe_load((run_dir / "budget_gate_decision.yml").read_text(encoding="utf-8"))
    assert data["status"] == "ok"


def test_unknown_price_high_tokens_budget_warning() -> None:
    ledger = CostLedger(task_id="task", calls=[
        CostCall(stage="S", agent="S", model_alias="unknown", input_tokens=150000, output_tokens=60000)
    ])
    decision = evaluate_budget_gate(ledger, {"max_total_tokens": 200000, "unknown_price_warning": True})
    assert decision.status == "warning"
    assert decision.estimated_cost_usd is None