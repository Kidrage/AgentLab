import pytest
from agentlab_tui.models import TUICommandResult, TUIWarning, TUIStateSnapshot

def test_tui_command_result_defaults():
    res = TUICommandResult(
        action="test",
        status="success",
        message="ok"
    )
    assert res.requires_approval is False
    assert res.mutated_state is False
    assert res.evidence_path is None
    assert len(res.warnings) == 0

def test_tui_state_snapshot_defaults():
    snap = TUIStateSnapshot(project_id="Demo")
    assert snap.view == "overview"
    assert len(snap.workers) == 0
    assert len(snap.tasks) == 0
    assert snap.project_id == "Demo"
