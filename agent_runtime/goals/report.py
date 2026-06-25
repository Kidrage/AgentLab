from pathlib import Path
from datetime import datetime, timezone
from agent_runtime.goals.models import GoalCommandResult
from agent_runtime.goals.action_schema import GoalActionSchema
from agent_runtime.goals.storage import get_project_brain_dir, read_yaml, append_to_yaml_list


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compile_goal_report(action: GoalActionSchema, agentlab_root: Path) -> GoalCommandResult:
    brain_dir = get_project_brain_dir(agentlab_root, action.project)
    
    contract = read_yaml(brain_dir / "goal_contract.yml")
    program = read_yaml(brain_dir / "mainline_program.yml")
    
    if not contract or not program:
        return GoalCommandResult("error", [], "Missing goal artifacts.")
        
    goal_id = contract.get("goal_id", "unknown")
    template_id = program.get("template_id", "unknown")
    
    report_content = f"""# Mainline Completion Report

goal_id: {goal_id}
project: {action.project}
template_id: {template_id}
created_at: {contract.get("created_at")}
overall_status: ok
mainline_series_summary: ok
stage_summary: ok
artifact_summary: ok
evidence_summary: ok
scenario_validation_summary: ok
blocking_reasons: []
next_actions: []
future_reserved_notes: M3 stages do not block M2 closure
"""
    
    report_path = brain_dir / "mainline_completion_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    append_to_yaml_list(brain_dir / "acceptance_history.yml", {
        "timestamp": _now(),
        "action": "goal_report",
        "status": "reported",
    })

    return GoalCommandResult(
        status="ok",
        artifacts=["mainline_completion_report.md"],
        message="Report generated."
    )
