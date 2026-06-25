from dataclasses import dataclass, field
from typing import List, Literal, Optional

@dataclass
class GoalActionSchema:
    command: str = "/goal"
    action: Literal["set", "plan", "status", "progress", "validate", "report", "pause", "resume", "close"] = "set"
    source: str = "cli"
    project: str = "AgentLab"
    text: str = ""
    goal_id: str = ""
    language: Literal["en", "zh"] = "en"
    created_artifacts: List[str] = field(default_factory=list)
    next_action: str = ""
    status: Literal["ok", "blocked", "error"] = "ok"
    blocking_reasons: List[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "command": self.command,
            "action": self.action,
            "source": self.source,
            "project": self.project,
            "text": self.text,
            "goal_id": self.goal_id,
            "language": self.language,
            "created_artifacts": self.created_artifacts,
            "next_action": self.next_action,
            "status": self.status,
            "blocking_reasons": self.blocking_reasons,
        }
