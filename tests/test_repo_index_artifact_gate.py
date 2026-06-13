from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from artifact_contract import artifact_content_issues


def test_artifact_gate_detects_codegraph_claim_without_ledger(tmp_path: Path) -> None:
    issues = artifact_content_issues("06_implementation_report.md", "I queried CodeGraph and used code graph.", tmp_path)
    assert any("repo_index_ledger" in issue or "repo_semantic_library" in issue for issue in issues)

