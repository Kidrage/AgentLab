import pytest
from typer.testing import CliRunner
import os
import yaml
from pathlib import Path
from agent_runtime.run_task import app
from agent_runtime.observability.query import query_timeline

runner = CliRunner()

def test_pipeline_smoke(tmp_path, monkeypatch):
    monkeypatch.setattr("agent_runtime.run_task._PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("AGENTLAB_ROOT", str(tmp_path))
    (tmp_path / "agentlab.sh").touch()
    (tmp_path / "agent_runtime").mkdir(exist_ok=True)

    monkeypatch.setattr("agent_runtime.routing.role_assignment.DEFAULT_CANDIDATES", [
        {"worker_id": "mock_worker", "display_name": "Mock", "installed": True, "category": "General", "cost_tier": "free", "command": "echo", "authenticated": "yes"}
    ])
    
    # 1. cost-estimate -> cost_estimated event
    task_packet = tmp_path / "task.yml"
    task_packet.write_text("project_id: AgentLab\ntask_id: task_0001\nmodel: gpt-4\nrole: coder")
    
    result = runner.invoke(app, ["cost-estimate", "--task-packet", str(task_packet)])
    assert result.exit_code == 0
    
    events = query_timeline(str(tmp_path), event_type="cost_estimated")
    assert len(events) >= 1
    
    # 2. route-task -> route_decision_created event
    # First write some policies needed for routing if they don't exist
    import shutil
    shutil.copytree(Path("config").resolve(), tmp_path / "config", dirs_exist_ok=True)
    result = runner.invoke(app, ["route-task", "--task-packet", str(task_packet)])
    assert result.exit_code == 0, f"route-task failed: {result.output}"
    events = query_timeline(str(tmp_path), event_type="route_decision_created")
    assert len(events) >= 1
    
    # 3. assign-role -> role_assigned event
    result = runner.invoke(app, ["assign-role", "--role", "coder", "--project", "test_proj"])
    assert result.exit_code == 0, f"assign-role failed: {result.output}"
    events = query_timeline(str(tmp_path), event_type="role_assigned")
    assert len(events) >= 1
    
    from agent_runtime.approvals.decision_card import DecisionCard
    from agent_runtime.approvals.approval_ledger import ApprovalLedger, write_approval_ledger
    ledger_path = tmp_path / "memory" / "test_proj" / "approval_ledger.yml"
    ledger = ApprovalLedger("test_proj")
    docs_dir = tmp_path / "projects" / "test_proj" / "tasks" / "task_0001" / "raw"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "user_request.md").write_text("Hello world\nThis is a real request.")
    dc1 = DecisionCard(decision_id="d1", decision_type="test", status="pending", reason="test", risk_level="low", requested_by="u1", task_id="task_0001", project="test_proj", phase_id="p1", capabilities=[], estimated_cost_usd=0, evidence_artifacts=[], created_at="now", updated_at="now", expires_at="now")
    dc2 = DecisionCard(decision_id="d2", decision_type="test", status="pending", reason="test", risk_level="low", requested_by="u1", task_id="task_0001", project="test_proj", phase_id="p1", capabilities=[], estimated_cost_usd=0, evidence_artifacts=[], created_at="now", updated_at="now", expires_at="now")
    ledger.approvals = [dc1, dc2]
    write_approval_ledger(ledger, ledger_path)

    # 4. approve -> approval_accepted event
    result = runner.invoke(app, ["approve", "--decision-id", "d1", "--actor", "user", "--reason", "ok", "--project", "test_proj"])
    assert result.exit_code == 0, f"approve failed: {result.output}"
    events = query_timeline(str(tmp_path), event_type="approval_accepted")
    assert len(events) >= 1
    
    # 5. reject -> approval_rejected event
    result = runner.invoke(app, ["reject", "--decision-id", "d2", "--actor", "user", "--reason", "no", "--project", "test_proj"])
    assert result.exit_code == 0
    events = query_timeline(str(tmp_path), event_type="approval_rejected")
    assert len(events) >= 1
    
    # 6. run-pipeline (dry-run) -> executor_started, executor_finished, phase_accepted
    monkeypatch.setattr("pipeline_runner.validate_artifacts", lambda run_dir: {"valid": True, "pass_rate": 1.0, "artifacts_checked": 1, "artifacts_passed": 1, "issues": [], "snapshot_drift": False, "issues_count": 0})
    
    docs_dir = tmp_path / "projects" / "test_proj" / "tasks" / "task_0001"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "user_request.md").write_text("Hello world\nThis is a real request.\nI need you to build a calculator.")
    
    result = runner.invoke(app, ["run-pipeline", "--task-id", "task_0001", "--project", "test_proj", "--dry-run"])
    assert result.exit_code == 0, f"run-pipeline failed: {result.output}"
    events_started = query_timeline(str(tmp_path), event_type="executor_started")
    all_events = query_timeline(str(tmp_path))
    assert len(events_started) >= 1, f"No executor_started. Output: {result.output}. All events: {[e.event_type for e in all_events]}"
    
    events_finished = query_timeline(str(tmp_path), event_type="executor_finished")
    assert len(events_finished) >= 1
    
    events_phase = query_timeline(str(tmp_path), event_type="phase_accepted")
    assert len(events_phase) >= 1
