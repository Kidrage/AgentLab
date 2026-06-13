from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from search.anysearch_adapter import AnySearchAdapter
from search.ledger import write_search_artifacts


def test_search_ledger_unknown_cost_is_not_zero(tmp_path: Path) -> None:
    response = AnySearchAdapter({}, mock=True).search_web("agentlab")
    write_search_artifacts(tmp_path, task_id="task_search", action="web_search", response=response)
    ledger = yaml.safe_load((tmp_path / "search_ledger.yml").read_text(encoding="utf-8"))
    assert ledger["entries"][0]["cost"]["estimated_cost_usd"] is None
    assert ledger["entries"][0]["cost"]["token_visibility"] == "unknown"
    assert (tmp_path / "search_results.json").exists()
    usage = yaml.safe_load((tmp_path / "skill_usage_ledger.yml").read_text(encoding="utf-8"))
    assert usage["entries"][0]["skill_id"] == "anysearch.web_research"

