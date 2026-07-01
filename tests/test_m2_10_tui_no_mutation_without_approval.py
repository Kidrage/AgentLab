"""M2-10 TUI no-mutation-without-approval — updated for M3-3 wired handlers."""

import pytest
from agentlab_tui.command_handlers import handle_approve, handle_retry


def test_no_mutation_without_approval():
    """
    M3-3: Command handlers enforce approval (actor+reason) and pass through
    the Operator Action contract. Mutations are now wired, not dry_run.
    """
    # With actor+reason, approve should succeed through the contract
    res = handle_approve("card_1", actor="admin", reason="looks good")

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


def test_retry_requires_approval():
    """
    M3-3: Retry enforces approval. With valid actor+reason, mutation proceeds.
    Without auth, it's blocked.
    """
    res = handle_retry("task_1", actor="admin", reason="stuck")
    assert res.requires_approval is True
    assert res.mutated_state is True
    assert res.status == "ok"

    # blocked without auth
    res_blocked = handle_retry("task_1", actor=None, reason=None)
    assert res_blocked.status == "error"
    assert res_blocked.mutated_state is False
