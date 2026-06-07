"""TrueNAS/SMB push-only merge sync for AgentLab.

The sync contract is intentionally conservative:

- local -> remote only
- never overwrite existing remote files
- never delete remote files
- write local manifest/checksum reports for recovery verification
"""

from __future__ import annotations

from datetime import datetime, timezone
from fnmatch import fnmatch
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
from typing import Any, Iterable

from atomic_io import atomic_write_yaml, safe_read_yaml


DEFAULT_EXCLUDES = [
    ".git/**",
    "**/.git/**",
    ".venv/**",
    "**/.venv/**",
    "node_modules/**",
    "**/node_modules/**",
    "**/__pycache__/**",
    "**/*.pyc",
    ".DS_Store",
    "**/.DS_Store",
    ".env",
    "**/.env",
    "agent_runtime/.env",
    ".agentlab_runtime/cache/**",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_backup_policy(agentlab_root: Path) -> dict[str, Any]:
    data = safe_read_yaml(agentlab_root / "config" / "backup_policy.yml", {})
    return data if isinstance(data, dict) else {}


def _truenas_config(agentlab_root: Path) -> dict[str, Any]:
    policy = _load_backup_policy(agentlab_root)
    return (((policy.get("targets") or {}).get("truenas") or {}) if policy else {})


def _status(status: str, message: str, **kwargs: Any) -> dict[str, Any]:
    data = {"version": 1, "target": "truenas", "status": status, "message": message, "created_at": utc_now()}
    data.update(kwargs)
    return data


def get_truenas_status(agentlab_root: Path, *, write_probe: bool = True) -> dict[str, Any]:
    """Return TrueNAS/SMB mount and write-readiness status."""
    agentlab_root = Path(agentlab_root).resolve()
    cfg = _truenas_config(agentlab_root)
    enabled = bool(cfg.get("enabled", False))
    mount_raw = str(cfg.get("mount_path") or "").strip()
    mount_path = Path(mount_raw).expanduser() if mount_raw else None
    protocol_url = str(cfg.get("protocol_url") or "")

    if not enabled:
        return _status("warn", "TrueNAS target disabled", enabled=False, protocol_url=protocol_url, mount_path=str(mount_path))
    if not mount_raw or mount_path is None:
        return _status("fail", "TrueNAS mount_path is not configured", enabled=enabled, protocol_url=protocol_url, mount_path="")
    if not mount_path.exists():
        return _status("fail", "TrueNAS mount path does not exist", enabled=enabled, protocol_url=protocol_url, mount_path=str(mount_path), mounted=False)
    if not mount_path.is_dir():
        return _status("fail", "TrueNAS mount path is not a directory", enabled=enabled, protocol_url=protocol_url, mount_path=str(mount_path), mounted=False)

    writable = os.access(mount_path, os.W_OK)
    probe_error = ""
    if write_probe:
        try:
            probe_dir = mount_path / ".agentlab_probe"
            probe_dir.mkdir(parents=True, exist_ok=True)
            probe_file = probe_dir / f"probe_{os.getpid()}_{int(datetime.now().timestamp())}.tmp"
            probe_file.write_text("ok\n", encoding="utf-8")
            probe_file.unlink(missing_ok=True)
            writable = True
        except Exception as exc:
            writable = False
            probe_error = str(exc)

    try:
        disk = shutil.disk_usage(mount_path)
        total_bytes = disk.total
        free_bytes = disk.free
    except Exception:
        total_bytes = 0
        free_bytes = 0

    return _status(
        "pass" if writable else "fail",
        "TrueNAS mount is available" if writable else "TrueNAS mount is not writable",
        enabled=enabled,
        protocol_url=protocol_url,
        mount_path=str(mount_path),
        mounted=True,
        writable=writable,
        write_probe=write_probe,
        probe_error=probe_error,
        total_bytes=total_bytes,
        free_bytes=free_bytes,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_posix(path: Path) -> str:
    return path.as_posix().lstrip("./")


def _matches_pattern(rel_posix: str, pattern: str) -> bool:
    pattern = str(pattern or "").strip().lstrip("/")
    if not pattern:
        return False
    name = PurePosixPath(rel_posix).name
    if fnmatch(rel_posix, pattern) or fnmatch(name, pattern):
        return True
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        return rel_posix == prefix or rel_posix.startswith(prefix + "/")
    if pattern.startswith("**/"):
        suffix = pattern[3:]
        return rel_posix == suffix or rel_posix.endswith("/" + suffix) or fnmatch(rel_posix, pattern)
    return PurePosixPath(rel_posix).match(pattern)


def _is_excluded(rel_posix: str, patterns: Iterable[str]) -> bool:
    return any(_matches_pattern(rel_posix, pattern) for pattern in patterns)


def _iter_sync_candidates(agentlab_root: Path, cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int], list[str]]:
    sync_items = cfg.get("sync_items") or []
    global_excludes = list(dict.fromkeys(DEFAULT_EXCLUDES + list(cfg.get("exclude") or [])))
    candidates: list[dict[str, Any]] = []
    summary = {"excluded": 0, "missing_sources": 0}
    warnings: list[str] = []

    for item in sync_items:
        local_rel = str(item.get("local_path") or item.get("path") or "").strip()
        remote_rel = str(item.get("remote_path") or local_rel).strip()
        if not local_rel:
            continue
        local_root = agentlab_root / local_rel
        item_excludes = list(item.get("exclude") or [])
        excludes = list(dict.fromkeys(global_excludes + item_excludes))
        if not local_root.exists():
            summary["missing_sources"] += 1
            warnings.append(f"Missing sync source: {local_rel}")
            continue
        files = [local_root] if local_root.is_file() else sorted(p for p in local_root.rglob("*") if p.is_file())
        for local_file in files:
            if local_file.is_symlink():
                summary["excluded"] += 1
                continue
            root_rel = _as_posix(local_file.relative_to(agentlab_root))
            try:
                item_rel = _as_posix(local_file.relative_to(local_root if local_root.is_dir() else local_root.parent))
            except ValueError:
                item_rel = local_file.name
            if _is_excluded(root_rel, excludes):
                summary["excluded"] += 1
                continue
            candidates.append(
                {
                    "local_path": root_rel,
                    "local_abs": local_file,
                    "remote_path": _as_posix(Path(remote_rel) / item_rel),
                    "direction": item.get("direction", "push_only_merge"),
                }
            )
    return candidates, summary, warnings


def _build_file_entry(local_file: Path, remote_file: Path, local_rel: str, remote_rel: str) -> dict[str, Any]:
    stat = local_file.stat()
    entry: dict[str, Any] = {
        "local_path": local_rel,
        "remote_path": remote_rel,
        "size": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "local_sha256": sha256_file(local_file),
        "remote_sha256": "",
        "action": "pending",
        "verified": False,
        "warning": "",
        "error": "",
    }
    if remote_file.exists() and remote_file.is_file():
        try:
            entry["remote_sha256"] = sha256_file(remote_file)
            if entry["remote_sha256"] != entry["local_sha256"]:
                entry["warning"] = "remote exists with different checksum; kept remote per no-overwrite policy"
        except Exception as exc:
            entry["warning"] = f"could not checksum remote: {exc}"
    return entry


def _write_reports(run_dir: Path, report: dict[str, Any], manifest: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(run_dir / "truenas_sync_report.yml", report)
    atomic_write_yaml(run_dir / "truenas_manifest.yml", manifest)


def _update_sync_ledger(agentlab_root: Path, project: str, report: dict[str, Any]) -> None:
    ledger_path = agentlab_root / "projects" / project / "agent_docs" / "10_SYNC_LEDGER.yml"
    ledger = safe_read_yaml(ledger_path, None)
    if not isinstance(ledger, dict):
        ledger = {"version": 1, "project": project, "entries": []}
    entry = {
        "timestamp": report.get("created_at", utc_now()),
        "task_id": report.get("task_id", ""),
        "target": "truenas",
        "status": report.get("status", "unknown"),
        "dry_run": bool(report.get("dry_run", False)),
        "mount_path": report.get("mount_path", ""),
        "protocol_url": report.get("protocol_url", ""),
        "copied_files": report.get("copied_files", 0),
        "would_copy_files": report.get("would_copy_files", 0),
        "skipped_existing": report.get("skipped_existing", 0),
        "failed_files": report.get("failed_files", 0),
        "manifest": report.get("manifest_path", ""),
    }
    ledger.setdefault("entries", []).append(entry)
    atomic_write_yaml(ledger_path, ledger)


def run_truenas_sync(
    agentlab_root: Path,
    project: str,
    task_id: str,
    *,
    dry_run: bool = True,
    execute: bool = False,
    write_probe: bool = True,
) -> dict[str, Any]:
    """Run a TrueNAS dry-run or execute sync and write local reports."""
    agentlab_root = Path(agentlab_root).resolve()
    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    cfg = _truenas_config(agentlab_root)
    status = get_truenas_status(agentlab_root, write_probe=write_probe)
    effective_dry_run = not execute or dry_run
    if execute:
        effective_dry_run = False
    manifest_path = f"runs/{task_id}/truenas_manifest.yml"
    report: dict[str, Any] = {
        "version": 1,
        "target": "truenas",
        "project": project,
        "task_id": task_id,
        "created_at": utc_now(),
        "dry_run": effective_dry_run,
        "status": "failed",
        "protocol_url": status.get("protocol_url") or cfg.get("protocol_url", ""),
        "mount_path": status.get("mount_path") or cfg.get("mount_path", ""),
        "manifest_path": manifest_path,
        "copied_files": 0,
        "would_copy_files": 0,
        "skipped_existing": 0,
        "failed_files": 0,
        "excluded_files": 0,
        "warnings": [],
        "blocking_reasons": [],
    }
    manifest: dict[str, Any] = {
        "version": 1,
        "target": "truenas",
        "project": project,
        "task_id": task_id,
        "created_at": report["created_at"],
        "dry_run": effective_dry_run,
        "checksum_algorithm": "sha256",
        "files": [],
        "summary": {},
    }

    if status.get("status") != "pass":
        report["blocking_reasons"].append(status.get("message", "TrueNAS target unavailable"))
        manifest["summary"] = {"total": 0, "failed": 0}
        _write_reports(run_dir, report, manifest)
        _update_sync_ledger(agentlab_root, project, report)
        return report

    mount_path = Path(str(status.get("mount_path")))
    candidates, candidate_summary, warnings = _iter_sync_candidates(agentlab_root, cfg)
    report["warnings"].extend(warnings)
    report["excluded_files"] = candidate_summary.get("excluded", 0)

    for candidate in candidates:
        local_file: Path = candidate["local_abs"]
        remote_rel = candidate["remote_path"]
        remote_file = mount_path / remote_rel
        entry = _build_file_entry(local_file, remote_file, candidate["local_path"], remote_rel)

        if remote_file.exists():
            entry["action"] = "skipped_existing"
            entry["verified"] = bool(entry.get("remote_sha256") and entry.get("remote_sha256") == entry.get("local_sha256"))
            report["skipped_existing"] += 1
            if entry.get("warning"):
                report["warnings"].append(f"{entry['remote_path']}: {entry['warning']}")
            manifest["files"].append(entry)
            continue

        if effective_dry_run:
            entry["action"] = "would_copy"
            report["would_copy_files"] += 1
            manifest["files"].append(entry)
            continue

        try:
            remote_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(local_file, remote_file)
            entry["remote_sha256"] = sha256_file(remote_file)
            entry["verified"] = entry["remote_sha256"] == entry["local_sha256"]
            entry["action"] = "copied" if entry["verified"] else "copied_unverified"
            if entry["verified"]:
                report["copied_files"] += 1
            else:
                report["failed_files"] += 1
                entry["error"] = "checksum mismatch after copy"
        except Exception as exc:
            entry["action"] = "failed"
            entry["error"] = str(exc)
            report["failed_files"] += 1
        manifest["files"].append(entry)

    manifest["summary"] = {
        "total_candidates": len(candidates),
        "would_copy": report["would_copy_files"],
        "copied": report["copied_files"],
        "skipped_existing": report["skipped_existing"],
        "failed": report["failed_files"],
        "excluded": report["excluded_files"],
        "missing_sources": candidate_summary.get("missing_sources", 0),
    }
    if report["failed_files"]:
        report["status"] = "partial"
        report["blocking_reasons"].append(f"{report['failed_files']} file(s) failed during TrueNAS sync")
    elif effective_dry_run:
        report["status"] = "dry_run_completed"
    else:
        report["status"] = "synced"

    _write_reports(run_dir, report, manifest)
    _update_sync_ledger(agentlab_root, project, report)
    return report


def build_backup_status(agentlab_root: Path, project: str, *, task_id: str | None = None) -> dict[str, Any]:
    """Build a combined local/GitHub/TrueNAS backup status snapshot."""
    agentlab_root = Path(agentlab_root).resolve()
    project_root = agentlab_root / "projects" / project
    project_config = safe_read_yaml(project_root / "project_config.yml", {})
    github_policy = safe_read_yaml(agentlab_root / "config" / "github_policy.yml", {})
    ledger = safe_read_yaml(project_root / "agent_docs" / "10_SYNC_LEDGER.yml", {})
    entries = ledger.get("entries", []) if isinstance(ledger, dict) else []
    github_cfg = ((project_config or {}).get("github") or {}).get("backup") or {}
    github_token_env = ((github_policy or {}).get("auth") or {}).get("token_env", "GITHUB_TOKEN")
    truenas_status = get_truenas_status(agentlab_root, write_probe=False)

    latest_github = next((e for e in reversed(entries) if e.get("target", "github") == "github" or e.get("commit_sha")), None)
    latest_truenas = next((e for e in reversed(entries) if e.get("target") == "truenas"), None)
    latest_for_task = [e for e in entries if not task_id or e.get("task_id") == task_id]
    return {
        "version": 1,
        "project": project,
        "task_id": task_id or "",
        "created_at": utc_now(),
        "status": "pass" if truenas_status.get("status") == "pass" else "warn",
        "github": {
            "enabled": bool(github_cfg.get("enabled", False)),
            "owner": github_cfg.get("owner", ""),
            "repo": github_cfg.get("repo", ""),
            "branch": github_cfg.get("branch", ((github_policy or {}).get("defaults") or {}).get("backup_branch", "main")),
            "token_env": github_token_env,
            "token_configured": bool(os.getenv(github_token_env)),
            "latest": latest_github or {},
        },
        "truenas": {
            "status": truenas_status,
            "latest": latest_truenas or {},
        },
        "ledger": {
            "path": str(project_root / "agent_docs" / "10_SYNC_LEDGER.yml"),
            "entries_count": len(entries),
            "recent_entries": latest_for_task[-10:],
        },
    }
