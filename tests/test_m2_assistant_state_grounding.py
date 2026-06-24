import pytest
from typer.testing import CliRunner
from agent_runtime.run_task import app
import json

runner = CliRunner()

def test_m2_assistant_explain_phase_and_cost(tmp_path, monkeypatch):
    monkeypatch.setattr("agent_runtime.run_task._PROJECT_ROOT", tmp_path)
    
    # Setup state
    project_dir = tmp_path / "projects" / "DemoProject"
    task_dir = project_dir / "tasks" / "phase_001"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "state.yml").write_text("status: running\ncurrent_agent: RepoScout")
    
    # Setup cost
    obs_dir = project_dir / "observability"
    obs_dir.mkdir(parents=True, exist_ok=True)
    with open(obs_dir / "timeline.jsonl", "w") as f:
        f.write(json.dumps({"event_type": "cost_estimated", "cost_usd": 1.25}) + "\n")
        
    result = runner.invoke(app, ["explain-phase", "--project", "DemoProject", "--phase", "phase_001"])
    assert result.exit_code == 0
    assert "Status**: running" in result.output
    assert "Current Agent**: RepoScout" in result.output

    result2 = runner.invoke(app, ["explain-cost", "--project", "DemoProject"])
    assert result2.exit_code == 0
    assert "$1.25" in result2.output
