from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import yaml

from agent_runtime.frontdesk_evidence import (
    build_grounded_task_report,
    search_tracked_evidence,
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def test_search_uses_literal_tracked_text_and_returns_line_hash(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    source = root / "agent_runtime" / "alpha.py"
    source.parent.mkdir(parents=True)
    source.write_text("first line\nNeedleValue = 42\n", encoding="utf-8")
    (root / "untracked.txt").write_text("NeedleValue secret\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "agent_runtime/alpha.py")

    result = search_tracked_evidence(root, "NeedleValue")

    assert result["schema_version"] == "frontdesk-evidence-search/v1"
    assert result["search_mode"] == "literal_tracked_text"
    assert result["match_count"] == 1
    assert result["truncated"] is False
    assert result["matches"] == [
        {
            "path": "agent_runtime/alpha.py",
            "line": 2,
            "excerpt": "NeedleValue = 42",
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }
    ]
    assert "untracked.txt" not in str(result)


def test_search_rejects_empty_or_path_traversal_scope(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")

    for query, scopes in (("", ()), ("needle", ("../outside",))):
        try:
            search_tracked_evidence(root, query, paths=scopes)
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError("unsafe search input was accepted")


def test_grounded_report_never_promotes_missing_verification(tmp_path: Path) -> None:
    root = tmp_path / "agentlab"
    run_dir = root / "projects" / "Demo" / "runs" / "task_1"
    run_dir.mkdir(parents=True)
    (run_dir / "state.yml").write_text(
        yaml.safe_dump({"status": "completed", "current_agent": None}),
        encoding="utf-8",
    )

    report = build_grounded_task_report(root, "Demo", "task_1")

    assert report["schema_version"] == "frontdesk-grounded-report/v1"
    assert report["task_status"]["value"] == "completed"
    assert report["task_status"]["source"] == "projects/Demo/runs/task_1/state.yml"
    assert report["verification_status"] == "unknown"
    assert report["reportable_as_verified"] is False
    assert report["unknowns"] == ["No canonical verification artifact was found."]


def test_grounded_report_cites_passing_verification_artifact(tmp_path: Path) -> None:
    root = tmp_path / "agentlab"
    run_dir = root / "projects" / "Demo" / "runs" / "task_2"
    run_dir.mkdir(parents=True)
    (run_dir / "state.yml").write_text("status: completed\n", encoding="utf-8")
    verification = run_dir / "verification_report.yml"
    verification.write_text("status: PASS\nchecks_passed: 3\n", encoding="utf-8")

    report = build_grounded_task_report(root, "Demo", "task_2")

    assert report["verification_status"] == "pass"
    assert report["reportable_as_verified"] is True
    assert report["verification_evidence"][0]["path"].endswith(
        "verification_report.yml"
    )
    assert len(report["verification_evidence"][0]["sha256"]) == 64
