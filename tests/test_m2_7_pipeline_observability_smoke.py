import pytest
from typer.testing import CliRunner
import os
import yaml
from agent_runtime.run_task import app
from agent_runtime.observability.query import query_timeline

runner = CliRunner()

def test_pipeline_smoke(tmp_path, monkeypatch):
    monkeypatch.setattr("agent_runtime.run_task._PROJECT_ROOT", tmp_path)
    
    # Provide dummy task packet for cost_estimate
    task_packet = tmp_path / "task.yml"
    task_packet.write_text("project_id: AgentLab\ntask_id: t1\nmodel: gpt-4")
    
    # Run a wired command
    result = runner.invoke(app, ["cost-estimate", "--task-packet", str(task_packet)])
    assert result.exit_code == 0
    
    events = query_timeline(str(tmp_path), event_type="cost_estimated")
    assert len(events) == 1
    assert events[0].details["model"] == "gpt-4"
    assert events[0].task_id == "t1"
