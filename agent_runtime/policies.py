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


import re

_TASK_ID_RE = re.compile(r"^task_\d{4}(_[a-z][a-z0-9_-]{0,48}[a-z0-9])?$")


def ensure_safe_task_id(task_id: str) -> str:
    """Accept task_NNNN or task_NNNN_slug-name for human-readable task ids.

    Examples: task_0001, task_0013_truenas-integration, task_0042_cloud-deploy-v2
    """
    if not _TASK_ID_RE.match(task_id):
        raise ValueError(
            "Task id must be: task_0001 or task_0001_slug-name "
            "(4-digit number, optional _slug with lowercase letters, digits, hyphens, underscores, max 50 chars)"
        )
    return task_id


def task_number(task_id: str) -> int:
    """Extract the numeric portion of a task id."""
    return int(task_id.split("_")[1])


def task_slug(task_id: str) -> str:
    """Extract the human-readable slug, or empty string."""
    parts = task_id.split("_", 2)
    return parts[2] if len(parts) >= 3 else ""


def generate_slug_from_request(request_text: str) -> str:
    """Generate a compact slug from user request text."""
    import re as _re
    # Take first meaningful line, limit to ~50 chars slug
    text = (request_text or "").strip()
    # Remove markdown headings
    text = _re.sub(r"^#+\s*", "", text)
    # Replace non-alphanumeric with space
    text = _re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff\s-]", " ", text)
    # First pass: try English keywords
    en_words = _re.findall(r"[a-zA-Z]{3,}", text)
    if en_words:
        slug = "-".join(w.lower() for w in en_words[:6])
        return slug[:50].strip("-")
    # Fallback: Chinese + English mixed
    all_tokens = [t.strip() for t in text.split() if t.strip() and len(t.strip()) >= 2]
    if not all_tokens:
        return ""
    # Use first few tokens, limit
    raw = "-".join(all_tokens[:5])
    raw = _re.sub(r"[^a-z0-9-]", "", raw.lower())
    return raw[:50].strip("-")


def resolve_agentlab_root(path: Path) -> Path:
    """Normalize configured AgentLab roots for Phase 2A tools."""
    root = path.expanduser().resolve()
    if root.name == "agent_runtime":
        return root.parent
    if not (root / "projects").exists() and (root.parent / "projects").exists():
        return root.parent
    return root


def assert_path_allowed(path: Path, allowed_root: Path, extra_roots: list[Path] | None = None) -> Path:
    root = allowed_root.resolve()
    target = path.resolve()

    allowed_roots = [root]
    for extra_root in extra_roots or []:
        allowed_roots.append(extra_root.expanduser().resolve())

    if not any(candidate in (target, *target.parents) for candidate in allowed_roots):
        raise ValueError(f"Path is outside allowed root: {target}")
    if target.name in FORBIDDEN_FILENAMES:
        raise ValueError(f"Refusing to access forbidden file: {target.name}")
    if any(part in FORBIDDEN_PATH_PARTS for part in target.parts):
        raise ValueError(f"Refusing to access forbidden path: {target}")

    return target


def ensure_dir_safe(path: Path, label: str = "directory") -> Path:
    """Create or verify a directory, handling symlinks gracefully.

    - If path exists and is a directory: pass
    - If path is a symlink pointing to an existing directory: pass
    - If path is a symlink pointing to missing target: error with clear message
    - If path exists but is not a directory: error
    - If path does not exist: create with parents
    """
    p = path.expanduser()

    if p.exists():
        if p.is_dir():
            return p
        if p.is_symlink():
            target = p.resolve(strict=False)
            if target.exists() and target.is_dir():
                return p
            raise RuntimeError(
                f"{label} is a symlink but target is missing or not a directory: "
                f"{p} -> {target}. Mount the target or configure an alternate path."
            )
        raise RuntimeError(f"{label} exists but is not a directory: {p}")

    p.mkdir(parents=True, exist_ok=True)
    return p
