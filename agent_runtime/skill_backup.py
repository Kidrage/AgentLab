"""Skill Vault backup planning and explicit rsync execution."""

from __future__ import annotations

# text-integrity: keep this file as real physical lines in Git and GitHub raw.
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import os
import shlex
import subprocess

from atomic_io import atomic_write_yaml, safe_read_yaml
from skill_vault import update_manifest, vault_root


@dataclass
class BackupPlan:
    source: Path
    remote: str
    command: list[str]
    dry_run: bool
    ready: bool
    error: str | None = None


def load_backup_policy(agentlab_root: Path) -> dict[str, Any]:
    data = safe_read_yaml(agentlab_root / "config" / "backup_policy.yml", default={}) or {}
    return data if isinstance(data, dict) else {}


def _skill_policy(policy: dict[str, Any]) -> dict[str, Any]:
    default = {
        "enabled": True,
        "source": "memory/global/skills",
        "remote_subdir": "memory/global/skills",
        "format": "full_mirror",
        "include_manifest": True,
        "include_registry": True,
        "retention_days": 365,
        "require_ssh_config": True,
        "dry_run_default": True,
    }
    configured = policy.get("skill_vault_backup") or {}
    if isinstance(configured, dict):
        default.update(configured)
    return default


def resolve_local_skill_vault_path(agentlab_root: Path, policy: dict[str, Any] | None = None) -> Path:
    cfg = _skill_policy(policy or load_backup_policy(agentlab_root))
    source = Path(str(cfg.get("source") or "memory/global/skills"))
    return source if source.is_absolute() else agentlab_root / source


def _remote_base(policy: dict[str, Any]) -> str | None:
    env_remote = os.getenv("AGENTLAB_SKILL_VAULT_BACKUP_REMOTE")
    if env_remote:
        return env_remote.rstrip("/")
    ssh = policy.get("ssh") or policy.get("truenas") or {}
    if isinstance(ssh, dict):
        user = os.getenv("AGENTLAB_BACKUP_SSH_USER") or ssh.get("user") or ssh.get("username")
        host = os.getenv("AGENTLAB_BACKUP_SSH_HOST") or ssh.get("host")
        base = os.getenv("AGENTLAB_BACKUP_REMOTE_BASE") or ssh.get("remote_base_path") or ssh.get("base_path")
        if user and host and base:
            return f"{user}@{host}:{str(base).rstrip('/')}"
    return None


def resolve_remote_skill_vault_path(agentlab_root: Path, policy: dict[str, Any] | None = None) -> str:
    effective = policy or load_backup_policy(agentlab_root)
    cfg = _skill_policy(effective)
    base = _remote_base(effective)
    if not base:
        raise ValueError(
            "Missing SSH backup config. Set AGENTLAB_SKILL_VAULT_BACKUP_REMOTE "
            "or AGENTLAB_BACKUP_SSH_USER, AGENTLAB_BACKUP_SSH_HOST, and AGENTLAB_BACKUP_REMOTE_BASE."
        )
    return f"{base.rstrip('/')}/{str(cfg.get('remote_subdir') or 'memory/global/skills').strip('/')}"


def plan_rsync_command(agentlab_root: Path, *, dry_run: bool = True) -> BackupPlan:
    policy = load_backup_policy(agentlab_root)
    cfg = _skill_policy(policy)
    source = resolve_local_skill_vault_path(agentlab_root, policy)
    if not cfg.get("enabled", True):
        return BackupPlan(source, "", [], dry_run, False, "Skill Vault backup is disabled by policy")
    if not source.exists():
        source = vault_root(agentlab_root)
        source.mkdir(parents=True, exist_ok=True)
    update_manifest(agentlab_root)
    try:
        remote = resolve_remote_skill_vault_path(agentlab_root, policy)
    except ValueError as exc:
        remote = ""
        error = str(exc)
        cmd = ["rsync", "-av", "--delete"] + (["--dry-run"] if dry_run else []) + [f"{source}/", "<missing-ssh-config>"]
        return BackupPlan(source, remote, cmd, dry_run, False, error)
    cmd = ["rsync", "-av", "--delete"]
    if dry_run:
        cmd.append("--dry-run")
    cmd.extend([f"{source}/", remote.rstrip("/") + "/"])
    return BackupPlan(source, remote, cmd, dry_run, True)


def dry_run_rsync_command(agentlab_root: Path) -> dict[str, Any]:
    plan = plan_rsync_command(agentlab_root, dry_run=True)
    return {
        "dry_run": True,
        "ready": plan.ready,
        "source": str(plan.source),
        "remote": plan.remote,
        "command": " ".join(shlex.quote(x) for x in plan.command),
        "error": plan.error,
    }


def execute_rsync(agentlab_root: Path) -> dict[str, Any]:
    plan = plan_rsync_command(agentlab_root, dry_run=False)
    if not plan.ready:
        return {
            "executed": False,
            "ready": False,
            "error": plan.error,
            "command": " ".join(shlex.quote(x) for x in plan.command),
        }
    result = subprocess.run(plan.command, capture_output=True, text=True, timeout=300)
    update_manifest(agentlab_root)
    return {
        "executed": result.returncode == 0,
        "ready": True,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "command": " ".join(shlex.quote(x) for x in plan.command),
    }


def backup_status(agentlab_root: Path) -> dict[str, Any]:
    policy = load_backup_policy(agentlab_root)
    cfg = _skill_policy(policy)
    plan = plan_rsync_command(agentlab_root, dry_run=True)
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "dry_run_default": bool(cfg.get("dry_run_default", True)),
        "source": str(plan.source),
        "remote": plan.remote,
        "ready": plan.ready,
        "error": plan.error,
    }
