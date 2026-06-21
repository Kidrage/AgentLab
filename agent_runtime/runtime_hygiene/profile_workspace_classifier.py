"""Classifier for runtime profiles and workspaces."""

from pathlib import Path
from enum import Enum

class ProfileClass(str, Enum):
    CLAUDE = "claude"
    CODEX = "codex"
    QWEN = "qwen"
    HERMES = "hermes"
    GEMINI = "gemini"
    BAILIAN = "bailian"
    OPENCLAW = "openclaw"
    UNKNOWN = "unknown"

class WorkspaceClass(str, Enum):
    CLAUDE = "claude"
    CODEX = "codex"
    QWEN = "qwen"
    HERMES = "hermes"
    OPENCLAW = "openclaw"
    GENERIC_CLI = "generic_cli"
    UNKNOWN = "unknown"

def classify_entry(path: str | Path) -> tuple[str, ProfileClass | WorkspaceClass | None]:
    """Classify a path under .agents/ into profile or workspace category."""
    p = Path(path).resolve()
    
    # Check if under .agents/profiles/
    if "profiles" in p.parts:
        idx = p.parts.index("profiles")
        if idx + 1 < len(p.parts):
            sub = p.parts[idx + 1].lower()
            try:
                return "profile", ProfileClass(sub)
            except ValueError:
                return "profile", ProfileClass.UNKNOWN
        return "profile", None
        
    # Check if under .agents/workspaces/
    if "workspaces" in p.parts:
        idx = p.parts.index("workspaces")
        if idx + 1 < len(p.parts):
            sub = p.parts[idx + 1].lower()
            try:
                return "workspace", WorkspaceClass(sub)
            except ValueError:
                return "workspace", WorkspaceClass.UNKNOWN
        return "workspace", None
        
    return "unknown", None
