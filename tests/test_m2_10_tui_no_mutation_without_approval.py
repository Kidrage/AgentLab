"""M2-10 TUI no-mutation-without-approval — updated for M3-3 wired handlers."""

import pytest
from pathlib import Path

import yaml

from agentlab_tui.command_handlers import handle_approve, handle_retry


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _make_project(root: Path) -> None:
    brain = root / "projects" / "TestProject" / "project_brain"
    brain.mkdir(parents=True, exist_ok=True)
    _write_yaml(brain / "acceptance_history.yml", {"entries": []})
    _write_yaml(brain / "next_actions.yml", {"next_action": "prepare_task"})
    _write_yaml(brain / "project_fact_snapshot.yml", {"project": "TestProject", "event_count": 0})
    _write_yaml(root / "projects" / "TestProject" / "project_artifact_index.yml", {"artifacts": []})
    (root / "projects" / "TestProject" / "PROJECT_HANDOFF.md").write_text("# Test\n", encoding="utf-8")
    _write_yaml(root / "projects" / "TestProject" / "runs" / "task_1" / "state.yml", {"status": "blocked"})


def test_no_mutation_without_approval(tmp_path: Path, monkeypatch):
    """
    M3-3: Command handlers enforce approval (actor+reason) and pass through
    the Operator Action contract. Mutations are now wired, not dry_run.
    """
    # With actor+reason, approve should succeed through the contract
    _make_project(tmp_path)
    monkeypatch.setenv("AGENTLAB_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    res = handle_approve("card_1", actor="admin", reason="looks good", project="TestProject")

    # Must enforce approval flag
    assert res.requires_approval is True

    # M3-3: mutations now go through operator action contract — mutated_state=True
    assert res.mutated_state is True
    assert res.status == "ok"

    # Without actor+reason, mutation must be blocked
    res_blocked = handle_approve("card_1", actor=None, reason=None)
    assert res_blocked.status == "error"
    assert res_blocked.mutated_state is False
    assert "Missing actor" in res_blocked.message


def test_retry_requires_approval(tmp_path: Path, monkeypatch):
    """
    M3-3: Retry enforces approval. With valid actor+reason, mutation proceeds.
    Without auth, it's blocked.
    """
    _make_project(tmp_path)
    monkeypatch.setenv("AGENTLAB_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    res = handle_retry("task_1", actor="admin", reason="stuck", project="TestProject")
    assert res.requires_approval is True
    assert res.mutated_state is True
    assert res.status == "ok"

    # blocked without auth
    res_blocked = handle_retry("task_1", actor=None, reason=None)
    assert res_blocked.status == "error"
    assert res_blocked.mutated_state is False
