"""Tests for WorkerCard schema and categories."""

from agent_runtime.workers.worker_card import WorkerCard, WorkerCategory

def test_worker_card_defaults():
    card = WorkerCard(
        worker_id="test_worker",
        display_name="Test Worker",
        command="test"
    )
    assert card.worker_id == "test_worker"
    assert card.display_name == "Test Worker"
    assert card.command == "test"
    assert card.installed is False
    assert card.category == WorkerCategory.UNKNOWN
    assert card.can_read_files is True
    assert card.can_edit_files is True
    assert card.can_run_shell is True

def test_worker_card_to_and_from_dict():
    data = {
        "worker_id": "claude_code",
        "display_name": "Claude Code",
        "command": "claude",
        "installed": True,
        "version": "1.2.3",
        "authenticated": "yes",
        "category": WorkerCategory.CODING_AGENT,
        "source": "local_cli",
        "can_read_files": True,
        "can_edit_files": True,
        "can_run_shell": True,
        "can_access_network": "yes",
        "can_upload_files": "no",
        "interactive": True,
        "supports_noninteractive_task": "yes",
        "supports_mcp": "yes",
        "supports_long_context": "yes",
        "cost_tier": "high",
        "risk_level": "high",
        "default_enabled": False,
        "approval_required": True,
        "best_for": ["refactoring"],
        "avoid_for": ["search"],
        "notes": ["test note"]
    }
    
    card = WorkerCard.from_dict(data)
    assert card.worker_id == "claude_code"
    assert card.version == "1.2.3"
    assert card.authenticated == "yes"
    assert card.category == WorkerCategory.CODING_AGENT
    
    dumped = card.to_dict()
    assert dumped["worker_id"] == "claude_code"
    assert dumped["best_for"] == ["refactoring"]
