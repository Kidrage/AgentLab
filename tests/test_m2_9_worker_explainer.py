import pytest
from typer.testing import CliRunner
from agent_runtime.run_task import app

runner = CliRunner()

def test_worker_explainer_healthy_worker(tmp_path, monkeypatch):
    """
    Test that explaining a healthy, installed worker produces
    the correct output and diagnosis.
    """
    monkeypatch.setattr("agent_runtime.run_task._PROJECT_ROOT", tmp_path)
    
    fake_candidates = [
        {
            "worker_id": "claude_code",
            "display_name": "Claude Code",
            "command": "claude",
            "installed": True,
            "authenticated": "yes",
            "category": "Code"
        }
    ]
    monkeypatch.setattr("agent_runtime.workers.detector.DEFAULT_CANDIDATES", fake_candidates)

    result = runner.invoke(app, ["assistant", "explain-worker", "--worker", "claude_code"])
    assert result.exit_code == 0
    assert "Worker Diagnosis: Claude Code (claude_code)" in result.output
    assert "Worker appears fully healthy" in result.output

def test_worker_explainer_broken_worker(tmp_path, monkeypatch):
    """
    Test that explaining a broken or missing worker identifies
    the underlying installation issue clearly.
    """
    monkeypatch.setattr("agent_runtime.run_task._PROJECT_ROOT", tmp_path)
    
    fake_candidates = [
        {
            "worker_id": "broken_worker",
            "display_name": "Broken Worker",
            "command": "broken",
            "installed": False,
            "authenticated": "unknown",
            "category": "None"
        }
    ]
    monkeypatch.setattr("agent_runtime.workers.detector.DEFAULT_CANDIDATES", fake_candidates)

    result = runner.invoke(app, ["assistant", "explain-worker", "--worker", "broken_worker"])
    assert result.exit_code == 0
    assert "Issue: Not Installed" in result.output
