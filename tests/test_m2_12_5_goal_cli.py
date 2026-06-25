from typer.testing import CliRunner
from agent_runtime.run_task import app

runner = CliRunner()

def test_cli_goal_set(tmp_path):
    result = runner.invoke(app, ["goal", "set", "--text", "fix stuff", "--project", "TestProj", "--out", str(tmp_path)])
    assert result.exit_code == 0
    assert "Goal " in result.stdout

def test_cli_goal_plan(tmp_path):
    runner.invoke(app, ["goal", "set", "--text", "fix stuff", "--project", "TestProj", "--out", str(tmp_path)])
    result = runner.invoke(app, ["goal", "plan", "--project", "TestProj", "--out", str(tmp_path)])
    assert result.exit_code == 0

def test_cli_goal_status_progress_validate_report(tmp_path):
    runner.invoke(app, ["goal", "set", "--text", "fix stuff", "--project", "TestProj", "--out", str(tmp_path)])
    runner.invoke(app, ["goal", "plan", "--project", "TestProj", "--out", str(tmp_path)])
    for cmd in ["status", "progress", "validate", "report"]:
        result = runner.invoke(app, ["goal", cmd, "--project", "TestProj", "--out", str(tmp_path)])
        assert result.exit_code == 0
