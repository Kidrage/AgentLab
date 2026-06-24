import sys
from pathlib import Path
import pytest
import yaml
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.program_manager.project_brain import build_project_brain

@pytest.fixture
def mission_contract_path(tmp_path):
    contract = {
        "task_id": "test_task",
        "project_id": "test_project",
        "task_type": "coding",
        "project_type": "codebase_build_project",
        "user_goal": "Write code",
        "intent_summary": "Goal description",
        "required_capabilities": [{"capability": "local_search"}],
        "risk_flags": ["regression_risk"]
    }
    path = tmp_path / "mission_contract.yml"
    path.write_text(yaml.safe_dump(contract), encoding="utf-8")
    return path

@pytest.fixture
def workflow_plan_path(tmp_path):
    plan = {
        "project_id": "test_project",
        "template_id": "codebase_build_workflow",
        "project_type": "codebase_build_project",
        "mission_contract_path": "/path/to/contract.yml",
        "phases": [
            {
                "phase_id": "phase_01",
                "title": "compile_mission",
                "goal": "Compile mission contract",
                "expected_artifacts": ["mission_contract.yml"],
                "acceptance_gates": ["gate_1"]
            },
            {
                "phase_id": "phase_02",
                "title": "run_tests",
                "goal": "Run test suite",
                "expected_artifacts": ["test_results.yml"],
                "acceptance_gates": ["gate_2"]
            }
        ]
    }
    path = tmp_path / "project_workflow_plan.yml"
    path.write_text(yaml.safe_dump(plan), encoding="utf-8")
    return path

def test_build_project_brain_with_workflow_plan(mission_contract_path, workflow_plan_path, tmp_path):
    out_dir = tmp_path / "brain"
    res = build_project_brain(
        mission_contract_path=mission_contract_path,
        project="test_project",
        out_dir=out_dir,
        workflow_plan_path=workflow_plan_path
    )

    assert res["ok"] is True
    assert out_dir.exists()

    # Check that key files exist
    assert (out_dir / "product_vision.md").exists()
    assert (out_dir / "project_brief.yml").exists()
    assert (out_dir / "roadmap.yml").exists()
    assert (out_dir / "milestone_graph.yml").exists()
    assert (out_dir / "current_phase.yml").exists()
    assert (out_dir / "phase_plan.yml").exists()
    assert (out_dir / "decision_log.yml").exists()
    assert (out_dir / "acceptance_history.yml").exists()
    assert (out_dir / "unresolved_questions.yml").exists()
    assert (out_dir / "known_risks.yml").exists()
    assert (out_dir / "architecture_state.yml").exists()
    assert (out_dir / "next_actions.yml").exists()
    assert (out_dir / "snapshots" / "initial.yml").exists()

    # Verify roadmap milestones match workflow plan phases
    roadmap = yaml.safe_load((out_dir / "roadmap.yml").read_text(encoding="utf-8"))
    assert len(roadmap["milestones"]) == 2
    assert roadmap["milestones"][0]["phase_id"] == "phase_01"
    assert roadmap["milestones"][0]["expected_artifacts"] == ["mission_contract.yml"]
    assert roadmap["milestones"][0]["acceptance_gates"] == ["gate_1"]

    # Verify current phase is first milestone
    current = yaml.safe_load((out_dir / "current_phase.yml").read_text(encoding="utf-8"))
    assert current["phase_id"] == "phase_01"
    assert current["status"] == "planned"

    # Verify phase plan matches first phase details
    phase_plan = yaml.safe_load((out_dir / "phase_plan.yml").read_text(encoding="utf-8"))
    assert phase_plan["phase_id"] == "phase_01"
    assert phase_plan["outputs"] == ["mission_contract.yml"]
    assert phase_plan["acceptance_criteria"] == ["gate_1"]

def test_build_project_brain_auto_compiles_workflow_plan(mission_contract_path, tmp_path):
    out_dir = tmp_path / "brain"
    # Call without workflow_plan_path to trigger auto-compilation from templates
    res = build_project_brain(
        mission_contract_path=mission_contract_path,
        project="test_project",
        out_dir=out_dir,
        workflow_plan_path=out_dir / "nonexistent.yml"
    )

    assert res["ok"] is True
    roadmap = yaml.safe_load((out_dir / "roadmap.yml").read_text(encoding="utf-8"))

    # Should have compiled template phases (codebase build has 8 phases)
    assert len(roadmap["milestones"]) >= 5
    assert roadmap["milestones"][0]["phase_id"] == "phase_01"
    assert roadmap["milestones"][0]["title"] == "compile_mission"
    assert "mission_contract.yml" in roadmap["milestones"][0]["expected_artifacts"]
