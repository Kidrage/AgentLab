"""TrueNAS push-only merge sync for AgentLab.

Supports two transport modes:
- SSH: rsync over SSH (no local mount needed, recommended)
- SMB mount: cp/rsync to local SMB mount point (legacy)

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
import subprocess
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


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override into base. override values take precedence."""
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_backup_policy(agentlab_root: Path) -> dict[str, Any]:
    """Load backup_policy.yml, merged with backup_policy.local.yml if present."""
    data = safe_read_yaml(agentlab_root / "config" / "backup_policy.yml", {})
    policy = data if isinstance(data, dict) else {}

    local_path = agentlab_root / "config" / "backup_policy.local.yml"
    if local_path.exists():
        local_data = safe_read_yaml(local_path, {})
        if isinstance(local_data, dict) and local_data:
            policy = _deep_merge(policy, local_data)

    return policy


def _truenas_config(agentlab_root: Path) -> dict[str, Any]:
    policy = _load_backup_policy(agentlab_root)
    return (((policy.get("targets") or {}).get("truenas") or {}) if policy else {})


def _transport_mode(cfg: dict[str, Any]) -> str:
    """Return the active transport mode: 'ssh' or 'smb_mount'."""
    return str(cfg.get("transport", "smb_mount")).strip()


def _ssh_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Extract SSH transport config, with env-var fallback for password."""
    ssh = cfg.get("ssh") or {}
    identity_file = str(ssh.get("identity_file") or "").strip()
    if identity_file:
        identity_file = str(Path(identity_file).expanduser())
    password = os.environ.get("AGENTLAB_TRUENAS_PASSWORD", "").strip()
    return {
        "host": str(ssh.get("host") or "").strip(),
        "port": int(ssh.get("port", 22)),
        "user": str(ssh.get("user") or "").strip(),
        "identity_file": identity_file,
        "password": password,
        "remote_base_path": str(ssh.get("remote_base_path") or "").strip().rstrip("/"),
    }


def _status(status: str, message: str, **kwargs: Any) -> dict[str, Any]:
    data = {"version": 1, "target": "truenas", "status": status, "message": message, "created_at": utc_now()}
    data.update(kwargs)
    return data


# ─── SSH connectivity ──────────────────────────────────────────────────────────


def _ssh_command(ssh: dict[str, Any], *, extra_flags: list[str] | None = None) -> list[str]:
    """Build base ssh command from config."""
    cmd = ["ssh"]
    if ssh["identity_file"] and os.path.isfile(ssh["identity_file"]):
        cmd += ["-i", ssh["identity_file"]]
    elif ssh["password"]:
        # Use sshpass if password is set and no key available
        pass_cmd = ["sshpass", "-p", ssh["password"]]
        cmd = pass_cmd + cmd
    cmd += [
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=10",
        "-o", "BatchMode=yes" if not ssh["password"] else "PasswordAuthentication=yes",
        "-p", str(ssh["port"]),
    ]
    if extra_flags:
        cmd += extra_flags
    return cmd


def _ssh_dest(ssh: dict[str, Any]) -> str:
    """Return user@host for rsync."""
    return f"{ssh['user']}@{ssh['host']}"


def _check_ssh_reachable(ssh: dict[str, Any]) -> tuple[bool, str]:
    """Quick SSH connectivity probe. Returns (ok, message)."""
    if not ssh["host"] or not ssh["user"]:
        return False, "SSH host/user not configured"

    cmd = _ssh_command(ssh) + [_ssh_dest(ssh), "echo SSH_OK"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        if result.returncode == 0 and "SSH_OK" in result.stdout:
            return True, "SSH connection successful"
        stderr = result.stderr.strip()
        if "Permission denied" in stderr:
            return False, "SSH authentication failed (Permission denied)"
        if "Connection refused" in stderr:
            return False, f"SSH connection refused on port {ssh['port']}"
        if "Host key verification failed" in stderr:
            return False, "SSH host key verification failed"
        return False, f"SSH probe failed: {stderr or 'exit code ' + str(result.returncode)}"
    except subprocess.TimeoutExpired:
        return False, "SSH connection timed out"
    except FileNotFoundError:
        return False, "ssh command not found on this system"
    except Exception as exc:
        return False, f"SSH probe error: {exc}"


def _shell_quote(s: str) -> str:
    """Minimal POSIX shell quoting."""
    return "'" + s.replace("'", "'\\''") + "'"


# ─── Remote file checks (SSH) ──────────────────────────────────────────────────


def _ssh_file_exists(ssh: dict[str, Any], remote_path: str) -> bool:
    """Check if a file exists on the remote via SSH."""
    cmd = _ssh_command(ssh) + [_ssh_dest(ssh), f"test -f {_shell_quote(remote_path)}"]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=10).returncode == 0
    except Exception:
        return False


def _ssh_sha256(ssh: dict[str, Any], remote_path: str) -> str:
    """Compute SHA256 of a remote file via SSH."""
    cmd = _ssh_command(ssh) + [_ssh_dest(ssh), f"sha256sum {_shell_quote(remote_path)}"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            return result.stdout.strip().split()[0]
    except Exception:
        pass
    return ""


def _ssh_disk_usage(ssh: dict[str, Any]) -> tuple[int, int]:
    """Get (total_bytes, free_bytes) from remote via SSH df."""
    remote_base = ssh["remote_base_path"]
    cmd = _ssh_command(ssh) + [_ssh_dest(ssh), f"df -B1 --output=size,avail {_shell_quote(remote_base)} | tail -1"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            parts = result.stdout.strip().split()
            if len(parts) >= 2:
                return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return 0, 0


# ─── Core functions ────────────────────────────────────────────────────────────


def get_truenas_status(agentlab_root: Path, *, write_probe: bool = True) -> dict[str, Any]:
    """Return TrueNAS connectivity status (SSH or SMB mount)."""
    agentlab_root = Path(agentlab_root).resolve()
    cfg = _truenas_config(agentlab_root)
    enabled = bool(cfg.get("enabled", False))
    transport = _transport_mode(cfg)
    protocol_url = str(cfg.get("protocol_url") or "")

    if not enabled:
        return _status("warn", "TrueNAS target disabled", enabled=False, transport=transport, protocol_url=protocol_url)

    if transport == "ssh":
        return _ssh_status(cfg, transport=transport, protocol_url=protocol_url, write_probe=write_probe)
    else:
        return _smb_status(cfg, transport=transport, protocol_url=protocol_url, write_probe=write_probe)


def _ssh_status(cfg: dict[str, Any], *, transport: str, protocol_url: str, write_probe: bool) -> dict[str, Any]:
    """Status check for SSH transport mode."""
    ssh = _ssh_config(cfg)
    enabled = bool(cfg.get("enabled", False))

    if not ssh["host"] or not ssh["user"]:
        return _status("fail", "SSH host/user not configured", enabled=enabled, transport=transport,
                       protocol_url=protocol_url, ssh_host=ssh["host"], ssh_user=ssh["user"])

    remote_base = ssh["remote_base_path"]
    if not remote_base:
        return _status("fail", "SSH remote_base_path not configured", enabled=enabled, transport=transport,
                       protocol_url=protocol_url, ssh_host=ssh["host"], ssh_user=ssh["user"])

    has_key = bool(ssh["identity_file"] and os.path.isfile(ssh["identity_file"]))
    has_pass = bool(ssh["password"])
    if not has_key and not has_pass:
        return _status("fail", "No SSH auth configured (set identity_file or AGENTLAB_TRUENAS_PASSWORD env var)",
                       enabled=enabled, transport=transport, protocol_url=protocol_url,
                       ssh_host=ssh["host"], ssh_user=ssh["user"])

    reachable, msg = _check_ssh_reachable(ssh)
    if not reachable:
        return _status("fail", msg, enabled=enabled, transport=transport, protocol_url=protocol_url,
                       ssh_host=ssh["host"], ssh_user=ssh["user"])

    # Check remote path exists
    cmd = _ssh_command(ssh) + [_ssh_dest(ssh), f"test -d {_shell_quote(remote_base)}"]
    path_exists = False
    try:
        path_exists = subprocess.run(cmd, capture_output=True, timeout=10).returncode == 0
    except Exception:
        pass

    if not path_exists:
        return _status("fail", f"Remote path does not exist: {remote_base}", enabled=enabled, transport=transport,
                       protocol_url=protocol_url, ssh_host=ssh["host"], ssh_user=ssh["user"],
                       remote_base_path=remote_base, mounted=False)

    # Check writable
    writable: bool | None = None
    probe_error = ""
    if write_probe:
        writable = False
        probe_file = f"{remote_base}/.agentlab_probe/ssh_probe_{os.getpid()}_{int(datetime.now().timestamp())}.tmp"
        try:
            mkdir_cmd = _ssh_command(ssh) + [_ssh_dest(ssh), f"mkdir -p {_shell_quote(remote_base + '/.agentlab_probe')}"]
            subprocess.run(mkdir_cmd, capture_output=True, timeout=10)
            write_cmd = _ssh_command(ssh) + [_ssh_dest(ssh),
                                             f"echo ok > {_shell_quote(probe_file)} && rm -f {_shell_quote(probe_file)}"]
            wr = subprocess.run(write_cmd, capture_output=True, timeout=10)
            writable = wr.returncode == 0
        except Exception as exc:
            probe_error = str(exc)

    total_bytes, free_bytes = _ssh_disk_usage(ssh)

    return _status(
        "pass" if (writable is True or not write_probe) else "fail",
        (
            "SSH connected, remote path writable"
            if writable is True
            else "SSH connected, remote path exists; write probe skipped"
            if not write_probe
            else "SSH connected, remote path not writable"
        ),
        enabled=enabled, transport=transport, protocol_url=protocol_url,
        ssh_host=ssh["host"], ssh_user=ssh["user"],
        mount_path=remote_base,
        remote_base_path=remote_base,
        mounted=path_exists,
        writable=writable,
        write_probe=write_probe,
        probe_error=probe_error,
        total_bytes=total_bytes,
        free_bytes=free_bytes,
    )


def _smb_status(cfg: dict[str, Any], *, transport: str, protocol_url: str, write_probe: bool) -> dict[str, Any]:
    """Status check for legacy SMB mount transport."""
    enabled = bool(cfg.get("enabled", False))
    mount_raw = str(cfg.get("mount_path") or "").strip()
    mount_path = Path(mount_raw).expanduser() if mount_raw else None

    if not mount_raw or mount_path is None:
        return _status("fail", "TrueNAS mount_path is not configured", enabled=enabled, transport=transport,
                       protocol_url=protocol_url, mount_path="")
    if not mount_path.exists():
        return _status("fail", "TrueNAS mount path does not exist", enabled=enabled, transport=transport,
                       protocol_url=protocol_url, mount_path=str(mount_path), mounted=False)
    if not mount_path.is_dir():
        return _status("fail", "TrueNAS mount path is not a directory", enabled=enabled, transport=transport,
                       protocol_url=protocol_url, mount_path=str(mount_path), mounted=False)

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
        enabled=enabled, transport=transport, protocol_url=protocol_url,
        mount_path=str(mount_path), mounted=True, writable=writable,
        write_probe=write_probe, probe_error=probe_error,
        total_bytes=total_bytes, free_bytes=free_bytes,
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
        "transport": report.get("transport", ""),
        "status": report.get("status", "unknown"),
        "dry_run": bool(report.get("dry_run", False)),
        "copied_files": report.get("copied_files", 0),
        "would_copy_files": report.get("would_copy_files", 0),
        "skipped_existing": report.get("skipped_existing", 0),
        "failed_files": report.get("failed_files", 0),
        "manifest": report.get("manifest_path", ""),
    }
    ledger.setdefault("entries", []).append(entry)
    atomic_write_yaml(ledger_path, ledger)


# ═══════════════════════════════════════════════════════════════════════════════
# Task type detection & routing
# ═══════════════════════════════════════════════════════════════════════════════

TASK_CLASS_DEFAULTS: dict[str, dict[str, Any]] = {
    "code_reading":      {"remote_subpath": "tasks/code_reading",      "trigger": "on_task_complete", "retention_days": 30},
    "code_development":  {"remote_subpath": "tasks/code_development",  "trigger": "on_file_change",   "retention_days": 0},
    "video_generation":  {"remote_subpath": "tasks/video_generation",  "trigger": "on_milestone",     "retention_days": 0},
    "content_writing":   {"remote_subpath": "tasks/content_writing",   "trigger": "on_file_change",   "retention_days": 90},
    "research":          {"remote_subpath": "tasks/research",          "trigger": "on_task_complete", "retention_days": 90},
    "system":            {"remote_subpath": "tasks/system",            "trigger": "on_file_change",   "retention_days": 0},
}


def _load_task_classification(agentlab_root: Path) -> dict[str, Any]:
    """Load task_classification from backup_policy.yml."""
    policy = _load_backup_policy(agentlab_root)
    return policy.get("task_classification", {}) if policy else {}


def _detect_task_type(agentlab_root: Path, project: str, task_id: str) -> str:
    """Detect task type from task metadata.

    Checks in order:
    1. workflow_plan.yml → task_type field
    2. task_card.yml → task_type field
    3. user_request.md → keyword matching (fallback)
    4. Defaults to 'system'
    """
    run_dir = agentlab_root / "projects" / project / "runs" / task_id

    # 1. workflow_plan.yml
    plan_path = run_dir / "workflow_plan.yml"
    if plan_path.exists():
        plan = safe_read_yaml(plan_path, {})
        if isinstance(plan, dict):
            tt = plan.get("task_type", "")
            if tt and tt in TASK_CLASS_DEFAULTS:
                return tt

    # 2. task_card.yml
    card_path = run_dir / "task_card.yml"
    if card_path.exists():
        card = safe_read_yaml(card_path, {})
        if isinstance(card, dict):
            tt = card.get("task_type", "")
            if tt and tt in TASK_CLASS_DEFAULTS:
                return tt

    # 3. Keyword matching from user request
    request_path = run_dir / "user_request.md"
    if request_path.exists():
        text = request_path.read_text(encoding="utf-8").lower()
        kw_map = {
            "code_reading":     ["读代码", "查看代码", "阅读仓库", "探索代码", "code reading",
                                 "code review", "检查代码", "understand repo", "explore repo"],
            "code_development": ["修改代码", "写代码", "实现", "重构", "fix bug", "debug",
                                 "implement", "refactor", "开发", "改动", "添加功能"],
            "video_generation": ["短剧", "漫剧", "视频生成", "AI视频", "视频制作", "comic",
                                 "video", "drama", "脚本", "分镜", "角色设定", "配音"],
            "content_writing":  ["写文章", "写作", "文档", "报告", "翻译", "writing", "content",
                                 "documentation", "article", "report"],
            "research":         ["调研", "搜索", "研究", "市场分析", "调查", "research",
                                 "search", "analysis", "market", "资料收集"],
        }
        scores: dict[str, int] = {}
        for tt, keywords in kw_map.items():
            scores[tt] = sum(1 for kw in keywords if kw in text)
        best = max(scores, key=scores.get) if scores else "system"
        if scores.get(best, 0) > 0 and best in TASK_CLASS_DEFAULTS:
            return best

    # 4. Default
    return "system"


def _get_task_type_config(agentlab_root: Path, task_type: str) -> dict[str, Any]:
    """Get the full task type config, merging defaults with policy overrides."""
    classification = _load_task_classification(agentlab_root)
    defaults = dict(TASK_CLASS_DEFAULTS.get(task_type, TASK_CLASS_DEFAULTS["system"]))
    overrides = classification.get(task_type, {}) if classification else {}
    return _deep_merge(defaults, overrides)


def _build_memory_sync_items(agentlab_root: Path, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Build sync items for config, templates, skills, repository, and project memory."""
    items: list[dict[str, Any]] = []
    remote_memory = "memory"  # remote base for memory

    # Global config → memory/global/config/
    config_dir = agentlab_root / "config"
    if config_dir.is_dir():
        items.append({
            "local_path": str(config_dir),
            "local_abs": config_dir,
            "remote_path": f"{remote_memory}/global/config/",
            "item_type": "memory",
        })

    # Agent templates → memory/global/agent_templates/
    tmpl_dir = agentlab_root / "agent_templates"
    if tmpl_dir.is_dir():
        items.append({
            "local_path": str(tmpl_dir),
            "local_abs": tmpl_dir,
            "remote_path": f"{remote_memory}/global/agent_templates/",
            "item_type": "memory",
        })

    # Skills → memory/global/skills/
    skills_dir = agentlab_root / "skills"
    if skills_dir.is_dir():
        items.append({
            "local_path": str(skills_dir),
            "local_abs": skills_dir,
            "remote_path": f"{remote_memory}/global/skills/",
            "item_type": "memory",
        })

    # Repository HandOff mirrors → memory/repositories/
    repository_memory = agentlab_root / "memory" / "repositories"
    if repository_memory.is_dir():
        items.append({
            "local_path": str(repository_memory),
            "local_abs": repository_memory,
            "remote_path": f"{remote_memory}/repositories/",
            "item_type": "memory",
        })

    # Project agent_docs → memory/projects/<Project>/agent_docs/
    projects_dir = agentlab_root / "projects"
    if projects_dir.is_dir():
        for proj_dir in sorted(projects_dir.iterdir()):
            if not proj_dir.is_dir():
                continue
            agent_docs = proj_dir / "agent_docs"
            if agent_docs.is_dir():
                items.append({
                    "local_path": str(agent_docs),
                    "local_abs": agent_docs,
                    "remote_path": f"{remote_memory}/projects/{proj_dir.name}/agent_docs/",
                    "item_type": "memory",
                })

    return items


def _build_task_sync_items(
    agentlab_root: Path, project: str, task_id: str | None,
) -> list[dict[str, Any]]:
    """Build sync item list for task artifact backup, categorized by task type."""
    items: list[dict[str, Any]] = []
    projects_dir = agentlab_root / "projects"

    if not projects_dir.is_dir():
        return items

    # If specific task_id → sync that one
    if task_id:
        run_dir = projects_dir / project / "runs" / task_id
        if run_dir.is_dir():
            task_type = _detect_task_type(agentlab_root, project, task_id)
            tt_config = _get_task_type_config(agentlab_root, task_type)
            remote_subpath = tt_config.get("remote_subpath", f"tasks/{task_type}")
            items.append({
                "local_path": str(run_dir),
                "local_abs": run_dir,
                "remote_path": f"{remote_subpath}/{task_id}/",
                "item_type": "task",
                "task_type": task_type,
                "task_id": task_id,
            })
        return items

    # No specific task_id → sync all tasks under all projects
    for proj_dir in sorted(projects_dir.iterdir()):
        if not proj_dir.is_dir() or proj_dir.name.startswith("."):
            continue
        runs_dir = proj_dir / "runs"
        if not runs_dir.is_dir():
            continue
        for task_dir in sorted(runs_dir.iterdir()):
            if not task_dir.is_dir():
                continue
            tid = task_dir.name
            task_type = _detect_task_type(agentlab_root, proj_dir.name, tid)
            tt_config = _get_task_type_config(agentlab_root, task_type)
            remote_subpath = tt_config.get("remote_subpath", f"tasks/{task_type}")
            items.append({
                "local_path": str(task_dir),
                "local_abs": task_dir,
                "remote_path": f"{remote_subpath}/{tid}/",
                "item_type": "task",
                "task_type": task_type,
                "task_id": tid,
            })

    return items


def _build_rsync_command(
    ssh: dict[str, Any],
    local_path: Path,
    remote_target: str,
    dry_run: bool,
) -> list[str]:
    """Build rsync command for SSH transport."""
    remote_base = ssh["remote_base_path"]
    # Build rsync -e with the correct SSH command
    ssh_cmd_parts = ["ssh"]
    if ssh["identity_file"] and os.path.isfile(ssh["identity_file"]):
        ssh_cmd_parts += ["-i", ssh["identity_file"]]
    elif ssh["password"]:
        # sshpass wrapper for rsync
        # rsync -e "sshpass -p PASSWORD ssh" ...
        ssh_cmd_parts = ["sshpass", "-p", ssh["password"], "ssh"] + ssh_cmd_parts[1:]

    ssh_cmd_parts += [
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=10",
        "-p", str(ssh["port"]),
    ]
    ssh_cmd_str = " ".join(ssh_cmd_parts)

    cmd = [
        "rsync",
        "--recursive",
        "--times",                # preserve modification times
        "--ignore-existing",      # NEVER overwrite remote files
        "--progress",             # human-readable output
        "--itemize-changes",      # detailed per-file reporting
        "-e", ssh_cmd_str,
    ]

    # Build exclude patterns
    for exc in DEFAULT_EXCLUDES:
        cmd += ["--exclude", exc.rstrip("/**").rstrip("/")]

    if dry_run:
        cmd += ["--dry-run"]

    # Source: local_path (with trailing slash = copy contents)
    cmd.append(str(local_path) + "/")

    # Destination: remote
    cmd.append(f"{_ssh_dest(ssh)}:{ssh['remote_base_path']}/{remote_target}/")

    return cmd


def _parse_rsync_itemize(line: str) -> dict[str, Any] | None:
    """Parse a single rsync --itemize-changes line into {action, path, details}."""
    # Format: YXcstpoguax  path
    # e.g., ">f+++++++++ projects/AgentLab/agent_docs/foo.md"
    #        ">f.st...... projects/..."  (sent, size/times differ)
    #        ".d..t...... projects/..."  (dir, time updated)
    if len(line) < 11:
        return None
    flags = line[:11]
    path = line[11:].strip()
    if not path:
        return None

    update_type = flags[0]  # > = local→remote, < = remote→local, . = no update
    file_type = flags[1]    # f = file, d = dir, L = symlink

    action = "skipped"
    if update_type == ">":
        action = "copied"
    elif update_type == "<":
        action = "skipped_remote_newer"
    elif flags == ".d..t......":
        action = "dir_touch"

    if file_type == "d":
        action = "skip_dir" if action == "skipped" else action

    return {"action": action, "path": path, "file_type": file_type, "flags": flags}


def run_truenas_sync(
    agentlab_root: Path,
    project: str,
    task_id: str,
    *,
    dry_run: bool = True,
    execute: bool = False,
    write_probe: bool = True,
) -> dict[str, Any]:
    """Run a TrueNAS dry-run or execute sync and write local reports.

    Supports both SSH and SMB mount transport modes.
    """
    agentlab_root = Path(agentlab_root).resolve()
    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    cfg = _truenas_config(agentlab_root)
    transport = _transport_mode(cfg)
    status = get_truenas_status(agentlab_root, write_probe=write_probe)
    effective_dry_run = not execute or dry_run
    if execute:
        effective_dry_run = False

    manifest_path = f"runs/{task_id}/truenas_manifest.yml"
    report: dict[str, Any] = {
        "version": 1,
        "target": "truenas",
        "transport": transport,
        "project": project,
        "task_id": task_id,
        "created_at": utc_now(),
        "dry_run": effective_dry_run,
        "status": "failed",
        "protocol_url": status.get("protocol_url") or cfg.get("protocol_url", ""),
        "mount_path": status.get("mount_path", ""),
        "remote_base_path": status.get("remote_base_path", ""),
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
        "transport": transport,
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

    # ── Dispatch by transport mode ──────────────────────────────────────────
    if transport == "ssh":
        return _run_ssh_sync(agentlab_root, project, task_id, run_dir, cfg, status, report, manifest, effective_dry_run)
    else:
        return _run_smb_sync(agentlab_root, project, task_id, run_dir, cfg, status, report, manifest, effective_dry_run)


def _run_ssh_sync(
    agentlab_root: Path,
    project: str,
    task_id: str,
    run_dir: Path,
    cfg: dict[str, Any],
    status: dict[str, Any],
    report: dict[str, Any],
    manifest: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    """Execute sync via rsync over SSH — memory + task artifacts with type routing."""
    ssh = _ssh_config(cfg)

    # ── Phase 1: Memory backup (config, templates, skills, agent_docs) ──
    memory_items = _build_memory_sync_items(agentlab_root, cfg)

    # ── Phase 2: Task artifact backup (per task type) ──
    task_items = _build_task_sync_items(agentlab_root, project, task_id)

    all_items = memory_items + task_items
    commands: list[dict[str, Any]] = []

    for item in all_items:
        local_path = item["local_abs"]
        remote_target = item["remote_path"]
        item_type = item.get("item_type", "unknown")

        rsync_cmd = _build_rsync_command(ssh, local_path, remote_target, dry_run)
        commands.append({
            "item_type": item_type,
            "local": str(local_path),
            "remote": remote_target,
            "task_type": item.get("task_type", ""),
            "task_id": item.get("task_id", ""),
            "command": " ".join(rsync_cmd),
            "cmd_list": rsync_cmd,                 # preserve list for subprocess
        })

    report["sync_phases"] = commands
    report["memory_items"] = len(memory_items)
    report["task_items"] = len(task_items)

    total_copied = 0
    total_would_copy = 0
    total_skipped = 0
    total_failed = 0

    for cmd_info in commands:
        cmd_list = cmd_info.get("cmd_list", [])
        if not cmd_list:
            continue

        try:
            result = subprocess.run(cmd_list, capture_output=True, text=True, timeout=120)
            output = result.stdout
            errors = result.stderr

            if errors.strip():
                report["warnings"].append(f"[{cmd_info['item_type']}] rsync stderr: {errors.strip()[:200]}")

            # Parse itemize-changes output
            copied = 0
            skipped = 0
            would_copy = 0
            failed = 0
            for line in output.strip().split("\n"):
                if not line.strip() or line.startswith("sending") or line.startswith("receiving") or line.startswith("sent"):
                    continue
                parsed = _parse_rsync_itemize(line)
                if parsed is None:
                    continue
                if dry_run and parsed["action"] == "copied":
                    would_copy += 1
                elif parsed["action"] == "copied":
                    copied += 1
                elif parsed["action"] in ("skipped", "skipped_remote_newer"):
                    skipped += 1
                elif parsed["action"] == "failed":
                    failed += 1
                manifest["files"].append({
                    "remote_path": parsed["path"],
                    "action": parsed["action"],
                    "file_type": parsed.get("file_type", ""),
                    "item_type": cmd_info["item_type"],
                    "task_type": cmd_info.get("task_type", ""),
                })

            total_copied += copied
            total_would_copy += would_copy
            total_skipped += skipped
            total_failed += failed

        except subprocess.TimeoutExpired:
            total_failed += 1
            report["blocking_reasons"].append(f"[{cmd_info['item_type']}] rsync timed out: {cmd_info['remote']}")
        except Exception as exc:
            total_failed += 1
            report["blocking_reasons"].append(f"[{cmd_info['item_type']}] rsync error: {exc}")

    report["copied_files"] = total_copied
    report["would_copy_files"] = total_would_copy
    report["skipped_existing"] = total_skipped
    report["failed_files"] = total_failed

    if total_failed:
        report["status"] = "partial"
    elif dry_run:
        report["status"] = "dry_run_completed"
    else:
        report["status"] = "synced"

    manifest["summary"] = {
        "total_candidates": total_copied + total_would_copy + total_skipped,
        "would_copy": total_would_copy,
        "copied": total_copied,
        "skipped_existing": total_skipped,
        "failed": total_failed,
        "excluded": report.get("excluded_files", 0),
        "missing_sources": 0,
        "memory_items": len(memory_items),
        "task_items": len(task_items),
    }

    _write_reports(run_dir, report, manifest)
    _update_sync_ledger(agentlab_root, project, report)
    return report


def _run_smb_sync(
    agentlab_root: Path,
    project: str,
    task_id: str,
    run_dir: Path,
    cfg: dict[str, Any],
    status: dict[str, Any],
    report: dict[str, Any],
    manifest: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    """Execute sync via legacy SMB mount + shutil.copy2."""
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

        if dry_run:
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
    elif dry_run:
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
