import pytest
from typer.testing import CliRunner
from agent_runtime.run_task import app

runner = CliRunner()

def test_m2_assistant_explain_route_cmd(tmp_path):
    decision_file = tmp_path / "route_decision.yml"
    decision_file.write_text('''
route_plan:
  decisions:
    - role: Coder
      selected_worker: claude_code
      route_profile: best_match
      rejected_alternatives:
        - worker_id: hermes
          reason: Needs API key
''')

    result = runner.invoke(app, ["explain-route", "--decision", str(decision_file)])
    assert result.exit_code == 0
    assert "Role: Coder" in result.output
    assert "claude_code" in result.output
    assert "hermes: Needs API key" in result.output
