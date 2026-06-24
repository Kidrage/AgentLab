import pytest
from agentlab_tui.command_handlers import handle_approve, handle_retry

def test_no_mutation_without_approval():
    """
    Test that command handlers explicitly enforce approval and
    never silently mutate state in the skeleton.
    """
    res = handle_approve("card_1", actor="admin", reason="looks good")
    
    # Must enforce approval flag
    assert res.requires_approval is True
    
    # Must explicitly declare no state was mutated
    assert res.mutated_state is False
    
    # Must include a warning that real ledger integration is missing
    assert len(res.warnings) > 0
    assert any("Real ledger integration unavailable" in w.message for w in res.warnings)

def test_retry_requires_approval():
    """
    Test that potentially destructive operations like retry
    also enforce approval policies.
    """
    res = handle_retry("task_1", actor="admin", reason="stuck")
    assert res.requires_approval is True
    assert res.mutated_state is False
