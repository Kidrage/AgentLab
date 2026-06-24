import pytest
from typer.testing import CliRunner
from agent_runtime.run_task import app

runner = CliRunner()

def test_m2_assistant_explain_worker_cmd(tmp_path, monkeypatch):
    monkeypatch.setattr("agent_runtime.run_task._PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("AGENTLAB_ROOT", str(tmp_path))
    # Fake config
    fake_candidates = [
        {
            "worker_id": "claude_code",
            "display_name": "Claude Code",
            "command": "claude",
            "installed": True,
            "authenticated": "yes",
            "category": "Code"
        },
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

    result = runner.invoke(app, ["explain-worker", "--worker", "claude_code"])
    assert result.exit_code == 0
    assert "Worker Diagnosis: Claude Code (claude_code)" in result.output
    assert "Worker appears fully healthy" in result.output

    result2 = runner.invoke(app, ["explain-worker", "--worker", "broken_worker"])
    assert result2.exit_code == 0
    assert "Issue: Not Installed" in result2.output
