"""Document model for the local search index.

A Document represents a single indexed file with metadata.
SourceCategory is an enum-like set of valid category strings.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, asdict
from datetime import datetime, timezone


# Enum-like set of valid source categories.
# These are the only accepted values for Document.source_category.
class SourceCategory:
    """String constants for document source categories."""

    REPO_FILES = "repo_files"
    DOCS = "docs"
    CONFIG = "config"
    SKILLS = "skills"
    TESTS = "tests"
    SCRIPTS = "scripts"
    ACCEPTANCE_RUNS = "acceptance_runs"
    TASK_RUNS = "task_runs"
    RECOVERY_HISTORY = "recovery_history"
    CLOSURE_FEEDBACK = "closure_feedback"
    EXTERNAL_INVENTORY = "external_inventory"
    PROJECT_BRAIN = "project_brain"
    WEB_SNAPSHOTS = "web_snapshots"

    _ALL = {
        REPO_FILES,
        DOCS,
        CONFIG,
        SKILLS,
        TESTS,
        SCRIPTS,
        ACCEPTANCE_RUNS,
        TASK_RUNS,
        RECOVERY_HISTORY,
        CLOSURE_FEEDBACK,
        EXTERNAL_INVENTORY,
        PROJECT_BRAIN,
        WEB_SNAPSHOTS,
    }

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in cls._ALL

    @classmethod
    def all_values(cls) -> set[str]:
        return set(cls._ALL)


def content_hash_of(text: str) -> str:
    """Compute SHA-256 hex digest of the given text content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Document:
    """A single indexed document with metadata and content."""

    path: str
    source_category: str
    content_hash: str
    text: str
    line_count: int
    size_bytes: int
    indexed_at: str

    def __post_init__(self) -> None:
        if not SourceCategory.is_valid(self.source_category):
            raise ValueError(
                f"Invalid source_category '{self.source_category}'. "
                f"Must be one of: {sorted(SourceCategory.all_values())}"
            )

    def to_dict(self) -> dict:
        """Serialize the document to a plain dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Document:
        """Reconstruct a Document from a dict (e.g. from JSON)."""
        return cls(
            path=data["path"],
            source_category=data["source_category"],
            content_hash=data["content_hash"],
            text=data["text"],
            line_count=data["line_count"],
            size_bytes=data["size_bytes"],
            indexed_at=data["indexed_at"],
        )

    @classmethod
    def from_file(
        cls,
        rel_path: str,
        text: str,
        source_category: str,
        size_bytes: int,
    ) -> Document:
        """Build a Document from file content and metadata."""
        lines = text.split("\n")
        return cls(
            path=rel_path,
            source_category=source_category,
            content_hash=content_hash_of(text),
            text=text,
            line_count=len(lines),
            size_bytes=size_bytes,
            indexed_at=datetime.now(timezone.utc).isoformat(),
        )
