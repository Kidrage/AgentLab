"""AgentLab Phase 2A policy placeholders."""

from pathlib import Path

FORBIDDEN_COMMAND_PREFIXES = (
    "pip",
    "npm",
    "brew",
    "apt",
    "rm -rf",
    "git reset --hard",
    "git checkout --",
)

FORBIDDEN_FILENAMES = {".env"}
FORBIDDEN_PATH_PARTS = {".venv", "node_modules", "__pycache__"}


def is_forbidden_command(command: str) -> bool:
    normalized = command.strip().lower()
    return any(normalized.startswith(prefix) for prefix in FORBIDDEN_COMMAND_PREFIXES)


def ensure_safe_task_id(task_id: str) -> str:
    allowed = task_id.startswith("task_") and task_id.replace("task_", "", 1).isdigit()
    if not allowed:
        raise ValueError("Task id must look like task_0001")
    return task_id


def resolve_agentlab_root(path: Path) -> Path:
    """Normalize configured AgentLab roots for Phase 2A tools."""
    root = path.expanduser().resolve()
    if root.name == "agent_runtime":
        return root.parent
    if not (root / "projects").exists() and (root.parent / "projects").exists():
        return root.parent
    return root


def assert_path_allowed(path: Path, allowed_root: Path) -> Path:
    root = allowed_root.resolve()
    target = path.resolve()

    if root not in (target, *target.parents):
        raise ValueError(f"Path is outside allowed root: {target}")
    if target.name in FORBIDDEN_FILENAMES:
        raise ValueError(f"Refusing to access forbidden file: {target.name}")
    if any(part in FORBIDDEN_PATH_PARTS for part in target.parts):
        raise ValueError(f"Refusing to access forbidden path: {target}")

    return target
