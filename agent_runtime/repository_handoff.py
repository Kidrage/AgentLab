"""Deterministic repository memory and project handoff generation.

The scanner inventories paths and filesystem/Git metadata across a repository
without bulk-reading file contents. It deliberately ignores dependency caches,
does not follow directory symlinks, and never sends data to a model or network.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit
import os
import re
import subprocess


ROOT_PROJECT_HANDOFF = Path("PROJECT_HANDOFF.md")

# Only PROJECT_HANDOFF.md is writable authority. The remaining paths are
# discovery aliases retained for repositories created under older policies.
HANDOFF_NAMES = (
    ROOT_PROJECT_HANDOFF,
    Path(".agentlab/HandOff.md"),
    Path("agent_docs/HandOff.md"),
    Path("HandOff.md"),
)

# Legacy names that are recognised but not written by AgentLab.
# Must be checked case-insensitively on macOS/APFS.
_HANDOFF_LEGACY_NAMES_LOWER = {"handoff.md"}

IGNORED_DIRS = {
    ".agentlab",
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
}

IGNORED_PATH_PREFIXES = {("memory", "repositories")}

CATEGORIES = {
    "code": {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt", ".swift", ".c", ".cc", ".cpp", ".h", ".hpp", ".rb", ".php", ".sh"},
    "literature": {".md", ".txt", ".rst", ".pdf", ".doc", ".docx", ".epub", ".tex"},
    "image": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".tif", ".tiff", ".heic"},
    "audio": {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".opus"},
    "video": {".mp4", ".mov", ".mkv", ".avi", ".webm"},
    "structured_data": {".json", ".jsonl", ".yml", ".yaml", ".toml", ".csv", ".tsv", ".xml", ".sql", ".parquet"},
    "archive": {".zip", ".tar", ".gz", ".bz2", ".xz", ".7z"},
}

KEY_FILE_NAMES = {
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "Makefile",
    "Dockerfile",
    "docker-compose.yml",
    "compose.yml",
    "requirements.txt",
}

MANUAL_NOTES_START = "<!-- AGENT_NOTES_START -->"
MANUAL_NOTES_END = "<!-- AGENT_NOTES_END -->"


def _run_git(root: Path, args: list[str], *, limit: int = 200_000) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 127, ""
    return result.returncode, result.stdout[:limit]


def _sanitize_remote(value: str) -> str:
    value = value.strip()
    if not value:
        return value
    if "://" not in value:
        return re.sub(r"^[^@\s]+@", "", value)
    parts = urlsplit(value)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def _git_metadata(root: Path) -> dict[str, Any]:
    inside_code, inside = _run_git(root, ["rev-parse", "--is-inside-work-tree"])
    is_git = inside_code == 0 and inside.strip() == "true"
    if not is_git:
        return {"is_git": False, "branch": "not_git", "head": "not_git", "remotes": [], "history": [], "status": []}

    _, branch = _run_git(root, ["branch", "--show-current"])
    _, head = _run_git(root, ["rev-parse", "--short", "HEAD"])
    _, status = _run_git(root, ["status", "--short", "--branch"])
    _, history = _run_git(root, ["log", "--date=short", "--pretty=format:%h %ad %s", "-20"])
    _, remotes = _run_git(root, ["remote", "-v"])
    _, submodules = _run_git(root, ["submodule", "status"])
    remote_lines = []
    for line in remotes.splitlines():
        fields = line.split()
        if len(fields) >= 2:
            remote_lines.append(f"{fields[0]} {_sanitize_remote(fields[1])} {fields[2] if len(fields) > 2 else ''}".strip())
    return {
        "is_git": True,
        "branch": branch.strip() or "detached",
        "head": head.strip() or "unborn",
        "remotes": sorted(set(remote_lines)),
        "history": history.splitlines(),
        "status": status.splitlines(),
        "submodules": submodules.splitlines(),
    }


def _git_paths(root: Path) -> list[Path] | None:
    code, output = _run_git(root, ["ls-files", "-co", "--exclude-standard", "-z"], limit=20_000_000)
    if code != 0:
        return None
    paths = []
    for raw in output.split("\0"):
        if not raw:
            continue
        path = Path(raw)
        absolute = root / path
        if (
            _is_ignored_path(path)
            or absolute.is_symlink()
            or not absolute.is_file()
        ):
            continue
        paths.append(path)
    return sorted(set(paths), key=lambda item: item.as_posix())


def _walk_paths(root: Path, max_paths: int) -> tuple[list[Path], bool]:
    paths: list[Path] = []
    truncated = False
    for current, dirs, files in os.walk(root, followlinks=False):
        relative_current = Path(current).relative_to(root)
        dirs[:] = sorted(
            directory
            for directory in dirs
            if not _is_ignored_path(relative_current / directory)
            and not (Path(current) / directory).is_symlink()
        )
        for filename in sorted(files):
            absolute = Path(current) / filename
            if absolute.is_symlink():
                continue
            try:
                relative = absolute.relative_to(root)
            except ValueError:
                continue
            paths.append(relative)
            if len(paths) >= max_paths:
                truncated = True
                return paths, truncated
    return paths, truncated


def _is_ignored_path(path: Path) -> bool:
    if any(part in IGNORED_DIRS for part in path.parts):
        return True
    return any(path.parts[: len(prefix)] == prefix for prefix in IGNORED_PATH_PREFIXES)


def _category(path: Path) -> str:
    suffix = path.suffix.lower()
    for category, suffixes in CATEGORIES.items():
        if suffix in suffixes:
            return category
    return "other"


def _repository_id(root: Path, git: dict[str, Any]) -> str:
    identity = "|".join(git.get("remotes", [])) or root.name
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", root.name).strip("-.") or "repository"
    return f"{slug}-{sha256(identity.encode('utf-8')).hexdigest()[:12]}"


def _directory_routes(paths: Iterable[Path]) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for path in paths:
        if len(path.parts) == 1:
            counts["."] += 1
        else:
            counts[path.parts[0]] += 1
            if len(path.parts) > 2:
                counts["/".join(path.parts[:2])] += 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:40]


def scan_repository(root: Path, *, max_paths: int = 200_000, examples_per_category: int = 20) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"repository path is not a directory: {root}")

    git = _git_metadata(root)
    paths = _git_paths(root) if git["is_git"] else None
    truncated = False
    if paths is None:
        paths, truncated = _walk_paths(root, max_paths)
    elif len(paths) > max_paths:
        paths = paths[:max_paths]
        truncated = True

    extension_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    category_bytes: Counter[str] = Counter()
    examples: dict[str, list[str]] = {key: [] for key in [*CATEGORIES, "other"]}
    key_files: list[str] = []
    structure_files: list[str] = []
    inaccessible = 0

    for relative in paths:
        absolute = root / relative
        suffix = relative.suffix.lower() or "[no extension]"
        category = _category(relative)
        extension_counts[suffix] += 1
        category_counts[category] += 1
        try:
            category_bytes[category] += absolute.stat().st_size
        except (FileNotFoundError, PermissionError, OSError):
            inaccessible += 1
        if len(examples[category]) < examples_per_category:
            examples[category].append(relative.as_posix())
        if relative.name in KEY_FILE_NAMES or relative.name.lower().startswith("readme"):
            key_files.append(relative.as_posix())
        lowered = relative.as_posix().lower()
        if any(token in lowered for token in ("schema", "model", "migration", "types", "interface", "contract")):
            if len(structure_files) < 80:
                structure_files.append(relative.as_posix())

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "repository_id": _repository_id(root, git),
        "git": git,
        "scan": {
            "method": "path_and_metadata_inventory",
            "content_bulk_read": False,
            "symlink_directories_followed": False,
            "ignored_directories": sorted(IGNORED_DIRS),
            "path_count": len(paths),
            "truncated": truncated,
            "inaccessible_paths": inaccessible,
        },
        "directory_routes": _directory_routes(paths),
        "extension_counts": extension_counts.most_common(40),
        "category_counts": dict(sorted(category_counts.items())),
        "category_bytes": dict(sorted(category_bytes.items())),
        "category_examples": examples,
        "key_files": sorted(set(key_files))[:80],
        "structure_files": sorted(set(structure_files))[:80],
    }


def _extract_manual_notes(existing: str) -> str:
    if MANUAL_NOTES_START not in existing or MANUAL_NOTES_END not in existing:
        return "- Add durable decisions, constraints, or cross-agent context here."
    return existing.split(MANUAL_NOTES_START, 1)[1].split(MANUAL_NOTES_END, 1)[0].strip()


def _bullets(values: Iterable[str], empty: str = "None detected.") -> list[str]:
    values = list(values)
    return [f"- {value}" for value in values] if values else [f"- {empty}"]


def render_handoff(snapshot: dict[str, Any], *, existing: str = "") -> str:
    git = snapshot["git"]
    scan = snapshot["scan"]
    lines = [
        "# Project Handoff",
        "",
        "> Deterministically generated repository/project memory for cross-agent handoff.",
        "> Update after every material project change and before final reporting.",
        "",
        "## Repository Identity",
        "",
        f"- Repository ID: `{snapshot['repository_id']}`",
        "- Working root: `.`",
        f"- Repository name: `{Path(snapshot['root']).name}`",
        f"- Git repository: `{str(git['is_git']).lower()}`",
        f"- Generated at: `{snapshot['generated_at']}`",
        "",
        "## Current State",
        "",
        f"- Branch: `{git['branch']}`",
        f"- HEAD: `{git['head']}`",
        f"- Indexed paths: {scan['path_count']}",
        f"- Inventory truncated: `{str(scan['truncated']).lower()}`",
        f"- Inaccessible paths: {scan['inaccessible_paths']}",
        "- Scan mode: complete path/metadata inventory; no bulk content read; no symlink traversal.",
        "",
        "## Project Progress Dashboard",
        "",
        "- Current progress: derive from branch, HEAD, current changes, and manual Agent Notes below.",
        "- Work already changed: see Change History and Current Changes.",
        "- Active work: any dirty Git status entries listed under Current Changes.",
        "- Remaining work / ETA: maintain in Agent Notes when it cannot be inferred deterministically.",
        "- Pending decisions: maintain in Agent Notes and refresh before final reporting.",
        "- Pending files / plans / acceptance artifacts: maintain in Agent Notes and task run ledgers.",
        "- Fast reporting source: this canonical root file; use the shared mirror only when explicitly written.",
        "",
        "## Active Work and Pending Items",
        "",
        "- In progress: inspect Current Changes and Agent Notes.",
        "- Pending decisions: record durable choices in Agent Notes before handoff.",
        "- Pending files to modify: record intended paths in Agent Notes before dispatch.",
        "- Pending plans to confirm: link task/run plans in Agent Notes.",
        "- Pending acceptance artifacts: link deliverables and validation evidence in Agent Notes.",
        "- Next safe entry point: run `./agentlab.sh repository-handoff --repo <path>` before deep work.",
        "",
        "## Directory Routes",
        "",
        "| Route | Files |",
        "|---|---:|",
    ]
    lines.extend(f"| `{route}` | {count} |" for route, count in snapshot["directory_routes"])
    lines.extend(["", "## Data and File Structure", "", "### Categories", ""])
    for category, count in snapshot["category_counts"].items():
        size = snapshot["category_bytes"].get(category, 0)
        lines.append(f"- {category}: {count} files, {size} bytes")
    lines.extend(["", "### Common Extensions", ""])
    lines.extend(f"- `{suffix}`: {count}" for suffix, count in snapshot["extension_counts"])
    lines.extend(["", "### Schema / Model / Interface Candidates", ""])
    lines.extend(_bullets(f"`{value}`" for value in snapshot["structure_files"]))
    lines.extend(["", "## Key Entrypoints and Guides", ""])
    lines.extend(_bullets(f"`{value}`" for value in snapshot["key_files"]))
    lines.extend(["", "## Change History", ""])
    lines.extend(_bullets((f"`{value}`" for value in git["history"]), "No Git history detected."))
    lines.extend(["", "## Current Changes", ""])
    lines.extend(_bullets((f"`{value}`" for value in git["status"]), "Working tree clean or not a Git repository."))
    lines.extend(["", "## Related Repositories", "", "### Remotes", ""])
    lines.extend(_bullets(f"`{value}`" for value in git["remotes"]))
    lines.extend(["", "### Submodules", ""])
    lines.extend(_bullets(f"`{value}`" for value in git.get("submodules", [])))
    lines.extend(["", "## Media and Literature Routes", ""])
    for category in ("literature", "image", "audio", "video", "structured_data"):
        values = snapshot["category_examples"].get(category, [])
        lines.append(f"### {category}")
        lines.append("")
        lines.extend(_bullets(f"`{value}`" for value in values))
        lines.append("")
    lines.extend([
        "## Validation and Risks",
        "",
        "- This inventory records paths and metadata, not semantic correctness.",
        "- Binary/media payloads and secrets were not read.",
        "- Validate current branch, tests, and interfaces before modifying files.",
        "",
        "## Agent Notes",
        "",
        MANUAL_NOTES_START,
        _extract_manual_notes(existing),
        MANUAL_NOTES_END,
        "",
        "## Mandatory Update Rule",
        "",
        "Refresh canonical PROJECT_HANDOFF.md after branch, commit, file, directory, schema, interface,",
        "related-repository, or material project-state changes, and before final handoff.",
        "",
    ])
    return "\n".join(lines)


def _iterdir_lower_map(dir_path: Path) -> dict[str, Path]:
    """Return a dict mapping lowercase name → actual Path for entries in *dir_path*."""
    try:
        return {entry.name.lower(): entry for entry in dir_path.iterdir()}
    except OSError:
        return {}


def discover_handoff(root: Path, shared_memory_root: Path | None = None) -> Path | None:
    root = Path(root).expanduser().resolve()
    # Build a case-insensitive index of root-level files (one directory listing)
    root_index = _iterdir_lower_map(root)
    for relative in HANDOFF_NAMES:
        # Fast path: direct parent check handles nested paths and simple files
        candidate = root / relative
        if candidate.is_file():
            # On case-insensitive filesystems, resolve to actual on-disk case.
            # The top-level check uses the pre-built index; nested paths
            # (e.g. .agentlab/HandOff.md) fall back to plain iterdir.
            parent = candidate.parent
            if parent == root and candidate.name.lower() in root_index:
                return root_index[candidate.name.lower()]
            # For nested paths, do a one-off iterdir for case accuracy
            nested_index = _iterdir_lower_map(parent)
            if candidate.name.lower() in nested_index:
                return nested_index[candidate.name.lower()]
            return candidate
    # Legacy case-insensitive names (e.g. HANDOFF.md)
    if root_index:
        for entry_lower, entry_path in root_index.items():
            if entry_lower in _HANDOFF_LEGACY_NAMES_LOWER and entry_path.is_file():
                return entry_path
    if shared_memory_root:
        snapshot = scan_repository(root, max_paths=1)
        candidate = Path(shared_memory_root) / snapshot["repository_id"] / "HandOff.md"
        if candidate.is_file():
            return candidate
    return None


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def update_handoffs(
    root: Path,
    shared_memory_root: Path,
    *,
    write_shared_copy: bool = False,
) -> dict[str, Any]:
    """Refresh canonical repository memory and optionally its shared fallback.

    Legacy local aliases remain readable through ``discover_handoff`` but are
    never rewritten. A shared copy is written only when explicitly requested or
    when the canonical repository path is not writable.
    """
    root = Path(root).expanduser().resolve()
    shared_memory_root = Path(shared_memory_root).expanduser().resolve()
    existing_path = discover_handoff(root, shared_memory_root)
    snapshot = scan_repository(root)
    root_path = root / ROOT_PROJECT_HANDOFF
    shared_path = shared_memory_root / snapshot["repository_id"] / "HandOff.md"

    existing = ""
    if existing_path:
        try:
            existing = existing_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            existing = ""
    content = render_handoff(snapshot, existing=existing)

    written: list[str] = []
    canonical_error = ""
    try:
        _atomic_write(root_path, content)
        written.append(str(root_path))
    except OSError as exc:
        canonical_error = str(exc)

    shared_copy_reason = None
    if write_shared_copy or canonical_error:
        _atomic_write(shared_path, content)
        written.append(str(shared_path))
        shared_copy_reason = (
            "canonical_write_fallback" if canonical_error else "explicit_request"
        )

    legacy_paths = [
        str(root / relative)
        for relative in HANDOFF_NAMES[1:]
        if (root / relative).is_file()
    ]
    return {
        "repository_id": snapshot["repository_id"],
        "handoff_paths": written,
        "canonical_handoff_path": str(root_path) if not canonical_error else None,
        "source_handoff_path": str(existing_path) if existing_path else None,
        "legacy_handoff_paths": legacy_paths,
        "shared_handoff_path": str(shared_path) if shared_copy_reason else None,
        "shared_copy_written": shared_copy_reason is not None,
        "shared_copy_reason": shared_copy_reason,
        "local_write_error": canonical_error or None,
        "path_count": snapshot["scan"]["path_count"],
        "truncated": snapshot["scan"]["truncated"],
    }
