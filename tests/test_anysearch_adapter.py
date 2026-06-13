from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from search.anysearch_adapter import AnySearchAdapter
from search.local_url_reader import LocalUrlReader


def test_missing_api_key_disabled_does_not_crash(monkeypatch) -> None:
    monkeypatch.delenv("ANYSEARCH_API_KEY", raising=False)
    response = AnySearchAdapter({"enabled": False}).search_web("hello")
    assert response.status == "skipped"
    assert response.usage["request_count"] == 0


def test_mock_search_has_source_and_retrieved_at() -> None:
    response = AnySearchAdapter({"enabled": False}, mock=True).search_web("hello")
    assert response.results[0].source
    assert response.results[0].retrieved_at


def test_batch_over_policy_pending_approval() -> None:
    config = {
        "enabled": True,
        "safety": {
            "require_approval_for_batch_over": 1,
        },
    }
    adapter = AnySearchAdapter(config, mock=True)

    response = adapter.batch_search(["one", "two"])

    assert response.status == "pending_approval"


def test_localhost_private_url_extract_blocked() -> None:
    response = LocalUrlReader().extract_url("http://127.0.0.1:8000")

    assert response.status == "rejected"
    assert "blocked" in response.warnings[0]
