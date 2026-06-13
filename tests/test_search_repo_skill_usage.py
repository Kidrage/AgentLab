from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from search.anysearch_adapter import AnySearchAdapter
from search.ledger import write_search_artifacts


def test_repeated_search_success_proposes_candidate(tmp_path: Path) -> None:
    response = AnySearchAdapter({}, mock=True).search_web("agentlab")
    write_search_artifacts(tmp_path, task_id="task_skill", action="web_search", response=response)
    write_search_artifacts(tmp_path, task_id="task_skill", action="web_search", response=response)
    usage = yaml.safe_load((tmp_path / "skill_usage_ledger.yml").read_text(encoding="utf-8"))
    assert usage["candidates"][0]["source_code_copied"] is False
    assert usage["candidates"][0]["license_review_required"] is True

