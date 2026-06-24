"""Tests for project-init CLI command."""

import sys
from pathlib import Path
import tempfile
import yaml
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.project_ops.cli import app

runner = CliRunner()

def test_project_init_cli_with_contracts():
    contract_data = {
        "task_id": "mission_m1",
        "project_id": "CLIDemo",
        "task_type": "coding",
        "project_type": "codebase_build_project",
        "user_goal": "CLI novel goal",
        "intent_summary": "Summary of CLI novel intent",
        "required_capabilities": [{"capability": "local_search"}],
        "risk_flags": ["regression_risk"]
    }

    plan_data = {
        "project_id": "CLIDemo",
        "template_id": "codebase_build_workflow",
        "project_type": "codebase_build_project",
        "mission_contract_path": "/path/to/contract.yml",
        "phases": [
            {
                "phase_id": "phase_01",
                "title": "compile_mission",
                "goal": "Compile mission",
                "expected_artifacts": ["mission_contract.yml"],
                "acceptance_gates": ["gate_1"]
            }
        ]
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        contract_path = tmp_path / "mission.yml"
        plan_path = tmp_path / "plan.yml"

        contract_path.write_text(yaml.safe_dump(contract_data), encoding="utf-8")
        plan_path.write_text(yaml.safe_dump(plan_data), encoding="utf-8")

        result = runner.invoke(app, [
            "project-init",
            "--mission-contract", str(contract_path),
            "--workflow-plan", str(plan_path),
            "--project", "CLIDemo",
            "--root", str(tmp_path)
        ])

        assert result.exit_code == 0, f"Command failed: {result.output}"

        project_root = tmp_path / "projects" / "CLIDemo"
        assert project_root.exists()
        assert (project_root / "project.yml").exists()

        # Verify project_brain directory and files
        brain_root = project_root / "project_brain"
        assert brain_root.exists()
        assert (brain_root / "project_brief.yml").exists()
        assert (brain_root / "product_vision.md").exists()
        assert (brain_root / "roadmap.yml").exists()
        assert (brain_root / "milestone_graph.yml").exists()
        assert (brain_root / "current_phase.yml").exists()
        assert (brain_root / "phase_plan.yml").exists()

        # Verify other directories
        assert (project_root / "artifacts").exists()
        assert (project_root / "evidence").exists()
        assert (project_root / "acceptance").exists()
