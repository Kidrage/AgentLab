from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from artifact_contract import _check_repo_analysis_evidence


def test_final_report_repo_claim_requires_manifest(tmp_path: Path) -> None:
    issues = _check_repo_analysis_evidence("verification_report.md", "Analyzed repository.", tmp_path)
    assert any("repo_manifest.json is missing" in issue for issue in issues)


def test_final_report_file_claim_requires_manifest_file(tmp_path: Path) -> None:
    (tmp_path / "repo_manifest.json").write_text(json.dumps({"files_read": [{"path": "README.md"}]}), encoding="utf-8")
    issues = _check_repo_analysis_evidence("verification_report.md", "Read CMakeLists.txt.", tmp_path)
    assert any("CMakeLists.txt" in issue for issue in issues)


def test_final_report_command_claim_requires_execution_log(tmp_path: Path) -> None:
    issues = _check_repo_analysis_evidence("verification_report.md", "Executed command pytest.", tmp_path)
    assert any("execution_log.yml" in issue for issue in issues)


def test_api_only_repo_report_does_not_require_execution_log(tmp_path: Path) -> None:
    (tmp_path / "repo_manifest.json").write_text(json.dumps({"files_read": [{"path": "README.md"}]}), encoding="utf-8")
    issues = _check_repo_analysis_evidence("verification_report.md", "Based on API manifest, read README.md.", tmp_path)
    assert issues == []


def test_report_without_repo_claim_not_affected(tmp_path: Path) -> None:
    assert _check_repo_analysis_evidence("verification_report.md", "Plain status update.", tmp_path) == []