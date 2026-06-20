"""Tests for Project Workflow CLI commands."""

import sys
from pathlib import Path
import tempfile
import yaml
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from run_task import app

runner = CliRunner()

def test_project_workflow_plan_cli():
    # Setup temporary files
    contract_data = {
        "project_type": "codebase_build_project",
        "task_id": "task_4567",
        "project_id": "CLIProj"
    }
    
    with tempfile.TemporaryDirectory() as tmpdir:
        contract_path = Path(tmpdir) / "mission_contract.yml"
        out_dir = Path(tmpdir) / "out"
        
        with open(contract_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(contract_data, f)
            
        result = runner.invoke(app, [
            "project-workflow-plan",
            "--mission-contract", str(contract_path),
            "--out", str(out_dir)
        ])
        
        assert result.exit_code == 0, f"Command failed: {result.output}"
        
        # Verify files were created
        yaml_path = out_dir / "project_workflow_plan.yml"
        md_path = out_dir / "project_workflow_plan.md"
        
        assert yaml_path.exists()
        assert md_path.exists()
        
        # Read files and verify content
        with open(yaml_path, "r", encoding="utf-8") as f:
            plan_yaml = yaml.safe_load(f)
            
        assert plan_yaml["project_id"] == "CLIProj"
        assert plan_yaml["project_type"] == "codebase_build_project"
        assert len(plan_yaml["phases"]) >= 5
        
        md_content = md_path.read_text(encoding="utf-8")
        assert "Project Workflow Plan: CLIProj" in md_content
        assert "**Template ID**: `codebase_build_workflow`" in md_content
