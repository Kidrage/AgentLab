"""Optional CodeGraph CLI adapter for local checkouts only."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import shutil
import subprocess
import time

from .base import RepoIndexer, RepoIndexDecision, RepoIndexQueryResult, RepoIndexResult, RepoIndexStatus


def is_remote_repo_ref(value: str | Path) -> bool:
    text = str(value)
    parsed = urlparse(text)
    return parsed.scheme in {"http", "https", "ssh", "git"} or text.startswith("git@")


def display_repo_path(repo_path: Path) -> str:
    if repo_path.exists():
        return repo_path.resolve().name
    return str(repo_path)


class CodeGraphAdapter(RepoIndexer):
    indexer_name = "codegraph_cli"

    def __init__(self, config: dict[str, Any] | None = None, *, runner=None, which=None):
        self.config = config or {}
        self.runner = runner or subprocess.run
        self.which = which or shutil.which

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("enabled", False))

    @property
    def command(self) -> str:
        return str((self.config.get("codegraph") or {}).get("command") or "codegraph")

    def status(self, repo_path: Path) -> RepoIndexStatus:
        warnings: list[str] = []
        if is_remote_repo_ref(repo_path):
            return RepoIndexStatus(str(repo_path), self.indexer_name, self.enabled, "denied", ["remote repo refs are not accepted"])
        if not repo_path.exists():
            return RepoIndexStatus(str(repo_path), self.indexer_name, self.enabled, "missing_checkout", ["repo_path does not exist"])
        if not self.enabled:
            warnings.append("repo_indexing disabled; status only")
            return RepoIndexStatus(display_repo_path(repo_path), self.indexer_name, False, "disabled", warnings)
        if not self.which(self.command):
            return RepoIndexStatus(display_repo_path(repo_path), self.indexer_name, True, "setup_required", [f"{self.command} CLI not found"])
        return RepoIndexStatus(display_repo_path(repo_path), self.indexer_name, True, "available", warnings)

    def can_index(self, repo_path: Path, *, mode: str) -> RepoIndexDecision:
        policy = self.config.get("policy") or {}
        if is_remote_repo_ref(repo_path):
            return RepoIndexDecision("deny", ["remote repo URL/ref rejected; CodeGraph never clones repos"])
        if not repo_path.exists():
            return RepoIndexDecision("deny", ["local checkout missing"])
        if mode == "repo_profile" or policy.get("forbid_repo_profile_indexing", True) and mode == "repo_profile":
            return RepoIndexDecision("deny", ["repo_profile mode forbids indexing"])
        if not self.enabled:
            return RepoIndexDecision("setup_required", ["repo_indexing disabled; dry-run/status only"])
        if not self.which(self.command):
            return RepoIndexDecision("setup_required", [f"{self.command} CLI not found"])
        if policy.get("require_approval_for_indexing", True):
            return RepoIndexDecision("pending_approval", ["real indexing requires explicit approval"], True)
        return RepoIndexDecision("allow", ["local checkout and policy allow indexing"])

    def index_repo(self, repo_path: Path, *, dry_run: bool = True, mode: str = "repo_patch", approve_indexing: bool = False) -> RepoIndexResult:
        decision = self.can_index(repo_path, mode=mode)
        args = list(((self.config.get("codegraph") or {}).get("index_args") or ["init", "-i"]))
        command = [self.command, *args, str(repo_path)]
        if dry_run:
            return RepoIndexResult(display_repo_path(repo_path), self.indexer_name, True, decision, False, command, warnings=decision.reasons)
        if decision.action != "allow":
            if approve_indexing and decision.action == "pending_approval":
                decision = RepoIndexDecision("allow", ["approved real indexing"], False)
            else:
                return RepoIndexResult(display_repo_path(repo_path), self.indexer_name, False, decision, False, command, warnings=decision.reasons)
        if not approve_indexing:
            return RepoIndexResult(display_repo_path(repo_path), self.indexer_name, False, RepoIndexDecision("pending_approval", ["real indexing requires explicit approval"], True), False, command, warnings=["real indexing requires explicit approval"])
        start = time.monotonic()
        proc = self.runner(command, cwd=str(repo_path), capture_output=True, text=True, timeout=int((self.config.get("policy") or {}).get("max_index_seconds", 120)))
        duration = round(time.monotonic() - start, 3)
        return RepoIndexResult(display_repo_path(repo_path), self.indexer_name, False, RepoIndexDecision("allow", ["index command executed"]), True, command, proc.returncode, duration_sec=duration)

    def query(self, repo_path: Path, query: str) -> RepoIndexQueryResult:
        status = self.status(repo_path)
        if status.status not in {"available"}:
            return RepoIndexQueryResult(display_repo_path(repo_path), self.indexer_name, query, warnings=status.warnings, status=status.status)
        return RepoIndexQueryResult(display_repo_path(repo_path), self.indexer_name, query, results=[], warnings=["query adapter placeholder; no external command executed by default"], status="dry_run")
