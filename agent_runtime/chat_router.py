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
    ATTACH_TASK = "attach_task"
    RUN_AGENT = "run_agent"
    RUN_NEXT = "run_next"
    STATUS = "status"
    PROGRESS = "progress"
    PLAN = "plan"
    CHECK = "check"
    SYNC = "sync"
    PAUSE = "pause"
    RESUME = "resume"
    PROVIDERS = "providers"
    MODELS = "models"
    OPEN_PATH = "open_path"
    FOLLOWUP = "followup"
    HELP = "help"
    PIPELINE = "pipeline"
    EXIT = "exit"
    UNKNOWN = "unknown"
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
    "/task": ChatIntent.ATTACH_TASK,
    "/progress": ChatIntent.PROGRESS,
    "/plan": ChatIntent.PLAN,
    "/run": ChatIntent.RUN_AGENT,
    "/run-next": ChatIntent.RUN_NEXT,
    "/check": ChatIntent.CHECK,
    "/push": ChatIntent.SYNC,
    "/sync": ChatIntent.SYNC,
    "/pause": ChatIntent.PAUSE,
    "/resume": ChatIntent.RESUME,
    "/providers": ChatIntent.PROVIDERS,
    "/models": ChatIntent.MODELS,
    "/open": ChatIntent.OPEN_PATH,
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


def parse_input(text: str, has_active_task: bool = False) -> tuple[str, str]:
    """Compatibility parser used by terminal_chat.

    Returns the older `(intent, payload_string)` shape while sharing the same
    command table as `parse_intent`.
    """
    raw = text.strip()
    if not raw:
        return ChatIntent.UNKNOWN, ""

    if raw.startswith("/"):
        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower()
        rest = parts[1].strip() if len(parts) > 1 else ""
        intent = _KNOWN_COMMANDS.get(cmd)
        if intent is None:
            return ChatIntent.UNKNOWN, raw
        return intent, rest

    if has_active_task:
        return ChatIntent.FOLLOWUP, raw
    return ChatIntent.NEW_TASK, raw
