import yaml

from agent_runtime.executors.ledger import load_execution_ledger, record_execution_event


def test_execution_ledger_records_route_event(tmp_path):
    path = tmp_path / "execution_ledger.yml"
    record_execution_event(path, "task", "routed", "agentlab.mock_patch", "mock_executor", "mock", "ROUTED")
    assert yaml.safe_load(path.read_text())["entries"][0]["event"] == "routed"


def test_execution_ledger_records_handoff_event(tmp_path):
    path = tmp_path / "execution_ledger.yml"
    record_execution_event(path, "task", "handoff_created", "manual.codex", "codex_cli", "manual_handoff_only", "NEEDS_APPROVAL")
    assert yaml.safe_load(path.read_text())["entries"][0]["event"] == "handoff_created"


def test_execution_ledger_records_result_ingestion(tmp_path):
    path = tmp_path / "execution_ledger.yml"
    record_execution_event(path, "task", "result_ingested", "agentlab.mock_patch", "mock_executor", "mock", "PASS")
    assert yaml.safe_load(path.read_text())["entries"][0]["event"] == "result_ingested"


def test_execution_ledger_round_trip_yaml(tmp_path):
    path = tmp_path / "execution_ledger.yml"
    record_execution_event(path, "task", "routed", "p", "t", "m", "ROUTED")
    ledger = load_execution_ledger(path)
    assert ledger["task_id"] == "task"
    assert ledger["entries"][0]["status"] == "ROUTED"


def test_execution_ledger_does_not_record_secrets(tmp_path):
    path = tmp_path / "execution_ledger.yml"
    record_execution_event(path, "task", "routed", "p", "t", "m", "ROUTED", ["OPENAI_API_KEY=sk_secret"])
    assert "OPENAI_API_KEY" not in path.read_text()
    assert "sk_secret" not in path.read_text()
