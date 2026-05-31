"""AgentLab Terminal Chat Router — intent routing + slash commands.

Supports Task Discovery commands:
/find, /resume-list, /attach, /open-task, /task-map, /artifacts, /summarize-task
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class ChatIntent:
    """Chat intent constants."""
    # Existing
    NEW_TASK = "new_task"
    RUN_AGENT = "run_agent"
    STATUS = "status"
    HELP = "help"
    PIPELINE = "pipeline"
    EXIT = "exit"
    # Task Discovery
    FIND_TASK = "find_task"
    RESUME_LIST = "resume_list"
    OPEN_TASK = "open_task"
    ATTACH_RESULT = "attach_result"
    TASK_MAP = "task_map"
    ARTIFACTS = "artifacts"
    SUMMARIZE_TASK = "summarize_task"


@dataclass
class ParsedIntent:
    intent: str
    payload: dict = field(default_factory=dict)
    raw: str = ""


_KNOWN_COMMANDS = {
    "/find": ChatIntent.FIND_TASK,
    "/resume-list": ChatIntent.RESUME_LIST,
    "/attach": ChatIntent.ATTACH_RESULT,
    "/open-task": ChatIntent.OPEN_TASK,
    "/task-map": ChatIntent.TASK_MAP,
    "/artifacts": ChatIntent.ARTIFACTS,
    "/summarize-task": ChatIntent.SUMMARIZE_TASK,
    "/status": ChatIntent.STATUS,
    "/help": ChatIntent.HELP,
    "/exit": ChatIntent.EXIT,
    "/quit": ChatIntent.EXIT,
    "/pipeline": ChatIntent.PIPELINE,
    "/new": ChatIntent.NEW_TASK,
}

_NEW_TASK_KEYWORDS = [
    "create task", "new task", "start task", "新任务", "创建任务",
    "开始任务", "帮我做", "帮我写", "帮我改", "帮我分析", "帮我设计",
]

_STATUS_KEYWORDS = [
    "task status", "show status", "what is current", "当前状态",
    "查看状态", "进度", "任务状态",
]


def parse_intent(text: str, project: str = "", active_task_id: Optional[str] = None) -> ParsedIntent:
    """Parse a chat message into an intent.

    Args:
        text: User message text.
        project: Current project name.
        active_task_id: Currently attached task ID.

    Returns:
        A ParsedIntent with intent type and parsed payload.
    """
    text = text.strip()

    # Slash commands
    if text.startswith("/"):
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        rest = parts[1].strip() if len(parts) > 1 else ""

        intent_type = _KNOWN_COMMANDS.get(cmd)
        if intent_type is None:
            return ParsedIntent(intent=ChatIntent.HELP, payload={"message": f"Unknown command: {cmd}"}, raw=text)

        payload = {}
        if intent_type == ChatIntent.FIND_TASK:
            payload["query"] = rest
        elif intent_type in (ChatIntent.ATTACH_RESULT, ChatIntent.OPEN_TASK):
            payload["target"] = rest  # can be task_id or result number

        return ParsedIntent(intent=intent_type, payload=payload, raw=text)

    # Keyword-based intent detection
    text_lower = text.lower()

    for kw in _NEW_TASK_KEYWORDS:
        if kw in text_lower:
            return ParsedIntent(intent=ChatIntent.NEW_TASK, payload={"request": text}, raw=text)

    for kw in _STATUS_KEYWORDS:
        if kw in text_lower:
            return ParsedIntent(intent=ChatIntent.STATUS, payload={}, raw=text)

    # Default: treat as potential new task or fallback
    return ParsedIntent(intent=ChatIntent.NEW_TASK, payload={"request": text}, raw=text)