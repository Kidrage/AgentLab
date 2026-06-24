import pytest
from typer.testing import CliRunner
from agent_runtime.run_task import app

runner = CliRunner()

def test_assistant_cli_ask(monkeypatch, tmp_path):
    monkeypatch.setattr("agent_runtime.run_task._PROJECT_ROOT", tmp_path)
    result = runner.invoke(app, ["assistant", "ask", "--project", "Demo", "--mode", "operator", "What is blocked?"])
    assert result.exit_code == 0
    assert "Answer:" in result.output

def test_assistant_cli_explain_phase(monkeypatch, tmp_path):
    monkeypatch.setattr("agent_runtime.run_task._PROJECT_ROOT", tmp_path)
    proj_dir = tmp_path / "projects" / "Demo" / "tasks" / "phase_001"
    proj_dir.mkdir(parents=True)
    
    result = runner.invoke(app, ["assistant", "explain-phase", "--project", "Demo", "--phase", "phase_001"])
    assert result.exit_code == 0
    assert "unknown" in result.output
