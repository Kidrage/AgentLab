from agent_runtime.costs.budget_policy import BudgetPolicy
from agent_runtime.costs.spend_ledger import SpendLedger
from agent_runtime.costs.alerts import check_alerts

def test_alerts_soft_limit():
    policy = BudgetPolicy(project_soft_limit_usd=10.0, project_hard_limit_usd=100.0)
    ledger = SpendLedger("test_proj")
    ledger.record_spend({"cost_usd": 15.0})

    alerts = check_alerts(policy, ledger)
    assert len(alerts) > 0
    assert alerts[0]["level"] == "warning"

def test_alerts_hard_limit():
    policy = BudgetPolicy(project_soft_limit_usd=10.0, project_hard_limit_usd=20.0)
    ledger = SpendLedger("test_proj")
    ledger.record_spend({"cost_usd": 25.0})

    alerts = check_alerts(policy, ledger)
    assert len(alerts) > 0
    assert alerts[0]["level"] == "blocking"
