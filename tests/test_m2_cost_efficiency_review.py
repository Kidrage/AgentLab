from agent_runtime.costs.spend_ledger import SpendLedger
from agent_runtime.costs.efficiency_review import generate_efficiency_review

def test_efficiency_review():
    ledger = SpendLedger("test_proj")
    ledger.record_spend({"task_id": "t1", "cost_usd": 15.0})

    estimates = {"t1": 10.0}
    report = generate_efficiency_review(ledger, estimates)
    assert "Efficiency Review for test_proj" in report
    assert "Est $10.00 | Act $15.00 | Diff $5.00" in report
