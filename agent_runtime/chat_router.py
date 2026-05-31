"""Rule-based chat intent parser for AgentLab Terminal chat.

Parses user input into a deterministic ChatIntent without calling any LLM.
Slash commands always win. Free-text becomes NEW_TASK or FOLLOWUP.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Optional


class ChatIntent(StrEnum):
    NEW_TASK = "new_task"
    ATTACH_TASK = "attach_task"
    STATUS = "status"
    PROGRESS = "progress"
    PLAN = "plan"
    RUN_AGENT = "run_agent"
    RUN_NEXT = "run_next"
    CHECK = "check"
    SYNC = "sync"
    PAUSE = "pause"
    RESUME = "resume"
    PROVIDERS = "providers"
    MODELS = "models"
    OPEN_PATH = "open_path"
    HELP = "help"
    EXIT = "exit"
    FOLLOWUP = "followup"
    UNKNOWN = "unknown"


_SLASH_COMMANDS = {
    "/help": (ChatIntent.HELP, None),
    "/status": (ChatIntent.STATUS, None),
    "/progress": (ChatIntent.PROGRESS, None),
    "/plan": (ChatIntent.PLAN, None),
    "/run-next": (ChatIntent.RUN_NEXT, None),
    "/check": (ChatIntent.CHECK, None),
    "/push": (ChatIntent.SYNC, None),
    "/sync": (ChatIntent.SYNC, None),
    "/pause": (ChatIntent.PAUSE, None),
    "/resume": (ChatIntent.RESUME, None),
    "/providers": (ChatIntent.PROVIDERS, None),
    "/models": (ChatIntent.MODELS, None),
    "/open": (ChatIntent.OPEN_PATH, None),
    "/exit": (ChatIntent.EXIT, None),
    "/quit": (ChatIntent.EXIT, None),
}

_TASK_RE = re.compile(r"task_\d{4}[\w\-]*")


def parse_input(text: str, *, has_active_task: bool = False) -> tuple[ChatIntent, Optional[str]]:
    """Parse user input and return (intent, optional_payload).

    Slash commands always win. Non-slash text becomes NEW_TASK
    (no active task) or FOLLOWUP (active task exists).
    """
    stripped = text.strip()

    # Empty input
    if not stripped:
        return (ChatIntent.UNKNOWN, None)

    # Slash commands
    # /run <AgentName>
    run_match = re.match(r"^/run\s+(.+)$", stripped, re.IGNORECASE)
    if run_match:
        return (ChatIntent.RUN_AGENT, run_match.group(1).strip())

    # /task <task_id>
    task_match = re.match(r"^/task\s+(.+)$", stripped, re.IGNORECASE)
    if task_match:
        task_val = task_match.group(1).strip()
        return (ChatIntent.ATTACH_TASK, task_val)

    # /new <text>
    new_match = re.match(r"^/new\s+(.+)$", stripped, re.IGNORECASE)
    if new_match:
        return (ChatIntent.NEW_TASK, new_match.group(1).strip())

    # Exact slash commands
    if stripped in _SLASH_COMMANDS:
        intent, _ = _SLASH_COMMANDS[stripped]
        return (intent, None)

    # Plain text — no slash → NEW_TASK or FOLLOWUP
    if not has_active_task:
        return (ChatIntent.NEW_TASK, stripped)
    return (ChatIntent.FOLLOWUP, stripped)