import pytest
import yaml
from typer.testing import CliRunner
from agent_runtime.run_task import app

runner = CliRunner()

def test_route_explainer_with_valid_fixture(tmp_path):
    """
    Test that the route explainer can parse a valid route decision
    and output a human-readable explanation.
    """
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

    result = runner.invoke(app, ["assistant", "explain-route", "--decision", str(decision_file)])
    assert result.exit_code == 0
    
    # Must identify the role correctly
    assert "Role: Coder" in result.output
    
    # Must identify the chosen worker
    assert "claude_code" in result.output
    
    # Must expose rejected alternatives
    assert "hermes: Needs API key" in result.output

def test_route_explainer_missing_file(tmp_path):
    """
    Test that passing a missing decision file safely errors
    without crashing unexpectedly.
    """
    missing_file = tmp_path / "missing.yml"
    result = runner.invoke(app, ["assistant", "explain-route", "--decision", str(missing_file)])
    assert result.exit_code != 0
