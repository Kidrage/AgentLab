from pathlib import Path
from agent_runtime.goals.models import MainlineProgress, MainlineProgram, GoalCommandResult
from agent_runtime.goals.action_schema import GoalActionSchema
from agent_runtime.goals.storage import write_yaml, read_yaml, get_project_brain_dir, append_to_yaml_list
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_progress(brain_dir: Path, goal_id: str, program: MainlineProgram):
    progress = MainlineProgress(
        goal_id=goal_id,
        completed_stages=[],
        pending_stages=[s.stage_id for s in program.stages if s.status != "future_reserved"],
        blocked_stages=[],
        evidence=program.evidence if hasattr(program, 'evidence') else [],
        gates=program.gates if hasattr(program, 'gates') else {},
    )
    write_yaml(brain_dir / "mainline_progress.yml", progress.__dict__)


def compile_goal_progress(action: GoalActionSchema, agentlab_root: Path) -> GoalCommandResult:
    brain_dir = get_project_brain_dir(agentlab_root, action.project)
    path = brain_dir / "mainline_progress.yml"
    if not path.exists():
        return GoalCommandResult("error", [], "No mainline progress found.")

    append_to_yaml_list(brain_dir / "acceptance_history.yml", {
        "timestamp": _now(),
        "action": "goal_progress",
        "status": "progress_recorded",
    })

    return GoalCommandResult(
        status="ok",
        artifacts=["mainline_progress.yml"],
        message="Progress updated."
    )
