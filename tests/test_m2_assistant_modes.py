import pytest
from typer.testing import CliRunner
from agent_runtime.run_task import app

runner = CliRunner()

def test_m2_assistant_ask_cmd(tmp_path, monkeypatch):
    monkeypatch.setattr("agent_runtime.run_task._PROJECT_ROOT", tmp_path)
    
    # Mock LLM response
    from agent_runtime.schemas import LLMCallResult
    def fake_generate_text(settings, providers, messages, **kwargs):
        return LLMCallResult(
            provider="fake",
            model="fake",
            content="This is a grounded answer.",
        )
    monkeypatch.setattr("agent_runtime.assistant.modes.generate_text", fake_generate_text)
    
    result = runner.invoke(app, ["ask", "--project", "DemoProject", "Why is it blocked?"])
    assert result.exit_code == 0
    assert "This is a grounded answer." in result.output
