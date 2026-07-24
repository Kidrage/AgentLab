from typer.testing import CliRunner
from agent_runtime.run_task import app
from agentlab_tui.app import run_tui

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


def test_tui_cli_interactive_entrypoint_can_exit():
    result = runner.invoke(app, ["tui"], input="/quit\n")

    assert result.exit_code == 0, result.output
    assert "AgentLab Natural-Language TUI" in result.output
    assert "Project: AgentLab" in result.output


def test_natural_language_tui_initializes_only():
    inputs = iter(["实现一个安全的状态查询接口", "/quit"])
    submitted = []
    output = []

    def fake_submit(project: str, request: str) -> tuple[bool, str]:
        submitted.append((project, request))
        return True, "created task_123"

    run_tui(
        project="Demo",
        input_fn=lambda _prompt: next(inputs),
        output_fn=output.append,
        submit_fn=fake_submit,
    )

    assert submitted == [("Demo", "实现一个安全的状态查询接口")]
    assert "Task initialized; no execution or provider call was started." in output
    assert "created task_123" in output
