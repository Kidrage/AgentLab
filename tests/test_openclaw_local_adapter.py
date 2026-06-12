from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from openclaw_local_adapter import (
    build_agentlab_cli_command,
    build_openclaw_event_message,
    parse_openclaw_user_reply,
    write_local_event_queue_record,
)


def _payload() -> dict:
    return {
        "event": "ACTION_REQUIRED",
        "project": "AgentLab",
        "task_id": "task_0001",
        "summary": "Approval required",
        "reason": "Need approval before writing files.",
        "api_key": "secret-value",
        "decision_card": {
            "id": "decision_0001",
            "options": [
                {"id": "approve_write", "label": "Approve write", "risk": "low"},
                {"id": "reject", "label": "Reject", "risk": "low"},
                {"id": "stop_task", "label": "Stop task", "risk": "medium"},
            ],
        },
    }


def test_build_openclaw_event_message_action_required() -> None:
    message = build_openclaw_event_message(_payload())
    assert message["title"] == "AgentLab action required"
    assert message["task_id"] == "task_0001"
    assert message["event"] == "ACTION_REQUIRED"
    assert message["summary"] == "Approval required"
    assert message["decision_id"] == "decision_0001"


def test_decision_options_map_to_a_b_c() -> None:
    message = build_openclaw_event_message(_payload())
    assert [option["key"] for option in message["options"]] == ["A", "B", "C"]
    assert [option["option_id"] for option in message["options"]] == ["approve_write", "reject", "stop_task"]


def test_parse_a_returns_approve_decision() -> None:
    message = build_openclaw_event_message(_payload())
    action = parse_openclaw_user_reply("A", message)
    assert action == {
        "action": "approve_decision",
        "task_id": "task_0001",
        "decision_id": "decision_0001",
        "option_id": "approve_write",
    }


def test_parse_chinese_approve_returns_approve_decision() -> None:
    message = build_openclaw_event_message(_payload())
    action = parse_openclaw_user_reply("批准", message)
    assert action["action"] == "approve_decision"
    assert action["option_id"] == "approve_write"


def test_parse_b_returns_reject_decision() -> None:
    message = build_openclaw_event_message(_payload())
    action = parse_openclaw_user_reply("B", message)
    assert action["action"] == "reject_decision"
    assert action["option_id"] == "reject"


def test_build_agentlab_cli_command_does_not_execute() -> None:
    action = {
        "action": "approve_decision",
        "task_id": "task_0001",
        "decision_id": "decision_0001",
        "option_id": "approve_write",
    }
    assert build_agentlab_cli_command(action, "AgentLab") == [
        "./agentlab.sh",
        "decision-approve",
        "decision_0001",
        "--project",
        "AgentLab",
        "--task-id",
        "task_0001",
        "--option",
        "approve_write",
    ]


def test_write_local_event_queue_record_writes_json(tmp_path: Path) -> None:
    path = write_local_event_queue_record(_payload(), tmp_path)
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["transport"] == "local_event_queue"
    assert data["message"]["event"] == "ACTION_REQUIRED"


def test_event_queue_file_redacts_secrets(tmp_path: Path) -> None:
    path = write_local_event_queue_record(_payload(), tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "secret-value" not in text
    assert "REDACTED" in text


def test_unknown_reply_returns_clear_error() -> None:
    message = build_openclaw_event_message(_payload())
    action = parse_openclaw_user_reply("what now", message)
    assert action["action"] == "error"
    assert "Unknown OpenClaw reply" in action["error"]


def test_payload_without_decision_card_generates_notification() -> None:
    payload = {"event": "COMPLETED", "project": "AgentLab", "task_id": "task_0002", "summary": "Done"}
    message = build_openclaw_event_message(payload)
    assert message["notification"] is True
    assert message["options"] == []
    assert message["summary"] == "Done"
