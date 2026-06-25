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
    program_dict = {
        "goal_id": program.goal_id,
        "template_id": program.template_id,
        "series": program.series,
        "stages": [s.__dict__ for s in program.stages]
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
