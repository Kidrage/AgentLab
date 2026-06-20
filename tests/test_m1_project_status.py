"""Tests for project-status CLI command and project_status logic."""

import sys
from pathlib import Path
import tempfile
import yaml
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.project_ops.cli import app
from agent_runtime.project_ops.project_router import init_project, project_status, render_project_status

runner = CliRunner()

def test_project_status_logic_and_rendering(tmp_path: Path):
    # Initialize basic project
    init_project(tmp_path, "status_proj", "coding", "Status Project")
    
    # Write some custom risks and questions to project_brain
    brain_root = tmp_path / "projects" / "status_proj" / "project_brain"
    
    yaml_risks = {"risks": ["risk_a", "risk_b"]}
    (brain_root / "known_risks.yml").write_text(yaml.safe_dump(yaml_risks), encoding="utf-8")
    
    yaml_questions = {"questions": ["question_a"]}
    (brain_root / "unresolved_questions.yml").write_text(yaml.safe_dump(yaml_questions), encoding="utf-8")
    
    # Write dictionary next_actions
    next_action_data = {
        "next_phase_id": "phase_02",
        "next_action": "run_tests",
        "reason": "unaccepted phase"
    }
    (brain_root / "next_actions.yml").write_text(yaml.safe_dump(next_action_data), encoding="utf-8")
    
    # Check project_status loading
    status = project_status(tmp_path, "status_proj")
    assert status["known_risks"] == ["risk_a", "risk_b"]
    assert status["unresolved_questions"] == ["question_a"]
    assert status["next_actions_data"]["next_action"] == "run_tests"
    
    # Check render_project_status output
    rendered = render_project_status(status)
    assert "# Project Status" in rendered
    assert "- Project: `status_proj`" in rendered
    assert "- Display name: Status Project" in rendered
    assert "risk_a" in rendered
    assert "risk_b" in rendered
    assert "Next Action: run_tests" in rendered
    assert "Next Phase: phase_02" in rendered
    assert "Reason: unaccepted phase" in rendered

def test_project_status_cli_command():
    contract_data = {
        "task_id": "mission_status",
        "project_id": "CLIDemoStatus",
        "task_type": "coding",
        "project_type": "codebase_build_project",
        "user_goal": "CLI goal",
        "intent_summary": "Summary of CLI intent",
        "required_capabilities": [{"capability": "local_search"}],
        "risk_flags": ["regression_risk"]
    }
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        contract_path = tmp_path / "mission.yml"
        contract_path.write_text(yaml.safe_dump(contract_data), encoding="utf-8")
        
        # Init
        runner.invoke(app, [
            "project-init",
            "--mission-contract", str(contract_path),
            "--project", "CLIDemoStatus",
            "--root", str(tmp_path)
        ])
        
        # Check Status
        result = runner.invoke(app, [
            "project-status",
            "--project", "CLIDemoStatus",
            "--root", str(tmp_path)
        ])
        
        assert result.exit_code == 0, f"Command failed: {result.output}"
        assert "Project: `CLIDemoStatus`" in result.output
        assert "Next Action: prepare_phase_task_packet" in result.output
