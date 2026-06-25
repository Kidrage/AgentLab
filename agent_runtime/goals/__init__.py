"""Goal / Mainline Command Bridge (M2-12.5).

Deterministic, local-only goal parsing, compilation, validation, and reporting.
No LLM calls, no shell execution, no network calls, no external executor dispatch.
"""

from agent_runtime.goals.parser import GoalActionSchema, parse_goal_command
from agent_runtime.goals.compiler import (
    compile_goal_plan,
    compile_goal_progress,
    compile_goal_report,
    compile_goal_set,
    compile_goal_validate,
)
from agent_runtime.goals.templates import TEMPLATES, get_template
from agent_runtime.goals.validation import validate_goal_acceptance

__all__ = [
    "GoalActionSchema",
    "parse_goal_command",
    "compile_goal_set",
    "compile_goal_plan",
    "compile_goal_progress",
    "compile_goal_validate",
    "compile_goal_report",
    "TEMPLATES",
    "get_template",
    "validate_goal_acceptance",
]
