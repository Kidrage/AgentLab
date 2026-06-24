import pytest
from agentlab_tui.command_handlers import (
    handle_approve, handle_reject, handle_pause, handle_resume,
    handle_retry, handle_rollback, handle_enable_worker, handle_disable_worker
)

def test_handle_approve_requires_auth():
    res = handle_approve("card_1", actor=None, reason=None)
    assert res.status == "error"
    assert "Missing actor" in res.message

def test_handle_approve_dry_run():
    res = handle_approve("card_1", actor="admin", reason="looks good")
    assert res.status == "dry_run"
    assert res.requires_approval is True
    assert res.mutated_state is False

def test_handle_reject():
    res = handle_reject("card_2", actor="admin", reason="flawed logic")
    assert res.status == "dry_run"
    assert res.action == "reject"

def test_handle_worker_toggle():
    res1 = handle_enable_worker("claude", actor="admin", reason="enabled")
    assert res1.action == "enable_worker"
    assert res1.status == "dry_run"
    
    res2 = handle_disable_worker("claude", actor="admin", reason="disabled")
    assert res2.action == "disable_worker"
    assert res2.status == "dry_run"
