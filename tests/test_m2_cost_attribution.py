from agent_runtime.costs.spend_ledger import SpendLedger
from agent_runtime.costs.attribution import attribute_spend, generate_attribution_report

def test_attribution():
    ledger = SpendLedger("test_proj")
    ledger.record_spend({"task_id": "t1", "role": "coder", "cost_usd": 10.0})
    ledger.record_spend({"task_id": "t1", "role": "reviewer", "cost_usd": 5.0})

    attr = attribute_spend(ledger)
    assert attr["total_usd"] == 15.0
    assert attr["by_task"]["t1"] == 15.0
    assert attr["by_role"]["coder"] == 10.0
    assert attr["by_role"]["reviewer"] == 5.0

    report = generate_attribution_report(attr)
    assert "Cost Attribution Report" in report
    assert "$15.00" in report
