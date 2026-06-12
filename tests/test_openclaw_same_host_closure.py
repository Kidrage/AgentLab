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


def test_same_host_openclaw_closure_mock(tmp_path: Path) -> None:
    payload = {
        "event": "ACTION_REQUIRED",
        "project": "AgentLab",
        "task_id": "task_0001",
        "summary": "Need approval",
        "decision_card": {
            "id": "decision_0001",
            "options": [
                {"id": "approve_write", "label": "Approve write"},
                {"id": "reject", "label": "Reject"},
                {"id": "stop_task", "label": "Stop task"},
            ],
        },
    }

    message = build_openclaw_event_message(payload)
    action = parse_openclaw_user_reply("A", message)
    approve_cmd = build_agentlab_cli_command(action, "AgentLab")
    resume_cmd = build_agentlab_cli_command({"action": "resume_task", "task_id": "task_0001"}, "AgentLab")
    queue_path = write_local_event_queue_record(payload, tmp_path / "agentlab_events")

    assert approve_cmd == [
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
    assert resume_cmd == ["./agentlab.sh", "decision-resume", "task_0001", "--project", "AgentLab"]
    assert queue_path.exists()
    record = json.loads(queue_path.read_text(encoding="utf-8"))
    assert record["message"]["options"][0]["key"] == "A"
