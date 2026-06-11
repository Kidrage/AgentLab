"""P1 Fix 7: Test chat adapter mock proving webhook + MCP bidirectional closure."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))


def _setup_chat_closure_env(tmp_path: Path) -> tuple[Path, str, str, dict]:
    """Create a task with a decision card, simulate webhook payload."""
    agentlab_root = tmp_path
    project = "ChatTest"
    task_id = "task_chat"

    # Config
    config = agentlab_root / "config"
    config.mkdir(parents=True)
    (config / "webhook_policy.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "enabled": False, "endpoints": []}), encoding="utf-8"
    )
    (config / "feedback_policy.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "notification_levels": {}, "watchdog_thresholds": {}}),
        encoding="utf-8",
    )

    # Create task run
    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    run_dir.mkdir(parents=True)
    (run_dir / "state.yml").write_text(yaml.safe_dump({"status": "blocked"}), encoding="utf-8")
    (run_dir / "progress.yml").write_text(yaml.safe_dump({"status": "blocked"}), encoding="utf-8")
    (run_dir / "user_request.md").write_text("Deploy to production", encoding="utf-8")
    (run_dir / "task_events.jsonl").write_text("", encoding="utf-8")

    # Create a decision card via feedback_manager
    from feedback_manager import create_decision_card

    card, _path = create_decision_card(
        run_dir,
        task_id=task_id,
        card_type="stale_running",
        title="Chat closure test",
        reason="Test webhook→chat→MCP closure",
        options=[
            {"id": "approve_write", "label": "Approve write", "risk": "low"},
            {"id": "approve_resume", "label": "Approve resume", "risk": "low"},
            {"id": "continue_waiting", "label": "Continue waiting", "risk": "low"},
            {"id": "stop_task", "label": "Stop task", "risk": "medium"},
        ],
        recommended_action="approve_resume",
        risk="low",
    )

    # Build webhook payload similar to what dispatch_event would send
    webhook_payload = {
        "event": "ACTION_REQUIRED",
        "project": project,
        "task_id": task_id,
        "stage": "blocked",
        "severity": "ACTION_REQUIRED",
        "summary": "Chat closure test",
        "reason": card.get("reason", ""),
        "decision_card": {
            "id": card.get("id"),
            "options": card.get("options", []),
        },
        "created_at": "2026-06-11T00:00:00Z",
    }

    return agentlab_root, project, task_id, webhook_payload


def test_receive_webhook_payload_parses_options(tmp_path: Path) -> None:
    """Chat adapter mock should parse webhook payload into chat message with option letters."""
    from chat_adapter_mock import receive_webhook_payload

    _, _, _, webhook_payload = _setup_chat_closure_env(tmp_path)
    result = receive_webhook_payload(webhook_payload)

    assert result["event"] == "ACTION_REQUIRED"
    assert "message" in result
    assert "A" in result.get("option_map", {})
    assert "[A]" in result["message"]
    assert len(result["options"]) == 4


def test_simulate_user_reply_maps_a_to_first_option(tmp_path: Path) -> None:
    """Simulating user reply with 'A' should map to first option id."""
    from chat_adapter_mock import receive_webhook_payload, simulate_user_reply

    _, _, _, webhook_payload = _setup_chat_closure_env(tmp_path)
    parsed = receive_webhook_payload(webhook_payload)
    option_id = simulate_user_reply(parsed, choice="A")
    assert option_id == "approve_write"


def test_simulate_user_reply_maps_b_to_second_option(tmp_path: Path) -> None:
    """Simulating user reply with 'B' should map to second option id."""
    from chat_adapter_mock import receive_webhook_payload, simulate_user_reply

    _, _, _, webhook_payload = _setup_chat_closure_env(tmp_path)
    parsed = receive_webhook_payload(webhook_payload)
    option_id = simulate_user_reply(parsed, choice="B")
    assert option_id == "approve_resume"


def test_full_chat_closure_apis(tmp_path: Path) -> None:
    """Full mock closure: webhook → chat → MCP approve → verify approved."""
    from chat_adapter_mock import mock_full_chat_closure

    agentlab_root, project, task_id, webhook_payload = _setup_chat_closure_env(tmp_path)

    result = mock_full_chat_closure(
        agentlab_root,
        project=project,
        task_id=task_id,
        webhook_payload=webhook_payload,
        user_choice="B",  # approve_resume
    )

    assert result["ok"], f"Full closure failed: {result.get('error', result)}"
    assert result["resolved_option"] == "approve_resume"
    assert "decision_approved" in result["steps"]

    # Verify the decision card is actually resolved
    from feedback_manager import load_decision_card
    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    decision_id = webhook_payload["decision_card"]["id"]
    card, _path = load_decision_card(run_dir, decision_id)
    assert card is not None
    assert card.get("status") == "approved"
    assert card.get("selected_option") == "approve_resume"
    assert card.get("resolved_by") == "chat_adapter_mock"


def test_user_decision_recorded_after_closure(tmp_path: Path) -> None:
    """After full closure, USER_DECISION_RECORDED event should exist."""
    from chat_adapter_mock import mock_full_chat_closure

    agentlab_root, project, task_id, webhook_payload = _setup_chat_closure_env(tmp_path)

    mock_full_chat_closure(
        agentlab_root,
        project=project,
        task_id=task_id,
        webhook_payload=webhook_payload,
        user_choice="A",
    )

    # Check task_events for USER_DECISION_RECORDED
    import json
    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    events_path = run_dir / "task_events.jsonl"
    assert events_path.exists()
    lines = events_path.read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line) for line in lines if line.strip()]
    decision_events = [e for e in events if e.get("event") == "USER_DECISION_RECORDED"]
    assert len(decision_events) > 0, f"No USER_DECISION_RECORDED event found in {events}"