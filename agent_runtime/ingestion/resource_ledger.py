"""ResourceLedger v1 for repository access and high-cost command evidence."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import yaml

try:
    from atomic_io import atomic_write_text
except ImportError:  # pragma: no cover
    from agent_runtime.atomic_io import atomic_write_text


@dataclass
class ResourceLedger:
    task_id: str
    repo_url: str | None = None
    repo_access: dict[str, Any] = field(default_factory=lambda: {
        "access_level": "github_api_tree_plus_key_files",
        "clone_performed": False,
        "sparse_clone_performed": False,
        "full_clone_performed": False,
        "files_read": 0,
        "bytes_downloaded": 0,
    })
    workspace: dict[str, Any] = field(default_factory=lambda: {
        "size_mb_before": None,
        "size_mb_after": None,
        "files_created": None,
    })
    commands: dict[str, Any] = field(default_factory=lambda: {
        "clone_commands_blocked": 0,
        "high_cost_commands_seen": [],
        "approval_required": [],
    })

    @classmethod
    def from_manifest(cls, task_id: str, manifest: Any) -> "ResourceLedger":
        data = manifest.as_dict() if hasattr(manifest, "as_dict") else dict(manifest)
        ledger = cls(task_id=task_id, repo_url=data.get("repo_url"))
        ledger.repo_access.update({
            "access_level": data.get("access_level"),
            "clone_performed": bool(data.get("clone_performed", False)),
            "files_read": len(data.get("files_read") or []),
            "bytes_downloaded": int(data.get("bytes_downloaded") or 0),
        })
        return ledger

    def record_clone_guard(self, decision: Any) -> None:
        command = getattr(decision, "command", None) or (decision.get("command") if isinstance(decision, dict) else None)
        action = getattr(decision, "action", None) or (decision.get("action") if isinstance(decision, dict) else None)
        reason = getattr(decision, "reason", None) or (decision.get("reason") if isinstance(decision, dict) else None)
        if action in {"deny", "pending_approval"}:
            self.commands["high_cost_commands_seen"].append(command)
        if action == "deny" and command and str(command).startswith("git clone"):
            self.commands["clone_commands_blocked"] += 1
        if action == "pending_approval":
            self.commands["approval_required"].append({"command": command, "reason": reason})

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def write_resource_ledger(run_dir: Path, ledger: ResourceLedger) -> Path:
    path = run_dir / "resource_ledger.yml"
    atomic_write_text(path, yaml.safe_dump(ledger.as_dict(), sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path
