from __future__ import annotations

from pathlib import Path

from agent_runtime.retry.policy import load_retry_policy
from agent_runtime.retry.scorecard import load_provider_scorecard, update_provider_scorecard


def _policy():
    return load_retry_policy(Path("config/retry_policy.yml"))


def test_provider_scorecard_updates_pass(tmp_path: Path):
    path = tmp_path / "provider_scorecard.yml"
    entry = update_provider_scorecard(path, "agentlab.mock_patch", "mock_executor", "PASS", _policy())
    assert entry.passes == 1
    assert entry.average_quality_score == 1.0


def test_provider_scorecard_updates_needs_revision(tmp_path: Path):
    path = tmp_path / "provider_scorecard.yml"
    entry = update_provider_scorecard(path, "agentlab.mock_patch", "mock_executor", "NEEDS_REVISION", _policy())
    assert entry.needs_revision == 1
    assert entry.average_quality_score == 0.35


def test_provider_scorecard_average_quality_score(tmp_path: Path):
    path = tmp_path / "provider_scorecard.yml"
    update_provider_scorecard(path, "agentlab.mock_patch", "mock_executor", "NEEDS_REVISION", _policy())
    entry = update_provider_scorecard(path, "agentlab.mock_patch", "mock_executor", "PASS", _policy())
    assert entry.average_quality_score == 0.675


def test_provider_scorecard_multiple_providers(tmp_path: Path):
    path = tmp_path / "provider_scorecard.yml"
    update_provider_scorecard(path, "agentlab.mock_patch", "mock_executor", "PASS", _policy())
    update_provider_scorecard(path, "manual.codex", "codex_cli", "FAIL", _policy())
    data = load_provider_scorecard(path)
    assert {item["provider_id"] for item in data["providers"]} == {"agentlab.mock_patch", "manual.codex"}
