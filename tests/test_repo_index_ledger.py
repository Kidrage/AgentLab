from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from ingestion.repo_indexers.codegraph_adapter import CodeGraphAdapter
from ingestion.repo_indexers.ledger import write_repo_index_artifacts


def test_repo_index_ledger_writes_status_and_semantic_library(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    result = CodeGraphAdapter({"enabled": False}).index_repo(repo, dry_run=True)
    write_repo_index_artifacts(tmp_path / "out", task_id="task_repo", repo_path=repo, result=result)
    ledger = yaml.safe_load((tmp_path / "out" / "repo_index_ledger.yml").read_text(encoding="utf-8"))
    assert ledger["cost"]["api_cost_usd"] is None
    assert (tmp_path / "out" / "repo_semantic_library.json").exists()
    usage = yaml.safe_load((tmp_path / "out" / "skill_usage_ledger.yml").read_text(encoding="utf-8"))
    assert usage["entries"][0]["skill_id"] == "codegraph.repo_index"

