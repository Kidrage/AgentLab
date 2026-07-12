from __future__ import annotations

import shutil
from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.approvals.approval_ledger import ApprovalLedger, write_approval_ledger
from agent_runtime.approvals.decision_card import DecisionCard
from agent_runtime.observability.event import Event
from agent_runtime.observability.event_log import EventLogger
from agent_runtime.observability.query import query_timeline, tail_event_log
from agent_runtime.observability.timeline import Timeline
from agent_runtime.run_task import app


runner = CliRunner()


def test_event_logger_writes_jsonl_and_typed_yaml(tmp_path) -> None:
    logger = EventLogger(str(tmp_path))
    logger.log_event(
        Event(
            event_id="e1",
            event_type="cost_recorded",
            timestamp="2024-01-01T12:00:00Z",
            project_id="p1",
            details={"amount": 0.5},
            cost_usd=0.5,
        )
    )

    observability = tmp_path / "observability"
    assert (observability / "event_log.jsonl").exists()
    assert (observability / "cost_events.yml").exists()


def test_route_event_is_written_to_route_yaml(tmp_path) -> None:
    timeline = Timeline("p1", str(tmp_path))
    timeline.add_event("route_decision_created", {"target": "coder_agent"})

    route_file = tmp_path / "observability" / "route_events.yml"
    assert route_file.exists()
    data = list(yaml.safe_load_all(route_file.read_text(encoding="utf-8")))
    assert len(data) == 1
    assert data[0]["event_type"] == "route_decision_created"


def test_timeline_query_and_tail(tmp_path) -> None:
    timeline = Timeline("p1", str(tmp_path))
    timeline.add_event("role_assigned", {"role": "coder"}, worker_id="w1")
    timeline.add_event("artifact_created", {"file": "main.py"})

    events = query_timeline(str(tmp_path))
    assert len(events) == 2
    assert events[0].event_type == "role_assigned"
    filtered = query_timeline(str(tmp_path), event_type="artifact_created")
    assert len(filtered) == 1
    assert filtered[0].event_type == "artifact_created"
    assert len(tail_event_log(str(tmp_path))) == 2


def test_pipeline_commands_emit_governed_timeline_events(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_runtime.run_task._PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("AGENTLAB_ROOT", str(tmp_path))
    (tmp_path / "agentlab.sh").touch()
    (tmp_path / "agent_runtime").mkdir()
    monkeypatch.setattr(
        "agent_runtime.routing.role_assignment.DEFAULT_CANDIDATES",
        [
            {
                "worker_id": "mock_worker",
                "display_name": "Mock",
                "installed": True,
                "category": "General",
                "cost_tier": "free",
                "command": "echo",
                "authenticated": "yes",
            }
        ],
    )

    task_packet = tmp_path / "task.yml"
    task_packet.write_text(
        "project_id: AgentLab\ntask_id: task_0001\nmodel: gpt-4\nrole: coder",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["cost-estimate", "--task-packet", str(task_packet)])
    assert result.exit_code == 0
    assert query_timeline(str(tmp_path), event_type="cost_estimated")

    shutil.copytree(Path("config").resolve(), tmp_path / "config", dirs_exist_ok=True)
    result = runner.invoke(app, ["route-task", "--task-packet", str(task_packet)])
    assert result.exit_code == 0, result.output
    assert query_timeline(str(tmp_path), event_type="route_decision_created")

    result = runner.invoke(
        app,
        ["assign-role", "--role", "coder", "--project", "test_proj"],
    )
    assert result.exit_code == 0, result.output
    assert query_timeline(str(tmp_path), event_type="role_assigned")

    ledger_path = tmp_path / "memory" / "test_proj" / "approval_ledger.yml"
    ledger = ApprovalLedger("test_proj")
    docs_dir = tmp_path / "projects" / "test_proj" / "tasks" / "task_0001" / "raw"
    docs_dir.mkdir(parents=True)
    (docs_dir / "user_request.md").write_text(
        "Hello world\nThis is a real request.",
        encoding="utf-8",
    )
    card_values = {
        "decision_type": "test",
        "status": "pending",
        "reason": "test",
        "risk_level": "low",
        "requested_by": "u1",
        "task_id": "task_0001",
        "project": "test_proj",
        "phase_id": "p1",
        "capabilities": [],
        "estimated_cost_usd": 0,
        "evidence_artifacts": [],
        "created_at": "now",
        "updated_at": "now",
        "expires_at": "now",
    }
    ledger.approvals = [
        DecisionCard(decision_id="d1", **card_values),
        DecisionCard(decision_id="d2", **card_values),
    ]
    write_approval_ledger(ledger, ledger_path)

    result = runner.invoke(
        app,
        [
            "approve",
            "--decision-id",
            "d1",
            "--actor",
            "user",
            "--reason",
            "ok",
            "--project",
            "test_proj",
        ],
    )
    assert result.exit_code == 0, result.output
    assert query_timeline(str(tmp_path), event_type="approval_accepted")

    result = runner.invoke(
        app,
        [
            "reject",
            "--decision-id",
            "d2",
            "--actor",
            "user",
            "--reason",
            "no",
            "--project",
            "test_proj",
        ],
    )
    assert result.exit_code == 0, result.output
    assert query_timeline(str(tmp_path), event_type="approval_rejected")

    monkeypatch.setattr(
        "pipeline_runner.validate_artifacts",
        lambda run_dir: {
            "valid": True,
            "pass_rate": 1.0,
            "artifacts_checked": 1,
            "artifacts_passed": 1,
            "issues": [],
            "snapshot_drift": False,
            "issues_count": 0,
        },
    )
    task_dir = tmp_path / "projects" / "test_proj" / "tasks" / "task_0001"
    (task_dir / "user_request.md").write_text(
        "Hello world\nThis is a real request.\nI need you to build a calculator.",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["run-pipeline", "--task-id", "task_0001", "--project", "test_proj", "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    event_types = {event.event_type for event in query_timeline(str(tmp_path))}
    assert {"executor_started", "executor_finished", "phase_accepted"} <= event_types
