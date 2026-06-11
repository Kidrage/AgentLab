from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from feedback_manager import create_decision_card, load_pending_decision_cards
from mcp_server import call_tool, list_tools
from skill_evolution import load_skill_requests


EXPECTED_TOOLS = {
    "agentlab_create_task",
    "agentlab_get_task_status",
    "agentlab_get_task_events",
    "agentlab_get_task_report",
    "agentlab_list_decisions",
    "agentlab_approve_decision",
    "agentlab_reject_decision",
    "agentlab_resume_task",
    "agentlab_pause_task",
    "agentlab_stop_task",
    "agentlab_list_skill_requests",
    "agentlab_request_skill_learning",
    "agentlab_approve_skill_request",
    "agentlab_reject_skill_request",
    "agentlab_list_active_skills",
    "agentlab_get_skill_usage",
    "agentlab_webhook_status",
    "agentlab_watchdog_scan",
}


def _setup_root(root: Path) -> Path:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "mcp_policy.yml").write_text(
        yaml.safe_dump({
            "enabled": False,
            "allow_task_creation": True,
            "allow_decision_approval": True,
            "allow_skill_approval": True,
            "allow_stop_task": True,
        }),
        encoding="utf-8",
    )
    run_dir = root / "projects" / "Demo" / "runs" / "task_0001"
    run_dir.mkdir(parents=True)
    (run_dir / "state.yml").write_text(yaml.safe_dump({"status": "paused", "last_event": "Waiting."}), encoding="utf-8")
    (run_dir / "progress.yml").write_text(yaml.safe_dump({"status": "paused", "current_stage": "blocked"}), encoding="utf-8")
    (run_dir / "07_validation_report.md").write_text("# Validation\n\nPass.\n", encoding="utf-8")
    return run_dir


def test_tool_list_contains_expected_tools() -> None:
    names = {tool["name"] for tool in list_tools()}
    assert EXPECTED_TOOLS.issubset(names)


def test_each_tool_schema_includes_required_args() -> None:
    tools = {tool["name"]: tool for tool in list_tools()}
    assert tools["agentlab_get_task_status"]["inputSchema"]["required"] == ["project", "task_id"]
    assert "decision_id" in tools["agentlab_approve_decision"]["inputSchema"]["required"]
    assert "request_id" in tools["agentlab_approve_skill_request"]["inputSchema"]["required"]


def test_tool_handlers_return_structured_json(tmp_path: Path) -> None:
    _setup_root(tmp_path)
    result = call_tool(
        "agentlab_get_task_status",
        {"project": "Demo", "task_id": "task_0001"},
        agentlab_root=tmp_path,
    )
    assert result["project"] == "Demo"
    assert result["task_id"] == "task_0001"
    assert result["status"] == "paused"
    assert "pending_decisions" in result


def test_missing_mcp_dependency_does_not_break_tool_contract() -> None:
    assert list_tools()


def test_decision_approval_tool_updates_decision_card(tmp_path: Path) -> None:
    run_dir = _setup_root(tmp_path)
    card, _path = create_decision_card(
        run_dir,
        task_id="task_0001",
        card_type="user_decision",
        title="Approval",
        reason="Need approval.",
        options=[{"id": "approve_resume", "label": "Approve resume", "risk": "low"}],
    )
    result = call_tool(
        "agentlab_approve_decision",
        {"project": "Demo", "task_id": "task_0001", "decision_id": card["id"], "option": "approve_resume"},
        agentlab_root=tmp_path,
    )
    assert result["ok"] is True
    assert result["next_recommended_action"] == "agentlab_resume_task"
    assert load_pending_decision_cards(run_dir) == []


def test_skill_request_tool_creates_request_through_lifecycle(tmp_path: Path) -> None:
    _setup_root(tmp_path)
    result = call_tool(
        "agentlab_request_skill_learning",
        {
            "project": "Demo",
            "skill_name": "Demo skill",
            "source": "manual://demo",
            "purpose": "Create a reusable repair skill.",
        },
        agentlab_root=tmp_path,
    )
    assert result["ok"] is True
    requests = load_skill_requests(tmp_path, "Demo")
    assert len(requests) == 1
    assert requests[0]["id"] == result["request_id"]
