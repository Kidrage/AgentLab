from agent_runtime.goals.parser import parse_goal_command
from agent_runtime.goals.compiler import compile_goal_set, compile_goal_plan
from agent_runtime.goals.progress import compile_goal_progress
from agent_runtime.goals.validation import compile_goal_validate
from agent_runtime.goals.report import compile_goal_report
from agent_runtime.goals.action_schema import GoalActionSchema
from agent_runtime.goals.models import GoalCommandResult

def execute_goal_action(action: GoalActionSchema, agentlab_root) -> GoalCommandResult:
    if action.status == "error":
        return GoalCommandResult("error", [], ", ".join(action.blocking_reasons))
        
    if action.action == "set":
        return compile_goal_set(action, agentlab_root)
    elif action.action == "plan":
        return compile_goal_plan(action, agentlab_root)
    elif action.action == "progress" or action.action == "status":
        return compile_goal_progress(action, agentlab_root)
    elif action.action == "validate":
        return compile_goal_validate(action, agentlab_root)
    elif action.action == "report":
        return compile_goal_report(action, agentlab_root)
    elif action.action in ["pause", "resume", "close"]:
        return GoalCommandResult("ok", [], f"Goal {action.action} action processed.")
    else:
        return GoalCommandResult("error", [], f"Unknown action: {action.action}")
