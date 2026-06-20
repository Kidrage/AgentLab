"""Tests for Project Workflow Planner logic."""

from pathlib import Path
import tempfile
import yaml
import pytest

from agent_runtime.project_workflows.planner import create_project_workflow_plan
from agent_runtime.project_workflows.models import ProjectWorkflowPlan

@pytest.fixture
def agentlab_root():
    return Path(__file__).resolve().parents[1]

def test_create_workflow_plan_codebase(agentlab_root):
    # Create a mock mission contract YAML
    contract_data = {
        "project_type": "codebase_build_project",
        "task_id": "task_1234",
        "project_id": "AgentLab",
        "decision_cards": ["card_1", "card_2"]
    }
    
    with tempfile.TemporaryDirectory() as tmpdir:
        contract_path = Path(tmpdir) / "mission_contract.yml"
        with open(contract_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(contract_data, f)
            
        plan = create_project_workflow_plan(
            mission_contract_path=contract_path,
            agentlab_root=agentlab_root,
            project_id="AgentLab"
        )
        
        assert isinstance(plan, ProjectWorkflowPlan)
        assert plan.project_id == "AgentLab"
        assert plan.project_type == "codebase_build_project"
        assert plan.template_id == "codebase_build_workflow"
        assert len(plan.phases) >= 5
        
        # Check first phase
        first_phase = plan.phases[0]
        assert first_phase.title == "compile_mission"
        assert "mission_contract.yml" in first_phase.expected_artifacts
        assert "intent_summary.md" in first_phase.expected_artifacts
        
        # Check inherited decision cards
        assert "card_1" in plan.decision_points
        assert "card_2" in plan.decision_points
        assert not plan.warnings

def test_create_workflow_plan_unknown_project(agentlab_root):
    contract_data = {
        "project_type": "unknown_project",
        "task_id": "task_9999",
        "project_id": "MysteryProject"
    }
    
    with tempfile.TemporaryDirectory() as tmpdir:
        contract_path = Path(tmpdir) / "mission_contract.yml"
        with open(contract_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(contract_data, f)
            
        plan = create_project_workflow_plan(
            mission_contract_path=contract_path,
            agentlab_root=agentlab_root,
            project_id="MysteryProject"
        )
        
        assert plan.project_type == "unknown_project"
        assert plan.template_id == "unknown_project_workflow"
        assert "Unknown project type detected. Clarification is required before execution can proceed." in plan.warnings
        assert "clarify_unknown_project_intent" in plan.decision_points

def test_create_workflow_plan_fallback_artifacts(agentlab_root):
    # Test that artifact templates / contracts fallback mechanism works
    # Create custom workflow templates where expected_artifacts are empty, to force fallback resolution.
    # But since we read from standard config, let's verify that the standard phases correctly fallback.
    # E.g. in config/project_workflow_templates.yml, the phases don't define "expected_artifacts" or "acceptance_gates" directly.
    # Therefore, they should be successfully resolved from project_phase_artifact_templates.yml and project_phase_acceptance_templates.yml!
    
    contract_data = {
        "project_type": "local_automation_project",
        "task_id": "task_5678",
        "project_id": "Auto"
    }
    
    with tempfile.TemporaryDirectory() as tmpdir:
        contract_path = Path(tmpdir) / "mission_contract.yml"
        with open(contract_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(contract_data, f)
            
        plan = create_project_workflow_plan(
            mission_contract_path=contract_path,
            agentlab_root=agentlab_root
        )
        
        # Find test_dry_run phase
        dry_run_phase = next((p for p in plan.phases if p.title == "test_dry_run"), None)
        assert dry_run_phase is not None
        assert "dry_run_results.yml" in dry_run_phase.expected_artifacts
        assert "dry_run_log.txt" in dry_run_phase.expected_artifacts
        assert any("dry_run" in gate.lower() for gate in dry_run_phase.acceptance_gates)
