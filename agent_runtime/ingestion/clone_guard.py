"""High-risk repository command policy checks."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import shlex
from pathlib import Path
from typing import Any

try:
    from command_runner import normalize_command
except ImportError:  # pragma: no cover
    from agent_runtime.command_runner import normalize_command

from .repo_policy import load_repo_ingestion_policy


@dataclass
class CloneGuardDecision:
    command: str
    action: str
    reason: str
    mode: str
    approval_required: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _command_text(argv: list[str]) -> str:
    return shlex.join(argv)


def _is_sparse_clone(argv: list[str]) -> bool:
    text = " ".join(argv)
    return "--filter=" in text or "--depth" in argv or "--sparse" in argv or "sparse-checkout" in text


def _classify(argv: list[str]) -> str | None:
    exe = Path(argv[0]).name if argv else ""
    if exe == "git" and len(argv) >= 2 and argv[1] == "clone":
        return "git_clone"
    if exe == "git" and len(argv) >= 3 and argv[1] == "submodule" and argv[2] == "update":
        return "git_submodule_update"
    if exe == "cmake" and "--build" in argv:
        return "build"
    if exe == "npm" and len(argv) >= 2 and argv[1] == "install":
        return "install"
    if exe == "pip" and len(argv) >= 2 and argv[1] == "install":
        return "install"
    if exe == "poetry" and len(argv) >= 2 and argv[1] == "install":
        return "install"
    if exe == "cargo" and len(argv) >= 2 and argv[1] == "build":
        return "build"
    if exe == "xcodebuild":
        return "build"
    return None


def evaluate_command(
    command: str | list[str],
    *,
    mode: str = "repo_profile",
    policy: dict[str, Any] | None = None,
) -> CloneGuardDecision:
    try:
        argv = normalize_command(command)
    except Exception as exc:
        return CloneGuardDecision(str(command), "deny", str(exc), mode)
    text = _command_text(argv)
    policy = policy or load_repo_ingestion_policy()
    kind = _classify(argv)
    if kind is None:
        return CloneGuardDecision(text, "allow", "command is outside clone guard scope", mode)

    if mode == "repo_profile":
        return CloneGuardDecision(text, "deny", f"{kind} is not allowed in repo_profile API-only mode", mode)

    if mode == "repo_patch":
        if kind == "git_clone" and _is_sparse_clone(argv):
            return CloneGuardDecision(text, "allow", "sparse clone allowed for repo_patch", mode)
        return CloneGuardDecision(text, "deny", f"{kind} requires build/test or full clone approval", mode)

    if mode == "repo_build_test":
        if kind in {"git_clone", "git_submodule_update", "build", "install"}:
            return CloneGuardDecision(text, "pending_approval", f"{kind} requires approval in repo_build_test mode", mode, True)

    if kind == "git_clone" and not policy.get("allow_full_clone", False) and not _is_sparse_clone(argv):
        return CloneGuardDecision(text, "pending_approval", "full clone requires approval", mode, True)

    return CloneGuardDecision(text, "allow", "allowed by clone guard", mode)
