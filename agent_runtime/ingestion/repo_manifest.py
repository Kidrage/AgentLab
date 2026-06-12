"""RepoManifest schema and writers."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

try:
    from atomic_io import atomic_write_json
except ImportError:  # pragma: no cover
    from agent_runtime.atomic_io import atomic_write_json


@dataclass
class RepoManifest:
    repo_url: str
    owner: str
    repo: str
    ref: str = "main"
    resolved_commit: str | None = None
    access_level: str = "github_api_tree_plus_key_files"
    clone_performed: bool = False
    tree_truncated: bool = False
    files_seen: int = 0
    files_read: list[dict[str, Any]] = field(default_factory=list)
    files_skipped_by_policy: list[dict[str, Any]] = field(default_factory=list)
    bytes_downloaded: int = 0
    evidence_level: str = "remote_api_targeted_files"
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def write_repo_manifest(run_dir: Path, manifest: RepoManifest) -> Path:
    path = run_dir / "repo_manifest.json"
    atomic_write_json(path, manifest.as_dict())
    return path
