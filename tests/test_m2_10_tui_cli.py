import pytest
from typer.testing import CliRunner
from agent_runtime.run_task import app

runner = CliRunner()

def test_tui_cli_headless():
    """
    Test that ./agentlab.sh tui --headless works without launching
    the interactive UI and without requiring textual/curses.
    """
    result = runner.invoke(app, ["tui", "--headless", "--view", "overview", "--project", "Demo"])
    assert result.exit_code == 0
    assert "=== AgentLab TUI Headless Snapshot ===" in result.output
    assert "Project: Demo" in result.output

def test_tui_cli_headless_missing_project():
    """
    Test that ./agentlab.sh tui --headless works even without a project.
    """
    result = runner.invoke(app, ["tui", "--headless"])
    assert result.exit_code == 0
    assert "[None selected]" in result.output
