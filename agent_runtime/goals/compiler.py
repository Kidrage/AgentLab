from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime, timezone
import uuid

from agent_runtime.goals.models import (
    GoalContract, MissionContract, WorkflowPlan, MainlineProgram, MainlineStage,
    MainlineAcceptanceContract, ScenarioValidationPlan, GoalCommandResult
)
from agent_runtime.goals.action_schema import GoalActionSchema
from agent_runtime.goals.templates import select_template
from agent_runtime.goals.storage import get_project_brain_dir, write_yaml, read_yaml, append_to_yaml_list

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_artifact(brain_dir: Path, filename: str, content: dict) -> None:
    """Write an artifact file only if it doesn't already exist."""
    target = brain_dir / filename
    if not target.exists():
        write_yaml(target, content)


def compile_goal_set(action: GoalActionSchema, agentlab_root: Path) -> GoalCommandResult:
    brain_dir = get_project_brain_dir(agentlab_root, action.project)
    
    goal_id = f"goal_{uuid.uuid4().hex[:8]}"
    template = select_template(action.text)
    
    contract = GoalContract(
        goal_id=goal_id,
        project=action.project,
        raw_requirement=action.text,
        compiled_template=template["template_id"],
        created_at=_now()
    )
    
    write_yaml(brain_dir / "goal_contract.yml", contract.__dict__)
    
    append_to_yaml_list(brain_dir / "decision_log.yml", {
        "timestamp": _now(),
        "decision": "goal set",
        "goal_id": goal_id
    })
    
    append_to_yaml_list(brain_dir / "next_actions.yml", {
        "timestamp": _now(),
        "action": "/goal plan"
    })
    
    action.goal_id = goal_id
    
    append_to_yaml_list(brain_dir / "acceptance_history.yml", {
        "timestamp": _now(),
        "action": "goal_set",
        "status": "recorded",
        "goal_id": goal_id,
    })

    return GoalCommandResult(
        status="ok",
        artifacts=["goal_contract.yml", "decision_log.yml", "next_actions.yml"],
        message=f"Goal {goal_id} set. Next action: /goal plan"
    )

def compile_goal_plan(action: GoalActionSchema, agentlab_root: Path) -> GoalCommandResult:
    brain_dir = get_project_brain_dir(agentlab_root, action.project)
    
    goal_contract_path = brain_dir / "goal_contract.yml"
    if not goal_contract_path.exists():
        return GoalCommandResult("error", [], "No goal contract found. Run /goal set first.")
        
    contract_data = read_yaml(goal_contract_path)
    goal_id = contract_data.get("goal_id", "unknown")
    template_id = contract_data.get("compiled_template", "unknown_large_project")
    
    from agent_runtime.goals.templates import TEMPLATES
    template = TEMPLATES.get(template_id, TEMPLATES["unknown_large_project"])
    
    mission = MissionContract(goal_id=goal_id, mission_statement=f"Fulfill {template['display_name']}")
    write_yaml(brain_dir / "mission_contract.yml", mission.__dict__)
    
    workflow = WorkflowPlan(goal_id=goal_id, stages=[s.get("stage_id", "unnamed") for s in template.get("stages", [])])
    write_yaml(brain_dir / "workflow_plan.yml", workflow.__dict__)
    
    program = MainlineProgram(
        goal_id=goal_id,
        template_id=template_id,
        series=template.get("mainline_series", []),
        stages=[MainlineStage(**s) for s in template.get("stages", [])]
    )

    # Collect all evidence and gates from template stages
    all_evidence: list = ["goal_contract.yml", "mainline_program.yml"]
    all_gates: dict = {"demo_passed": True, "contract_valid": True}
    for stage_data in template.get("stages", []):
        for ev in stage_data.get("required_evidence", []):
            if ev not in all_evidence:
                all_evidence.append(ev)
        for gate in stage_data.get("acceptance_gates", []):
            all_gates[gate] = True

    # Create placeholder files for any template-required artifacts
    _ensure_artifact(brain_dir, "goal_contract.yml",
                     read_yaml(brain_dir / "goal_contract.yml") or {"project": action.project})
    _ensure_artifact(brain_dir, "architecture_state.yml",
                     {"state": "planned", "modules": [], "project": action.project})
    _ensure_artifact(brain_dir, "research_brief.yml",
                     {"project": action.project, "brief": action.text or "", "status": "draft"})
    _ensure_artifact(brain_dir, "repo_manifest.yml",
                     {"project": action.project, "files": [], "status": "pending"})
    _ensure_artifact(brain_dir, "phase_plan.yml",
                     {"phase_id": "phase_01", "status": "planned", "outputs": []})

    program.evidence = all_evidence
    program.gates = all_gates
    program_dict = {
        "goal_id": program.goal_id,
        "template_id": program.template_id,
        "series": program.series,
        "stages": [s.__dict__ for s in program.stages],
        "evidence": program.evidence,
        "gates": program.gates,
    }
    write_yaml(brain_dir / "mainline_program.yml", program_dict)
    
    acceptance = MainlineAcceptanceContract(goal_id=goal_id, acceptance_criteria=["all stages complete"])
    write_yaml(brain_dir / "mainline_acceptance_contract.yml", acceptance.__dict__)
    
    validation = ScenarioValidationPlan(goal_id=goal_id, scenarios=[
        {
            "scenario_id": sv,
            "description": f"Validate {sv}",
            "required_artifacts": [],
            "required_evidence": [],
            "validation_method": "deterministic",
            "pass_condition": "evidence present",
            "blocking_if_missing": True
        } for sv in template.get("scenario_validations", [])
    ])
    write_yaml(brain_dir / "scenario_validation_plan.yml", validation.__dict__)
    
    from agent_runtime.goals.progress import init_progress
    init_progress(brain_dir, goal_id, program)
    
    append_to_yaml_list(brain_dir / "decision_log.yml", {
        "timestamp": _now(),
        "decision": "goal plan",
        "goal_id": goal_id
    })

    append_to_yaml_list(brain_dir / "acceptance_history.yml", {
        "timestamp": _now(),
        "action": "goal_plan",
        "status": "planned",
    })

    return GoalCommandResult(
        status="ok",
        artifacts=[
            "mission_contract.yml",
            "workflow_plan.yml",
            "mainline_program.yml",
            "mainline_acceptance_contract.yml",
            "scenario_validation_plan.yml",
            "mainline_progress.yml"
        ],
        message="Goal planned successfully."
    )
