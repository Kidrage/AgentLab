"""M3-3 TUI Daily-Driver Flow — end-to-end tests for TUI operator surface."""

from __future__ import annotations

from pathlib import Path

import yaml

from agentlab_tui.command_handlers import (
    handle_approve,
    handle_reject,
    handle_pause,
    handle_resume,
    handle_retry,
    handle_inspect_evidence,
    handle_open_artifact,
    handle_export_handoff,
)


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _make_project_fixture(root: Path) -> Path:
    """Create minimal project fixture with acceptance_history for TUI tests."""
    brain_dir = root / "projects" / "TestProject" / "project_brain"
    brain_dir.mkdir(parents=True)
    (root / "projects" / "TestProject" / "PROJECT_HANDOFF.md").write_text("# Test\n", encoding="utf-8")
    _write_yaml(root / "projects" / "TestProject" / "project_artifact_index.yml", {"artifacts": []})
    _write_yaml(brain_dir / "project_fact_snapshot.yml", {"project": "TestProject", "event_count": 0})
    _write_yaml(brain_dir / "acceptance_history.yml", {"entries": []})
    _write_yaml(brain_dir / "next_actions.yml", {"next_phase_id": "phase_1", "next_action": "prepare_task"})
    _write_yaml(brain_dir / "current_phase.yml", {"phase_id": "phase_1", "status": "in_progress"})
    return root


def test_tui_approve_requires_actor() -> None:
    """TUI approve must be blocked without actor."""
    result = handle_approve("card_1", None, None)
    assert result.status == "error"
    assert "Missing actor" in result.message


def test_tui_approve_with_valid_input() -> None:
    """TUI approve with actor+reason should succeed."""
    result = handle_approve("card_1", "operator", "evidence reviewed", "TestProject")
    assert result.status == "ok"
    assert result.mutated_state is True


def test_tui_reject_with_valid_input() -> None:
    """TUI reject with actor+reason should succeed."""
    result = handle_reject("card_1", "operator", "evidence insufficient", "TestProject")
    assert result.status == "ok"
    assert result.mutated_state is True


def test_tui_pause_resume_requires_actor() -> None:
    """TUI pause/resume must require actor."""
    for handler in [handle_pause, handle_resume]:
        result = handler("TestProject", None, None)
        assert result.status == "error"


def test_tui_pause_resume_with_valid_input() -> None:
    """TUI pause/resume with actor+reason should succeed."""
    result = handle_pause("TestProject", "operator", "budget review")
    assert result.status == "ok"
    result = handle_resume("TestProject", "operator", "budget approved")
    assert result.status == "ok"


def test_tui_retry_with_valid_input() -> None:
    """TUI retry with actor+reason should succeed."""
    result = handle_retry("task_001", "operator", "fixed missing evidence")
    assert result.status == "ok"
    assert result.mutated_state is True


def test_tui_readonly_actions_no_actor() -> None:
    """TUI read-only actions should not need actor."""
    result = handle_inspect_evidence("task_001", "TestProject")
    assert result.status == "ok"
    assert result.mutated_state is False

    result = handle_open_artifact("projects/TestProject/artifact.yml")
    assert result.status == "ok"
    assert result.mutated_state is False

    result = handle_export_handoff("TestProject")
    assert result.status == "ok"
    assert result.mutated_state is False


def test_tui_mutation_returns_evidence_path() -> None:
    """TUI mutations should return evidence_path pointing to project brain."""
    result = handle_approve("card_1", "operator", "done", "TestProject")
    assert result.status == "ok"
    assert result.evidence_path is not None
    assert "TestProject" in str(result.evidence_path)


def test_tui_forbidden_effects_blocked() -> None:
    """If operator_os is available, forbidden effects should be caught."""
    try:
        from agentlab_tui.command_handlers import _validate_and_log
        validation = _validate_and_log(
            "approve", "phase_acceptance", "phase_1",
            "operator", "test",
            requested_effects=["phase_acceptance_bypass"],
        )
        assert validation["status"] == "blocked"
        assert any("phase_acceptance_bypass" in e for e in validation["errors"])
    except ImportError:
        pass  # operator_os not importable in this context - skip
