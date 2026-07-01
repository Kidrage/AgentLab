"""M2-10 TUI command handlers — updated for M3-3 wired behavior (was dry_run)."""

import pytest
from agentlab_tui.command_handlers import (
    handle_approve, handle_reject, handle_pause, handle_resume, handle_retry,
    handle_inspect_evidence, handle_open_artifact, handle_export_handoff,
)


def test_handle_approve_requires_auth():
    res = handle_approve("card_1", actor=None, reason=None)
    assert res.status == "error"
    assert "Missing actor" in res.message


def test_handle_approve_wired():
    """M3-3: approve is now wired (was dry_run)."""
    res = handle_approve("card_1", actor="admin", reason="looks good")
    assert res.status == "ok"
    assert res.requires_approval is True
    assert res.mutated_state is True


def test_handle_reject():
    """M3-3: reject is now wired (was dry_run)."""
    res = handle_reject("card_2", actor="admin", reason="flawed logic")
    assert res.status == "ok"
    assert res.action == "reject"
    assert res.mutated_state is True


def test_handle_pause_resume():
    """M3-3: pause/resume wired."""
    res1 = handle_pause("TestProject", actor="admin", reason="budget")
    assert res1.status == "ok"
    res2 = handle_resume("TestProject", actor="admin", reason="approved")
    assert res2.status == "ok"


def test_handle_retry_wired():
    """M3-3: retry is now wired."""
    res = handle_retry("task_001", actor="admin", reason="evidence supplied")
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
