from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from ingestion.repo_indexers.base import RepoIndexDecision


def test_repo_index_decision_serializable() -> None:
    assert RepoIndexDecision("deny", ["no"]).as_dict()["action"] == "deny"

