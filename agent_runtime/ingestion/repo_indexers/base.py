"""Provider-neutral repo indexer contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RepoIndexDecision:
    action: str
    reasons: list[str] = field(default_factory=list)
    approval_required: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RepoIndexStatus:
    repo_path: str
    indexer: str
    enabled: bool
    status: str
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RepoIndexResult:
    repo_path: str
    indexer: str
    dry_run: bool
    decision: RepoIndexDecision
    performed: bool = False
    command: list[str] = field(default_factory=list)
    exit_code: int | None = None
    index_size_mb: float | None = None
    indexed_files: int | None = None
    duration_sec: float | None = None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["decision"] = self.decision.as_dict()
        return data


@dataclass
class RepoIndexQueryResult:
    repo_path: str
    indexer: str
    query: str
    tool: str = "search"
    results: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: str = "ok"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class RepoIndexer:
    indexer_name = "abstract"

    def status(self, repo_path: Path) -> RepoIndexStatus:
        raise NotImplementedError

    def can_index(self, repo_path: Path, *, mode: str) -> RepoIndexDecision:
        raise NotImplementedError

    def index_repo(self, repo_path: Path, *, dry_run: bool = True) -> RepoIndexResult:
        raise NotImplementedError

    def query(self, repo_path: Path, query: str) -> RepoIndexQueryResult:
        raise NotImplementedError

