"""Path and identifier policy helpers for local AgentLab runtime code."""

from __future__ import annotations

from pathlib import Path
import re


SAFE_TASK_ID_RE = re.compile(r"^task_[A-Za-z0-9][A-Za-z0-9_-]{0,80}$")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_agentlab_root(start: str | Path | None = None) -> Path:
    """Resolve the AgentLab repository root from *start* or this file."""
    current = Path(start).resolve() if start is not None else Path(__file__).resolve()
    if current.is_file():
        current = current.parent
    for candidate in [current, *current.parents]:
        if (candidate / "agentlab.sh").exists() and (candidate / "agent_runtime").is_dir():
            return candidate
    return Path(__file__).resolve().parents[1]


def assert_path_allowed(
    path: str | Path,
    allowed_root: str | Path | None = None,
    *,
    extra_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
) -> Path:
    """Return a resolved path if it stays inside allowed roots.

    Raises ``ValueError`` on escape instead of returning a boolean. This is the
    contract used by runtime modules that build task/run paths before writing.
    """
    root = Path(allowed_root).resolve() if allowed_root is not None else resolve_agentlab_root()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    roots = [root, *[Path(item).resolve() for item in (extra_roots or [])]]
    if any(_is_relative_to(resolved, item) for item in roots):
        return resolved
    raise ValueError(f"path escapes allowed roots: {resolved}")


def assert_file_allowed(file_path: str | Path, allowed_root: str | Path | None = None) -> Path:
    """Return an allowed file path. Kept as a compatibility alias."""
    return assert_path_allowed(file_path, allowed_root)


def ensure_dir_safe(path: str | Path, label: str = "directory", allowed_root: str | Path | None = None) -> Path:
    """Create an allowed directory and return its resolved path."""
    resolved = assert_path_allowed(path, allowed_root)
    if resolved.exists() and not resolved.is_dir():
        raise ValueError(f"{label} exists but is not a directory: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def ensure_safe_task_id(task_id: str) -> str:
    if not SAFE_TASK_ID_RE.match(str(task_id or "")):
        raise ValueError(f"unsafe task_id: {task_id}")
    return task_id


def task_number(task_id: str) -> int | None:
    match = re.search(r"task_(\d+)", str(task_id or ""))
    return int(match.group(1)) if match else None


def generate_slug_from_request(text: str, *, max_length: int = 48) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    return (slug or "task")[:max_length].strip("-") or "task"


def get_allowed_paths() -> dict:
    root = resolve_agentlab_root()
    return {
        "cwd": str(Path.cwd()),
        "project_dir": str(root),
        "allowed_patterns": [
            "projects/AgentLab/**",
            "config/**",
            "agent_runtime/**",
            "docs/**",
            "tests/**",
        ],
    }
