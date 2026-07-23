"""Migration readiness checks for AgentLab.

The migration doctor is intentionally read-mostly: it verifies environment,
repository, SMB/TrueNAS, Web UI, and cache prerequisites without printing or
persisting secret values.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any

import yaml

from atomic_io import atomic_write_text, atomic_write_yaml, safe_read_yaml


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_yaml(path: Path) -> dict[str, Any]:
    data = safe_read_yaml(path, {})
    return data if isinstance(data, dict) else {}


def _check(checks: list[dict[str, Any]], check_id: str, status: str, message: str, **details: Any) -> None:
    checks.append({"id": check_id, "status": status, "message": message, "details": details})


def _summarize(checks: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"pass": 0, "warn": 0, "fail": 0}
    for check in checks:
        status = check.get("status", "warn")
        summary[status] = summary.get(status, 0) + 1
    return summary


def _overall_status(checks: list[dict[str, Any]]) -> str:
    statuses = {c.get("status") for c in checks}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"


def _version_at_least(required: str) -> bool:
    required = str(required or ">=3.10").strip()
    if not required.startswith(">="):
        return True
    parts = required[2:].split(".")
    wanted = tuple(int(p) for p in parts[:3] if p.isdigit())
    current = sys.version_info[: len(wanted)]
    return current >= wanted


def _git_remote(agentlab_root: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=str(agentlab_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        remote = result.stdout.strip()
        return bool(remote), remote
    except Exception as exc:  # pragma: no cover - defensive for machines without git
        return False, str(exc)


def _env_check(checks: list[dict[str, Any]], name: str, *, required: bool, purpose: str = "") -> None:
    configured = bool(os.getenv(name))
    if configured:
        _check(checks, f"env.{name}", "pass", f"{name} configured", required=required, purpose=purpose)
    elif required:
        _check(checks, f"env.{name}", "fail", f"{name} missing", required=required, purpose=purpose)
    else:
        _check(checks, f"env.{name}", "pass", f"{name} optional and not configured", required=required, purpose=purpose)


def run_migration_doctor(
    agentlab_root: Path,
    project: str = "AgentLab",
    *,
    task_id: str | None = None,
    write_report: bool = False,
    write_probe: bool = True,
) -> dict[str, Any]:
    """Return a structured migration readiness report."""
    agentlab_root = Path(agentlab_root).resolve()
    config_root = agentlab_root / "config"
    project_root = agentlab_root / "projects" / project
    profile_path = config_root / "migration_profile.yml"
    profile = _load_yaml(profile_path)
    backup_policy = _load_yaml(config_root / "backup_policy.yml")
    github_policy = _load_yaml(config_root / "github_policy.yml")

    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    blocking_reasons: list[str] = []

    if profile:
        _check(checks, "migration_profile", "pass", "migration_profile.yml loaded", path=str(profile_path))
    else:
        _check(checks, "migration_profile", "fail", "migration_profile.yml missing or empty", path=str(profile_path))

    required_python = ((profile.get("environment") or {}).get("python") or ">=3.10") if profile else ">=3.10"
    python_status = "pass" if _version_at_least(required_python) else "fail"
    _check(
        checks,
        "python.version",
        python_status,
        f"Python {platform.python_version()} against {required_python}",
        executable=sys.executable,
    )

    for rel in ["agent_runtime", "agent_templates", "config", "projects", "web_ui"]:
        path = agentlab_root / rel
        _check(checks, f"dir.{rel}", "pass" if path.is_dir() else "fail", f"{rel} {'exists' if path.is_dir() else 'missing'}", path=str(path))

    _check(
        checks,
        "project.root",
        "pass" if project_root.is_dir() else "fail",
        f"project {project} {'exists' if project_root.is_dir() else 'missing'}",
        path=str(project_root),
    )

    for item in (((profile.get("required_user_inputs") or {}).get("model_api") or []) if profile else []):
        _env_check(
            checks,
            str(item.get("name", "")),
            required=bool(item.get("required", False)),
            purpose=str(item.get("purpose", "")),
        )

    github_token_env = (
        (((profile.get("required_user_inputs") or {}).get("backup_permissions") or {}).get("github") or {}).get("token_env")
        or (github_policy.get("auth") or {}).get("token_env")
        or "GITHUB_TOKEN"
    )
    has_remote, remote = _git_remote(agentlab_root)
    origin_uses_ssh = remote.startswith("git@") or remote.startswith("ssh://")
    # Respect project-level GitHub backup override and SSH source remotes.
    project_config = _load_yaml(project_root / "project_config.yml")
    project_github_disabled = not bool((project_config.get("github") or {}).get("backup", {}).get("enabled", True))
    global_github_enabled = bool((backup_policy.get("targets") or {}).get("github", {}).get("enabled", False))
    github_token_required = (not project_github_disabled) and global_github_enabled and not origin_uses_ssh
    if github_token_required or os.getenv(str(github_token_env)):
        _env_check(checks, str(github_token_env), required=github_token_required, purpose="GitHub guarded backup")
    else:
        _check(
            checks,
            f"env.{github_token_env}",
            "pass",
            f"{github_token_env} not required for current GitHub SSH/project backup configuration",
            required=False,
            purpose="GitHub guarded backup",
        )
    if project_github_disabled:
        checks.append({"id": "github.backup.disabled", "status": "pass",
                        "message": f"Project {project} has GitHub backup disabled; GITHUB_TOKEN is not required."})

    _check(
        checks,
        "git.remote.origin",
        "pass" if has_remote else "warn",
        "git origin remote configured" if has_remote else "git origin remote not configured",
        remote=remote,
    )

    try:
        from truenas_sync import get_truenas_status

        truenas = get_truenas_status(agentlab_root, write_probe=write_probe)
        smb_status = "pass" if truenas.get("status") == "pass" else "fail"
        _check(
            checks,
            "smb.truenas",
            smb_status,
            truenas.get("message", "TrueNAS status checked"),
            mount_path=truenas.get("mount_path"),
            protocol_url=truenas.get("protocol_url"),
            writable=truenas.get("writable"),
            free_bytes=truenas.get("free_bytes"),
        )
    except Exception as exc:
        truenas = {"status": "fail", "error": str(exc)}
        _check(checks, "smb.truenas", "fail", f"TrueNAS status check failed: {exc}")

    web_ui_cfg = ((profile.get("required_user_inputs") or {}).get("web_ui") or {}) if profile else {}
    port_env = str(web_ui_cfg.get("port_env") or "AGENTLAB_PORT")
    raw_port = os.getenv(port_env, str(web_ui_cfg.get("default_port") or 8765))
    try:
        port = int(raw_port)
        port_ok = 1 <= port <= 65535
    except ValueError:
        port = raw_port
        port_ok = False
    _check(checks, "web_ui.port", "pass" if port_ok else "fail", f"Web UI port {raw_port}", port_env=port_env, port=port)

    token_env = str(web_ui_cfg.get("auth_token_env") or "AGENTLAB_WEB_UI_TOKEN")
    token_required = bool(web_ui_cfg.get("auth_required", True))
    _env_check(checks, token_env, required=token_required, purpose="Web UI local access control")

    cache_cfg = ((profile.get("required_user_inputs") or {}).get("cache") or {}) if profile else {}
    cache_root = agentlab_root / str(cache_cfg.get("root") or ".agentlab_runtime/cache")
    cache_status = "pass" if cache_root.exists() else "warn"
    _check(
        checks,
        "cache.root",
        cache_status,
        "cache root exists" if cache_root.exists() else "cache root not created yet",
        path=str(cache_root),
        parent_exists=cache_root.parent.exists(),
    )

    try:
        disk = shutil.disk_usage(agentlab_root)
        _check(checks, "local.disk", "pass", "local disk usage readable", total_bytes=disk.total, free_bytes=disk.free)
    except Exception as exc:
        _check(checks, "local.disk", "warn", f"local disk usage unavailable: {exc}")

    summary = _summarize(checks)
    for check in checks:
        if check.get("status") == "fail":
            blocking_reasons.append(check.get("message", check.get("id", "unknown failure")))
        elif check.get("status") == "warn":
            warnings.append(check.get("message", check.get("id", "warning")))

    report: dict[str, Any] = {
        "version": 1,
        "project": project,
        "task_id": task_id or "",
        "created_at": utc_now(),
        "status": _overall_status(checks),
        "summary": summary,
        "checks": checks,
        "warnings": warnings,
        "blocking_reasons": blocking_reasons,
        "paths": {
            "agentlab_root": str(agentlab_root),
            "project_root": str(project_root),
            "migration_profile": str(profile_path),
        },
        "truenas_status": truenas,
        "backup_policy_loaded": bool(backup_policy),
    }

    if write_report and task_id:
        run_dir = agentlab_root / "projects" / project / "runs" / task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_yaml(run_dir / "migration_doctor_report.yml", report)

    return report


def write_migration_bootstrap(
    agentlab_root: Path,
    project: str = "AgentLab",
    *,
    task_id: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Write safe migration helper files without real secrets."""
    agentlab_root = Path(agentlab_root).resolve()
    profile = _load_yaml(agentlab_root / "config" / "migration_profile.yml")
    env_path = agentlab_root / "agent_runtime" / ".env.example"
    checklist_path = agentlab_root / "docs" / "MIGRATION_CHECKLIST.md"
    created: list[str] = []
    skipped: list[str] = []

    env_names = ["AGENTLAB_ROOT", "DEFAULT_PROJECT"]
    for item in ((profile.get("required_user_inputs") or {}).get("model_api") or []):
        env_names.append(str(item.get("name")))
    github_token_env = (((profile.get("required_user_inputs") or {}).get("backup_permissions") or {}).get("github") or {}).get("token_env") or "GITHUB_TOKEN"
    env_names.extend([str(github_token_env), "AGENTLAB_PORT", "AGENTLAB_WEB_UI_TOKEN"])
    env_lines = [
        "# AgentLab local environment template",
        "# Copy to agent_runtime/.env and fill values locally. Do not commit real secrets.",
        f"AGENTLAB_ROOT={agentlab_root}",
        f"DEFAULT_PROJECT={project}",
    ]
    env_lines.extend(f"{name}=" for name in dict.fromkeys(env_names) if name and name not in {"AGENTLAB_ROOT", "DEFAULT_PROJECT"})

    if overwrite or not env_path.exists():
        atomic_write_text(env_path, "\n".join(env_lines) + "\n")
        created.append(str(env_path))
    else:
        skipped.append(str(env_path))

    checklist = "\n".join(
        [
            "# AgentLab Migration Checklist",
            "",
            "1. Clone or copy AgentLab source.",
            "2. Copy `agent_runtime/.env.example` to `agent_runtime/.env` and fill local secrets.",
            "3. Mount TrueNAS/SMB workspace before running sync commands.",
            "4. Run `./agentlab.sh doctor`.",
            "5. Run `./agentlab.sh model-doctor --project AgentLab`.",
            "6. Run `./agentlab.sh migration-doctor --project AgentLab`.",
            "7. Run `./agentlab.sh truenas-status --project AgentLab`.",
            "",
            "Do not commit real API keys or tokens.",
        ]
    )
    if overwrite or not checklist_path.exists():
        atomic_write_text(checklist_path, checklist + "\n")
        created.append(str(checklist_path))
    else:
        skipped.append(str(checklist_path))

    report = {
        "version": 1,
        "project": project,
        "task_id": task_id or "",
        "created_at": utc_now(),
        "status": "completed",
        "created": created,
        "skipped_existing": skipped,
    }
    if task_id:
        run_dir = agentlab_root / "projects" / project / "runs" / task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_yaml(run_dir / "migration_init_report.yml", report)
    return report
