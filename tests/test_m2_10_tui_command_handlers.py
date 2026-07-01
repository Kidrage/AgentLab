"""M2-10 TUI command handlers — updated for M3-3 wired behavior (was dry_run)."""

import pytest
from pathlib import Path

import yaml

from agentlab_tui.command_handlers import (
    handle_approve, handle_reject, handle_pause, handle_resume, handle_retry,
    handle_inspect_evidence, handle_open_artifact, handle_export_handoff,
)


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _make_project(root: Path, project: str = "TestProject") -> None:
    brain = root / "projects" / project / "project_brain"
    brain.mkdir(parents=True, exist_ok=True)
    _write_yaml(brain / "acceptance_history.yml", {"entries": []})
    _write_yaml(brain / "next_actions.yml", {"next_action": "prepare_task"})
    _write_yaml(brain / "project_fact_snapshot.yml", {"project": project, "event_count": 0})
    _write_yaml(root / "projects" / project / "project_artifact_index.yml", {"artifacts": []})
    (root / "projects" / project / "PROJECT_HANDOFF.md").write_text("# Test\n", encoding="utf-8")
    _write_yaml(root / "projects" / project / "runs" / "task_001" / "state.yml", {"status": "blocked"})


def test_handle_approve_requires_auth():
    res = handle_approve("card_1", actor=None, reason=None)
    assert res.status == "error"
    assert "Missing actor" in res.message


def test_handle_approve_wired(tmp_path: Path, monkeypatch):
    """M3-3: approve is now wired (was dry_run)."""
    _make_project(tmp_path)
    monkeypatch.setenv("AGENTLAB_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    res = handle_approve("card_1", actor="admin", reason="looks good", project="TestProject")
    assert res.status == "ok"
    assert res.requires_approval is True
    assert res.mutated_state is True


def test_handle_reject(tmp_path: Path, monkeypatch):
    """M3-3: reject is now wired (was dry_run)."""
    _make_project(tmp_path)
    monkeypatch.setenv("AGENTLAB_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    res = handle_reject("card_2", actor="admin", reason="flawed logic", project="TestProject")
    assert res.status == "ok"
    assert res.action == "reject"
    assert res.mutated_state is True


def test_handle_pause_resume(tmp_path: Path, monkeypatch):
    """M3-3: pause/resume wired."""
    _make_project(tmp_path)
    monkeypatch.setenv("AGENTLAB_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    res1 = handle_pause("TestProject", actor="admin", reason="budget")
    assert res1.status == "ok"
    res2 = handle_resume("TestProject", actor="admin", reason="approved")
    assert res2.status == "ok"


def test_handle_retry_wired(tmp_path: Path, monkeypatch):
    """M3-3: retry is now wired."""
    _make_project(tmp_path)
    monkeypatch.setenv("AGENTLAB_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    res = handle_retry("task_001", actor="admin", reason="evidence supplied", project="TestProject")
    assert res.status == "ok"
    assert res.mutated_state is True


def test_readonly_handlers():
    """M3-3: read-only inspect/open/export added."""
    res1 = handle_inspect_evidence("task_001")
    assert res1.status == "ok"
    assert res1.mutated_state is False

    res2 = handle_open_artifact("projects/X/artifact.yml")
    assert res2.status == "ok"
    assert res2.mutated_state is False

    res3 = handle_export_handoff("TestProject")
    assert res3.status == "ok"
    assert res3.mutated_state is False
