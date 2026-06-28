from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

from agent_runtime.project_workflows.models import ProjectWorkflowPlan, PhasePlan
from agent_runtime.project_workflows.loader import (
    load_workflow_templates,
    load_phase_artifact_templates,
    load_phase_acceptance_templates,
    load_yaml
)
from agent_runtime.project_workflows.matcher import match_template

def create_project_workflow_plan(
    mission_contract_path: Path,
    agentlab_root: Path,
    project_id: Optional[str] = None,
) -> ProjectWorkflowPlan:
    """Generate a ProjectWorkflowPlan based on the mission contract."""
    # Load mission contract
    if not mission_contract_path.exists():
        raise FileNotFoundError(f"Mission contract not found: {mission_contract_path}")
    
    with open(mission_contract_path, "r", encoding="utf-8") as f:
        contract = yaml.safe_load(f) or {}

    project_type = contract.get("project_type", "unknown_project")
    task_id = contract.get("task_id", "")
    p_id = project_id or contract.get("project_id", "")
    long_governance = contract.get("long_project_governance") or {}
    must_read_artifacts = long_governance.get("must_read_artifacts") or []
    missing_facts = long_governance.get("missing_facts") or []
    artifact_intent = {}
    if p_id:
        try:
            from agent_runtime.project_artifact_steward import build_artifact_intent
        except ImportError:
            from project_artifact_steward import build_artifact_intent
        try:
            artifact_intent = build_artifact_intent(agentlab_root, p_id, task_id)
        except Exception as exc:
            artifact_intent = {"enabled": False, "error": f"{type(exc).__name__}: {exc}"}

    # Load templates
    templates_config = load_workflow_templates(agentlab_root)
    artifact_templates = load_phase_artifact_templates(agentlab_root)
    acceptance_templates = load_phase_acceptance_templates(agentlab_root)

    # Fallback artifact source: project_artifact_contracts.yml
    artifact_contracts = load_yaml(agentlab_root / "config" / "project_artifact_contracts.yml")
    phase_artifacts_fallback = artifact_contracts.get("phase_artifacts", {})

    # Match template
    template = match_template(project_type, templates_config)
    template_id = template.get("template_id", f"{project_type}_workflow")

    phases: List[PhasePlan] = []
    warnings: List[str] = []
    decision_points: List[str] = []

    # Handle unknown_project cases or warnings
    if project_type == "unknown_project" or not template:
        warnings.append("Unknown project type detected. Clarification is required before execution can proceed.")
        decision_points.append("clarify_unknown_project_intent")

    template_phases = template.get("phases", [])
    for i, p_data in enumerate(template_phases):
        title = p_data.get("title", "")
        phase_id = f"phase_{i + 1:02d}"

        # Resolve artifacts
        expected_artifacts = p_data.get("expected_artifacts", [])
        if not expected_artifacts:
            # Try from project_phase_artifact_templates.yml
            expected_artifacts = artifact_templates.get(title, {}).get("artifacts", [])
        if not expected_artifacts:
            # Try fallback from project_artifact_contracts.yml
            expected_artifacts = phase_artifacts_fallback.get(title, {}).get("outputs", [])

        # Resolve expected outputs
        expected_outputs = p_data.get("expected_outputs", [])
        if not expected_outputs:
            expected_outputs = expected_artifacts

        # Resolve acceptance gates
        acceptance_gates = p_data.get("acceptance_gates", [])
        if not acceptance_gates:
            acceptance_gates = acceptance_templates.get(title, {}).get("gates", [])

        phase = PhasePlan(
            phase_id=phase_id,
            title=title,
            goal=p_data.get("goal", f"Complete {title.replace('_', ' ')}"),
            required_inputs=p_data.get("required_inputs", []),
            expected_outputs=expected_outputs,
            expected_artifacts=expected_artifacts,
            required_capabilities=p_data.get("required_capabilities", []),
            recommended_skills=p_data.get("recommended_skills", []),
            recommended_executors=p_data.get("recommended_executors", []),
            acceptance_gates=acceptance_gates,
            human_decision_points=p_data.get("human_decision_points", []),
            failure_recovery=p_data.get("failure_recovery", []),
            asset_registry_updates=p_data.get("asset_registry_updates", []),
            next_phase_conditions=p_data.get("next_phase_conditions", []),
            must_read_artifacts=must_read_artifacts,
            missing_facts=missing_facts,
            plan_status="needs_revision" if missing_facts else "ready",
            self_check={
                "passed": not bool(missing_facts),
                "checks": [
                    "required_artifacts_resolved",
                    "must_read_artifacts_listed",
                    "revision_log_preserved",
                ],
            },
            revision_log=contract.get("revision_log") or [],
            artifact_intent=artifact_intent,
        )
        phases.append(phase)

    # Inherit decision points from mission contract
    contract_decision_cards = contract.get("decision_cards", [])
    if contract_decision_cards:
        decision_points.extend(contract_decision_cards)

    return ProjectWorkflowPlan(
        project_id=p_id,
        template_id=template_id,
        project_type=project_type,
        mission_contract_path=str(mission_contract_path),
        phases=phases,
        warnings=warnings,
        decision_points=decision_points,
    )
