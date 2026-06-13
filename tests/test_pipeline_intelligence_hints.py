from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from intelligence_plans import maybe_write_intelligence_plans


def test_pipeline_hint_writes_search_and_repo_plans(tmp_path: Path) -> None:
    written = maybe_write_intelligence_plans(
        tmp_path,
        task_id="task_hint",
        task_text="latest docs pricing for repo architecture patch",
        route_key="repo_patch",
    )
    assert tmp_path / "search_plan.yml" in written
    assert tmp_path / "repo_index_plan.yml" in written
    usage = yaml.safe_load((tmp_path / "skill_usage_ledger.yml").read_text(encoding="utf-8"))
    skill_ids = {entry["skill_id"] for entry in usage["entries"]}
    assert {"anysearch.web_research", "codegraph.repo_index"} <= skill_ids

