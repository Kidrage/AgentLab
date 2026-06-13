from __future__ import annotations

from pathlib import Path

from agent_runtime.retry import RetryAttempt
from agent_runtime.retry.attempt_ledger import load_retry_attempt_ledger, record_retry_attempt, write_retry_attempt_ledger


def test_retry_attempt_ledger_records_each_attempt(tmp_path: Path):
    path = tmp_path / "retry_attempt_ledger.yml"
    record_retry_attempt(path, "task", RetryAttempt("task", "attempt_001", 1, "p", "mock_executor", "mock"))
    record_retry_attempt(path, "task", RetryAttempt("task", "attempt_002", 2, "p", "mock_executor", "mock"))
    assert len(load_retry_attempt_ledger(path)["attempts"]) == 2


def test_retry_attempt_ledger_round_trip_yaml(tmp_path: Path):
    path = tmp_path / "retry_attempt_ledger.yml"
    ledger = {"task_id": "task", "attempts": [{"attempt_id": "attempt_001", "status": "review_failed"}]}
    write_retry_attempt_ledger(path, ledger)
    assert load_retry_attempt_ledger(path) == ledger


def test_retry_attempt_ledger_redacts_secrets(tmp_path: Path):
    path = tmp_path / "retry_attempt_ledger.yml"
    attempt = RetryAttempt(
        "task",
        "attempt_001",
        1,
        "OPENAI_API_KEY=sk-testsecret",
        "mock_executor",
        "mock",
        failure_reasons=["GITHUB_TOKEN=secret"],
    )
    record_retry_attempt(path, "task", attempt)
    text = path.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" not in text
    assert "GITHUB_TOKEN" not in text
    assert "sk-testsecret" not in text
