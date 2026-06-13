from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from search.provider import SearchResponse, SearchResult


def test_provider_output_serializes_to_json_yaml() -> None:
    response = SearchResponse(
        provider="mock",
        query="agentlab",
        results=[SearchResult(title="AgentLab", url="https://example.com", snippet="ok", source="mock")],
    )
    data = response.as_dict()
    assert json.loads(json.dumps(data))["results"][0]["source"] == "mock"
    assert yaml.safe_load(yaml.safe_dump(data))["usage"]["token_visibility"] == "unknown"

