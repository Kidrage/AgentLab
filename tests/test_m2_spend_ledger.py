from agent_runtime.costs.spend_ledger import SpendLedger, load_spend_ledger, write_spend_ledger

def test_spend_ledger_roundtrip(tmp_path):
    ledger = SpendLedger("test_proj")
    ledger.record_spend({"task_id": "t1", "cost_usd": 5.0})

    path = tmp_path / "ledger.yml"
    write_spend_ledger(ledger, path)

    loaded = load_spend_ledger(path)
    assert loaded.project == "test_proj"
    assert loaded.get_total() == 5.0
    assert loaded.get_total_by_task("t1") == 5.0
