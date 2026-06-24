from agent_runtime.costs.spend_ledger import SpendLedger

def test_spend_ledger():
    ledger = SpendLedger()
    ledger.record("Coder", "worker1", "gpt-4", "cli", 2.0)
    assert ledger.get_total() == 2.0
    assert ledger.entries[0]["worker"] == "worker1"
