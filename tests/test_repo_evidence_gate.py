from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from artifact_contract import _check_repo_analysis_evidence
from execution_log import append_command_record


def test_repo_analysis_claim_requires_manifest(tmp_path: Path) -> None:
    issues = _check_repo_analysis_evidence(
        "02_reposcout_report.md",
        "# RepoScout Report\n\nAnalyzed the repository and read README.md.\n",
        tmp_path,
    )

    assert any("repo_manifest.json is missing" in issue for issue in issues)


def test_file_read_claim_matches_manifest(tmp_path: Path) -> None:
    (tmp_path / "repo_manifest.json").write_text(
        json.dumps({"files_read": [{"path": "README.md", "bytes": 10}]}),
        encoding="utf-8",
    )

    issues = _check_repo_analysis_evidence(
        "02_reposcout_report.md",
        "# RepoScout Report\n\nRead README.md for project context.\n",
        tmp_path,
    )

    assert issues == []


def test_clone_claim_requires_resource_ledger(tmp_path: Path) -> None:
    issues = _check_repo_analysis_evidence(
        "02_reposcout_report.md",
        "# RepoScout Report\n\nCloned the repository for analysis.\n",
        tmp_path,
    )

    assert any("resource_ledger.yml is missing" in issue for issue in issues)


def test_build_claim_requires_execution_log(tmp_path: Path) -> None:
    issues = _check_repo_analysis_evidence(
        "07_validation_report.md",
        "# Validation Report\n\nRan tests with pytest.\n",
        tmp_path,
    )
    assert any("execution_log.yml" in issue for issue in issues)

    append_command_record(tmp_path, {"command": "pytest", "exit_code": 0, "stdout": "", "stderr": ""})
    issues = _check_repo_analysis_evidence(
        "07_validation_report.md",
        "# Validation Report\n\nRan tests with pytest.\n",
        tmp_path,
    )
    assert issues == []
