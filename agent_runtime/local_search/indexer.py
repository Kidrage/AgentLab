"""File indexer for the local search module.

Recursively walks directories, reads text files, redacts secrets and
local paths, and produces a list of Document objects for the index.
"""

from __future__ import annotations

import fnmatch
import os
import re
import warnings
from pathlib import Path

from .document import Document, SourceCategory, content_hash_of

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_FILE_SIZE = 1_048_576  # 1 MB

DEFAULT_EXCLUDE_DIRS: set[str] = {
    ".venv",
    "venv",
    "__pycache__",
    ".git",
    "node_modules",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    ".eggs",
    "*.egg-info",
    ".agentlab_runtime",
    ".tmp_agent_docs",
}

# Regex that matches local absolute home-dir paths and replaces them with <HOME>.
_HOME_PATH_RE = re.compile(r"/(?:Users|home)/[^/\s\"']+")

# Patterns that look like secret assignments.  We skip lines where an
# identifier containing one of these keywords is *assigned* a non-empty
# literal value (not a variable reference or placeholder).
_SECRET_KEYWORDS = ("api_key", "secret", "password", "token", "passwd", "api_secret")
_SECRET_LINE_RE = re.compile(
    r"""^\s*[A-Za-z_]*(?:""" + "|".join(_SECRET_KEYWORDS) + r""")[A-Za-z_]*\s*[=:]\s*['"][^'"]{4,}['"]""",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Source directory configuration for build_index
# ---------------------------------------------------------------------------

SOURCE_DIRS: dict[str, dict] = {
    "repo_files": {
        "paths": ["agent_runtime"],
        "suffixes": {".py", ".md", ".sh"},
    },
    "docs": {
        "paths": ["docs"],
        "suffixes": {".md"},
    },
    "config": {
        "paths": ["config"],
        "suffixes": {".yml", ".yaml"},
    },
    "skills": {
        "paths": ["agent_runtime/skills"],
        "suffixes": {".py"},
    },
    "tests": {
        "paths": ["tests"],
        "suffixes": {".py"},
    },
    "scripts": {
        "paths": ["scripts"],
        "suffixes": {".py", ".sh"},
    },
    "acceptance_runs": {
        "paths": ["acceptance_runs"],
        "suffixes": {".md", ".yml", ".yaml"},
    },
    "recovery_history": {
        "paths": ["projects"],
        "suffixes": {".jsonl", ".json"},
        "subdir_pattern": "*/runs/*/recovery*",
    },
    "closure_feedback": {
        "paths": ["projects"],
        "suffixes": {".json", ".md"},
        "subdir_pattern": "*/runs/*/closure*",
    },
    "project_brain": {
        "paths": ["projects"],
        "suffixes": {".md", ".yml"},
        "subdir_pattern": "*/project_brain/*",
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_excluded_dir(name: str) -> bool:
    """Return True if the directory name matches an exclude pattern."""
    for pat in DEFAULT_EXCLUDE_DIRS:
        if fnmatch.fnmatch(name, pat):
            return True
    return False


def _is_binary(data: bytes) -> bool:
    """Heuristic: file is binary if it contains null bytes."""
    return b"\x00" in data


def _redact_paths(text: str) -> str:
    """Replace local home-dir paths with <HOME>."""
    return _HOME_PATH_RE.sub("<HOME>", text)


def _redact_secrets(text: str) -> str:
    """Remove lines that look like secret assignments."""
    lines = text.split("\n")
    kept: list[str] = []
    for line in lines:
        if _SECRET_LINE_RE.search(line):
            kept.append("[REDACTED]")
        else:
            kept.append(line)
    return "\n".join(kept)


def _matches_subdir_pattern(rel_path: str, subdir_pattern: str | None) -> bool:
    """Check whether a relative path matches an optional subdir glob."""
    if subdir_pattern is None:
        return True
    return fnmatch.fnmatch(rel_path, subdir_pattern)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def index_directory(
    root: Path,
    source_category: str,
    suffixes: set[str],
    exclude_dirs: set[str] | None = None,
    subdir_pattern: str | None = None,
) -> list[Document]:
    """Recursively index files under *root* that match *suffixes*.

    Files in directories matching *exclude_dirs* (or the built-in defaults)
    are skipped.  Binary files and files larger than MAX_FILE_SIZE are also
    skipped.
    """
    if exclude_dirs is None:
        exclude_dirs = DEFAULT_EXCLUDE_DIRS

    if not root.is_dir():
        warnings.warn(f"index_directory: path does not exist or is not a dir: {root}")
        return []

    documents: list[Document] = []

    for dirpath_str, dirnames, filenames in os.walk(root):
        # Prune excluded directories in-place.
        dirnames[:] = [
            d for d in dirnames if not _is_excluded_dir(d) and d not in exclude_dirs
        ]

        dirpath = Path(dirpath_str)
        for fname in sorted(filenames):
            fpath = dirpath / fname

            # Suffix filter
            if fpath.suffix not in suffixes:
                continue

            # Size filter
            try:
                size = fpath.stat().st_size
            except OSError:
                continue
            if size > MAX_FILE_SIZE:
                continue

            # Read and decode
            try:
                raw = fpath.read_bytes()
            except OSError:
                continue
            if _is_binary(raw):
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue

            # Redact
            text = _redact_paths(text)
            text = _redact_secrets(text)

            # Subdir pattern (relative to root)
            rel = str(fpath.relative_to(root))
            if not _matches_subdir_pattern(rel, subdir_pattern):
                continue

            doc = Document.from_file(
                rel_path=rel,
                text=text,
                source_category=source_category,
                size_bytes=size,
            )
            documents.append(doc)

    return documents


def build_index(
    root: Path,
    config: dict | None = None,
) -> list[Document]:
    """Build a full index by walking configured source directories.

    *config* may override entries in SOURCE_DIRS.  Each key maps to a dict
    with at least ``paths`` and ``suffixes``, and optionally
    ``subdir_pattern`` and ``exclude_dirs``.
    """
    source_map = SOURCE_DIRS
    if config is not None:
        source_map = {**SOURCE_DIRS, **config}

    all_docs: list[Document] = []

    for category, spec in source_map.items():
        paths = spec.get("paths", [])
        suffixes = set(spec.get("suffixes", set()))
        subdir_pattern = spec.get("subdir_pattern")
        extra_exclude = set(spec.get("exclude_dirs", set()))

        for sub in paths:
            target = root / sub
            if not target.is_dir():
                warnings.warn(
                    f"build_index: skipping missing directory: {target} "
                    f"(category={category})"
                )
                continue

            docs = index_directory(
                root=target,
                source_category=category,
                suffixes=suffixes,
                exclude_dirs=DEFAULT_EXCLUDE_DIRS | extra_exclude,
                subdir_pattern=subdir_pattern,
            )
            all_docs.extend(docs)

    return all_docs
