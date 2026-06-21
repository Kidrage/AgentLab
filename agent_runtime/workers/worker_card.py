"""Worker card models and categories for AgentLab."""

from dataclasses import dataclass, field, asdict
from typing import Optional, Any

class WorkerCategory:
    CODING_AGENT = "coding_agent"
    PLANNING_AGENT = "planning_agent"
    FRONTDESK_AGENT = "frontdesk_agent"
    MULTIMODAL_CLOUD_TOOL = "multimodal_cloud_tool"
    RESEARCH_TOOL = "research_tool"
    DETERMINISTIC_REPO_TOOL = "deterministic_repo_tool"
    DETERMINISTIC_AST_TOOL = "deterministic_ast_tool"
    TEST_RUNNER = "test_runner"
    LINTER = "linter"
    FORMATTER = "formatter"
    SHELL_TOOL = "shell_tool"
    VCS_TOOL = "vcs_tool"
    CONTAINER_TOOL = "container_tool"
    UNKNOWN = "unknown"

@dataclass
class WorkerCard:
    worker_id: str
    display_name: str
    command: str
    installed: bool = False
    version: Optional[str] = None
    authenticated: str = "unknown"  # "yes" | "no" | "unknown"
    category: str = WorkerCategory.UNKNOWN
    source: str = "local_cli"
    can_read_files: bool = True
    can_edit_files: bool = True
    can_run_shell: bool = True
    can_access_network: str = "unknown"  # "yes" | "no" | "unknown"
    can_upload_files: str = "unknown"
    interactive: bool = True
    supports_noninteractive_task: str = "unknown"
    supports_mcp: str = "unknown"
    supports_long_context: str = "unknown"
    cost_tier: str = "medium"  # "free" | "low" | "medium" | "high"
    risk_level: str = "medium"  # "low" | "medium" | "high"
    default_enabled: bool = False
    approval_required: bool = True
    best_for: list[str] = field(default_factory=list)
    avoid_for: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkerCard":
        return cls(**data)
