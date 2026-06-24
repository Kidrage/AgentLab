from agent_runtime.costs.spend_ledger import SpendLedger
from agent_runtime.costs.alerts import check_alerts

def test_alerts():
    ledger = SpendLedger()
    ledger.record("A", "B", "C", "D", 6.0)
    policy = {"cost_policy": {"hard_limit_usd": 10.0, "soft_limit_usd": 5.0}}
    assert check_alerts(ledger, policy) == "SOFT_LIMIT_EXCEEDED"
    
    ledger.record("A", "B", "C", "D", 5.0)
    assert check_alerts(ledger, policy) == "HARD_LIMIT_EXCEEDED"
