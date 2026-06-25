from pathlib import Path
from agent_runtime.goals.models import MainlineProgress, MainlineProgram, GoalCommandResult
from agent_runtime.goals.action_schema import GoalActionSchema
from agent_runtime.goals.storage import write_yaml, read_yaml, get_project_brain_dir

def init_progress(brain_dir: Path, goal_id: str, program: MainlineProgram):
    progress = MainlineProgress(
        goal_id=goal_id,
        completed_stages=[],
        pending_stages=[s.stage_id for s in program.stages if s.status != "future_reserved"],
        blocked_stages=[]
    )
    write_yaml(brain_dir / "mainline_progress.yml", progress.__dict__)

def compile_goal_progress(action: GoalActionSchema, agentlab_root: Path) -> GoalCommandResult:
    brain_dir = get_project_brain_dir(agentlab_root, action.project)
    path = brain_dir / "mainline_progress.yml"
    if not path.exists():
        return GoalCommandResult("error", [], "No mainline progress found.")
    
    return GoalCommandResult(
        status="ok",
        artifacts=["mainline_progress.yml"],
        message="Progress updated."
    )
