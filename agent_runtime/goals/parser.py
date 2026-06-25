from typing import Optional, Tuple
from agent_runtime.goals.action_schema import GoalActionSchema
from agent_runtime.goals.aliases import resolve_action, ENGLISH_ALIASES, CHINESE_ALIASES

def parse_goal_command(raw_text: str, project: str = "AgentLab", source: str = "cli") -> GoalActionSchema:
    raw_text = raw_text.strip()
    if not raw_text:
        return GoalActionSchema(status="error", blocking_reasons=["Empty command"])

    if raw_text == "/goal":
        return GoalActionSchema(action="status", project=project, source=source, language="en")
    elif raw_text == "/目标":
        return GoalActionSchema(action="status", project=project, source=source, language="zh", command="/目标")

    prefix = ""
    if raw_text.startswith("/goal "):
        prefix = "/goal "
    elif raw_text.startswith("/目标 "):
        prefix = "/目标 "
    else:
        # Check short aliases e.g. /计划
        if raw_text.startswith("/"):
            short_alias = raw_text[1:].strip()
            if short_alias in CHINESE_ALIASES:
                return GoalActionSchema(
                    command="/目标",
                    action=CHINESE_ALIASES[short_alias],  # type: ignore
                    project=project,
                    source=source,
                    language="zh"
                )
            elif short_alias in ENGLISH_ALIASES:
                return GoalActionSchema(
                    command="/goal",
                    action=ENGLISH_ALIASES[short_alias],  # type: ignore
                    project=project,
                    source=source,
                    language="en"
                )
        return GoalActionSchema(status="error", blocking_reasons=["Unknown command format"])

    content = raw_text[len(prefix):].strip()
    command = prefix.strip()
    
    parts = content.split(" ", 1)
    action_cand = parts[0]
    
    action, lang = resolve_action(action_cand)
    text = ""
    
    if action in ENGLISH_ALIASES.values():
        if len(parts) > 1:
            text = parts[1].strip()
    else:
        # Default to set
        action = "set"
        lang = "en" if command == "/goal" else "zh"
        text = content
        
    return GoalActionSchema(
        command=command,
        action=action, # type: ignore
        project=project,
        source=source,
        text=text,
        language=lang
    )
