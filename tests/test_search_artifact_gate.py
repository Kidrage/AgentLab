from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from artifact_contract import artifact_content_issues


def test_artifact_gate_detects_search_claim_without_ledger(tmp_path: Path) -> None:
    issues = artifact_content_issues("03_research_notes.md", "I searched web for pricing.", tmp_path)
    assert any("search_ledger.yml" in issue for issue in issues)

