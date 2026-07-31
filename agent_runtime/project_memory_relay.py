"""Safe continuous relay sync for project memory files.

Only files below ``projects/*/agent_docs`` are eligible.  Existing remote
files are versioned before replacement, newer remote files are preserved, and
an executed transfer is accepted only after a remote SHA-256 verification.
"""

from __future__ import annotations

from datetime import datetime, timezone
from fnmatch import fnmatch
from hashlib import sha256
import math
from pathlib import Path
import os
import re
import shlex
import subprocess
import tempfile
import time
from typing import Any, Callable

from atomic_io import atomic_write_json, atomic_write_text
from truenas_sync import (
    _shell_quote,
    _ssh_command,
    _ssh_config,
    _ssh_dest,
    _transport_mode,
    _truenas_config,
    _load_backup_policy,
)


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def project_memory_remote_path(agentlab_root: Path, local_path: Path) -> str | None:
    """Map an eligible local project-memory file to its bounded relay path."""
    root = Path(agentlab_root).resolve()
    source = Path(local_path)
    if source.is_symlink() or not source.is_file():
        return None
    try:
        relative = source.resolve().relative_to(root)
    except ValueError:
        return None
    parts = relative.parts
    if len(parts) < 4 or parts[0] != "projects" or parts[2] != "agent_docs":
        return None
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return (Path("memory") / relative).as_posix()


def _result(status: str, message: str, **values: Any) -> dict[str, Any]:
    result = {
        "version": 1,
        "status": status,
        "message": message,
        "created_at": _utc_now(),
    }
    result.update(values)
    return result


def _governed_memory_names(agentlab_root: Path) -> set[str]:
    from config_loader import load_agentlab_configs

    configs = load_agentlab_configs(agentlab_root)
    configured = (
        configs.get("memory_policy", {})
        .get("records", {})
        .get("project_memory", [])
    )
    return {str(name).lstrip("/") for name in configured}


def _is_excluded(agentlab_root: Path, path: Path) -> bool:
    cfg = _truenas_config(agentlab_root)
    patterns = [str(item) for item in (cfg.get("exclude") or [])]
    relative = path.resolve().relative_to(agentlab_root.resolve()).as_posix()
    return any(fnmatch(relative, pattern) or fnmatch(path.name, pattern) for pattern in patterns)


def _is_governed_memory_file(agentlab_root: Path, path: Path) -> bool:
    remote = project_memory_remote_path(agentlab_root, path)
    if remote is None or _is_excluded(agentlab_root, path):
        return False
    parts = Path(remote).parts
    memory_relative = Path(*parts[4:]).as_posix()
    return memory_relative in _governed_memory_names(agentlab_root)


def iter_project_memory_files(agentlab_root: Path) -> list[Path]:
    """Return regular, non-symlink files below every project agent_docs dir."""
    root = Path(agentlab_root).resolve()
    candidates: list[Path] = []
    projects = root / "projects"
    if not projects.is_dir():
        return candidates
    for agent_docs in sorted(projects.glob("*/agent_docs")):
        if agent_docs.is_symlink() or not agent_docs.is_dir():
            continue
        candidates.extend(
            path
            for path in sorted(agent_docs.rglob("*"))
            if path.is_file()
            and not path.is_symlink()
            and _is_governed_memory_file(root, path)
        )
    return candidates


def _snapshot(agentlab_root: Path) -> dict[str, tuple[int, int, str]]:
    snapshot: dict[str, tuple[int, int, str]] = {}
    for path in iter_project_memory_files(agentlab_root):
        try:
            content, stat = _read_stable_source(path)
        except (FileNotFoundError, OSError, RuntimeError):
            continue
        snapshot[str(path)] = (
            stat.st_mtime_ns,
            stat.st_size,
            sha256(content).hexdigest(),
        )
    return snapshot


def _write_status(agentlab_root: Path, report: dict[str, Any]) -> None:
    status_path = (
        Path(agentlab_root).resolve()
        / ".agentlab_runtime"
        / "relay_memory_sync"
        / "status.json"
    )
    atomic_write_json(status_path, report)


def _read_stable_source(path: Path, attempts: int = 3) -> tuple[bytes, os.stat_result]:
    """Read bytes whose size and mtime stayed stable across the read."""
    for _ in range(attempts):
        before = path.stat()
        content = path.read_bytes()
        after = path.stat()
        if (
            before.st_ino == after.st_ino
            and before.st_size == after.st_size == len(content)
            and before.st_mtime_ns == after.st_mtime_ns
        ):
            return content, after
    raise RuntimeError("project-memory source changed repeatedly while being snapshotted")


def _version_counter_path(agentlab_root: Path, remote_relative: str) -> Path:
    key = sha256(remote_relative.encode("utf-8")).hexdigest()
    return (
        Path(agentlab_root).resolve()
        / ".agentlab_runtime"
        / "relay_memory_sync"
        / "version_slots"
        / f"{key}.txt"
    )


def _next_version_slot(agentlab_root: Path, remote_relative: str, max_versions: int) -> int:
    """Preview the next per-file history slot without advancing it."""
    counter_path = _version_counter_path(agentlab_root, remote_relative)
    try:
        previous = int(counter_path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        previous = -1
    return (previous + 1) % max_versions


def _commit_version_slot(agentlab_root: Path, remote_relative: str, slot: int) -> None:
    atomic_write_text(_version_counter_path(agentlab_root, remote_relative), f"{slot}\n")


def watcher_interval_seconds(agentlab_root: Path, requested: int | None = None) -> int:
    """Resolve the watcher interval without violating configured rate limits."""
    root = Path(agentlab_root).resolve()
    policy = _load_backup_policy(root)
    cfg = _truenas_config(root)
    continuous = cfg.get("continuous_project_memory") or {}
    frequency = policy.get("sync_frequency", {})
    global_frequency = frequency.get("global", {})
    trigger_frequency = frequency.get("by_trigger", {}).get("on_file_change", {})
    max_per_hour = max(1, int(global_frequency.get("max_sync_per_hour") or 60))
    policy_floor = max(
        int(global_frequency.get("debounce_seconds") or 0),
        int(global_frequency.get("batch_window_seconds") or 0),
        int(trigger_frequency.get("cooldown_between_syncs_seconds") or 0),
        math.ceil(3600 / max_per_hour),
    )
    return max(
        policy_floor,
        int(requested or continuous.get("interval_seconds") or policy_floor),
    )


def sync_project_memory_file(
    agentlab_root: Path,
    local_path: Path,
    *,
    execute: bool = False,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Serialize and snapshot one governed memory file before remote I/O."""
    import fcntl

    root = Path(agentlab_root).resolve()
    source = Path(local_path).resolve()
    remote_relative = project_memory_remote_path(root, source)
    if remote_relative is None:
        return _result(
            "rejected",
            "path is outside projects/*/agent_docs",
            local_path=str(source),
        )
    if not _is_governed_memory_file(root, source):
        return _result(
            "rejected",
            "path is excluded or is not a governed project-memory record",
            local_path=str(source),
            remote_path=remote_relative,
        )

    runtime_dir = root / ".agentlab_runtime" / "relay_memory_sync"
    lock_dir = runtime_dir / "file_locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_key = sha256(remote_relative.encode("utf-8")).hexdigest()
    with (lock_dir / f"{lock_key}.lock").open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            content, source_stat = _read_stable_source(source)
        except (OSError, RuntimeError) as exc:
            return _result(
                "error",
                f"stable source snapshot failed: {exc}",
                local_path=str(source),
                remote_path=remote_relative,
            )
        runtime_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="snapshot-", dir=runtime_dir) as temp_dir:
            snapshot = Path(temp_dir) / source.name
            snapshot.write_bytes(content)
            snapshot.chmod(0o600)
            os.utime(snapshot, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
            return _sync_project_memory_snapshot(
                root,
                source,
                snapshot,
                execute=execute,
                runner=runner,
            )


def _sync_project_memory_snapshot(
    agentlab_root: Path,
    local_path: Path,
    snapshot_path: Path,
    *,
    execute: bool = False,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Safely sync one project memory file to the configured SSH relay."""
    root = Path(agentlab_root).resolve()
    source = Path(local_path).resolve()
    remote_relative = project_memory_remote_path(root, source)
    if remote_relative is None:
        return _result(
            "rejected",
            "path is outside projects/*/agent_docs",
            local_path=str(source),
        )
    if not _is_governed_memory_file(root, source):
        return _result(
            "rejected",
            "path is excluded or is not a governed project-memory record",
            local_path=str(source),
            remote_path=remote_relative,
        )

    cfg = _truenas_config(root)
    continuous = cfg.get("continuous_project_memory") or {}
    if not cfg.get("enabled") or not continuous.get("enabled"):
        return _result(
            "disabled",
            "continuous project-memory relay sync is disabled",
            local_path=str(source),
            remote_path=remote_relative,
        )
    if _transport_mode(cfg) != "ssh":
        return _result(
            "error",
            "continuous project-memory relay sync requires SSH transport",
            local_path=str(source),
            remote_path=remote_relative,
        )

    ssh = _ssh_config(cfg)
    if not ssh["host"] or not ssh["user"] or not ssh["remote_base_path"]:
        return _result(
            "error",
            "SSH host, user, and remote_base_path are required",
            local_path=str(source),
            remote_path=remote_relative,
        )

    snapshot = Path(snapshot_path).resolve()
    digest = sha256(snapshot.read_bytes()).hexdigest()
    endpoint_id = str(continuous.get("endpoint_id") or "endpoint").strip() or "endpoint"
    if re.fullmatch(r"[A-Za-z0-9_.-]+", endpoint_id) is None:
        return _result(
            "error",
            "continuous_project_memory.endpoint_id contains unsafe characters",
            local_path=str(source),
            remote_path=remote_relative,
            sha256=digest,
        )
    policy = _load_backup_policy(root)
    project_memory_policy = (
        policy.get("memory_backup", {}).get("project_memory", {})
    )
    update_policy = str(
        continuous.get("existing_remote")
        or "version_then_update_if_local_not_older"
    )
    if update_policy != "version_then_update_if_local_not_older":
        return _result(
            "error",
            f"unsupported continuous project-memory update policy: {update_policy}",
            local_path=str(source),
            remote_path=remote_relative,
            sha256=digest,
        )
    conflict_policy = str(continuous.get("conflict_policy") or "preserve_remote_newer")
    if conflict_policy != "preserve_remote_newer":
        return _result(
            "error",
            f"unsupported continuous project-memory conflict policy: {conflict_policy}",
            local_path=str(source),
            remote_path=remote_relative,
            sha256=digest,
        )
    remote_history = bool(continuous.get("remote_history", True))
    if not remote_history:
        return _result(
            "error",
            "versioned project-memory updates require remote_history=true",
            local_path=str(source),
            remote_path=remote_relative,
            sha256=digest,
        )
    max_versions = max(
        1,
        int(
            continuous.get("max_versions")
            or project_memory_policy.get("max_versions")
            or 10
        ),
    )
    remote_file = f"{ssh['remote_base_path']}/{remote_relative}"
    remote_parent = str(Path(remote_file).parent).replace("\\", "/")
    remote_lock_dir = f"{ssh['remote_base_path']}/shared_protocols/locks/project_memory"
    remote_lock_id = sha256(remote_file.encode("utf-8")).hexdigest()
    remote_lock_file = f"{remote_lock_dir}/{remote_lock_id}.lock"
    receipt_dir = (
        f"{ssh['remote_base_path']}/memory/receipts/project_memory/{endpoint_id}"
    )
    receipt_retention_hours = max(
        1, int(continuous.get("receipt_retention_hours") or 24)
    )
    receipt_id = f"{remote_lock_id}-{os.getpid()}-{time.time_ns()}"
    receipt_file = f"{receipt_dir}/{receipt_id}.sha256"
    destination = f"{_ssh_dest(ssh)}:{remote_parent}/"
    common = {
        "capture_output": True,
        "text": True,
        "timeout": 30,
    }

    if not execute:
        inspect_script = (
            f"if test -f {_shell_quote(remote_file)}; then "
            f"stat -c %Y {_shell_quote(remote_file)}; "
            f"sha256sum {_shell_quote(remote_file)}; "
            "else printf 'MISSING\\n'; fi"
        )
        inspect_command = _ssh_command(ssh) + [_ssh_dest(ssh), inspect_script]
        try:
            inspect_result = runner(inspect_command, **common)
        except Exception as exc:
            return _result(
                "error",
                f"remote preview failed: {exc}",
                local_path=str(source),
                remote_path=remote_file,
                sha256=digest,
            )
        if inspect_result.returncode != 0:
            return _result(
                "error",
                f"remote preview failed: {inspect_result.stderr.strip()}",
                local_path=str(source),
                remote_path=remote_file,
                sha256=digest,
            )
        lines = inspect_result.stdout.strip().splitlines()
        if lines == ["MISSING"]:
            status = "would_update"
            message = "new relay file would be created"
            remote_digest = ""
        elif len(lines) >= 2 and lines[0].isdigit():
            remote_mtime = int(lines[0])
            remote_digest = lines[1].split()[0]
            if remote_digest == digest:
                status = "unchanged"
                message = "relay file already current"
            elif remote_mtime > int(snapshot.stat().st_mtime):
                status = "would_conflict"
                message = "newer relay file would be preserved"
            else:
                status = "would_update"
                message = "older relay file would be versioned and updated"
        else:
            return _result(
                "error",
                "remote preview returned an invalid file-state response",
                local_path=str(source),
                remote_path=remote_file,
                sha256=digest,
            )
        return _result(
            status,
            message,
            local_path=str(source),
            remote_path=remote_file,
            sha256=digest,
            remote_sha256=remote_digest,
            verified=remote_digest == digest,
        )

    version_slot = _next_version_slot(root, remote_relative, max_versions)
    backup_dir = (
        f"{ssh['remote_base_path']}/memory/history/{endpoint_id}/"
        f"slot-{version_slot:02d}/{Path(remote_relative).parent.as_posix()}"
    )
    mkdir_paths = [
        _shell_quote(remote_parent),
        _shell_quote(backup_dir),
        _shell_quote(remote_lock_dir),
        _shell_quote(receipt_dir),
    ]
    mkdir_command = _ssh_command(ssh) + [
        _ssh_dest(ssh),
        (
            f"mkdir -p {' '.join(mkdir_paths)} && "
            f"find {_shell_quote(receipt_dir)} -type f "
            "\\( -name '*.sha256' -o -name '*.sha256.tmp' \\) "
            f"-mmin +{receipt_retention_hours * 60} -delete"
        ),
    ]
    try:
        mkdir_result = runner(mkdir_command, **common)
    except Exception as exc:
        return _result(
            "error",
            f"remote directory preparation failed: {exc}",
            local_path=str(source),
            remote_path=remote_file,
            sha256=digest,
        )
    if mkdir_result.returncode != 0:
        return _result(
            "error",
            f"remote directory preparation failed: {mkdir_result.stderr.strip()}",
            local_path=str(source),
            remote_path=remote_file,
            sha256=digest,
        )

    remote_rsync_script = (
        'rsync "$@"; rc=$?; '
        "if test $rc -eq 0; then "
        f"sha256sum {_shell_quote(remote_file)} > {_shell_quote(receipt_file + '.tmp')} "
        f"&& mv {_shell_quote(receipt_file + '.tmp')} {_shell_quote(receipt_file)} "
        "|| rc=70; fi; exit $rc"
    )
    remote_rsync_path = (
        f"flock -x {_shell_quote(remote_lock_file)} "
        f"sh -c {_shell_quote(remote_rsync_script)} sh"
    )
    rsync_command = [
        "rsync",
        "--checksum",
        "--times",
        "--update",
        "--itemize-changes",
        "--protect-args",
        f"--rsync-path={remote_rsync_path}",
        "-e",
        shlex.join(_ssh_command(ssh)),
    ]
    rsync_command[4:4] = ["--backup", f"--backup-dir={backup_dir}"]
    rsync_command.extend([str(snapshot), destination])
    try:
        rsync_result = runner(rsync_command, **common)
    except Exception as exc:
        return _result(
            "error",
            f"rsync failed: {exc}",
            local_path=str(source),
            remote_path=remote_file,
            sha256=digest,
        )
    if rsync_result.returncode != 0:
        return _result(
            "error",
            f"rsync failed: {rsync_result.stderr.strip()}",
            local_path=str(source),
            remote_path=remote_file,
            sha256=digest,
        )

    changed = any(line.startswith(">f") for line in rsync_result.stdout.splitlines())
    if changed:
        _commit_version_slot(root, remote_relative, version_slot)
    verify_command = _ssh_command(ssh) + [
        _ssh_dest(ssh),
        (
            f"cat {_shell_quote(receipt_file)} "
            f"&& rm -f -- {_shell_quote(receipt_file)}"
        ),
    ]
    try:
        verify_result = runner(verify_command, **common)
    except Exception as exc:
        return _result(
            "error",
            f"remote verification failed: {exc}",
            local_path=str(source),
            remote_path=remote_file,
            sha256=digest,
            verified=False,
        )
    if verify_result.returncode != 0:
        return _result(
            "error",
            f"remote verification command failed: {verify_result.stderr.strip()}",
            local_path=str(source),
            remote_path=remote_file,
            sha256=digest,
            verified=False,
        )
    remote_digest = verify_result.stdout.strip().split()[0] if verify_result.stdout.strip() else ""
    if re.fullmatch(r"[0-9a-fA-F]{64}", remote_digest) is None:
        return _result(
            "error",
            "remote verification returned an invalid SHA-256 digest",
            local_path=str(source),
            remote_path=remote_file,
            sha256=digest,
            verified=False,
        )
    if remote_digest != digest:
        return _result(
            "conflict",
            "remote is newer or changed concurrently; remote file was preserved",
            error="remote is newer or changed concurrently; remote file was preserved",
            local_path=str(source),
            remote_path=remote_file,
            sha256=digest,
            remote_sha256=remote_digest,
            verified=False,
        )
    return _result(
        "synced" if changed else "unchanged",
        "relay file synchronized and verified" if changed else "relay file verified current",
        local_path=str(source),
        remote_path=remote_file,
        sha256=digest,
        remote_sha256=remote_digest,
        verified=True,
    )


def sync_all_project_memories(
    agentlab_root: Path,
    *,
    execute: bool = False,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Discover and sync every regular project-memory file in the workspace."""
    root = Path(agentlab_root).resolve()
    candidates = iter_project_memory_files(root)

    files = [
        sync_project_memory_file(root, path, execute=execute, runner=runner)
        for path in candidates
    ]
    problem_statuses = {"error", "conflict", "would_conflict", "rejected", "disabled"}
    problem_count = sum(item["status"] in problem_statuses for item in files)
    if not files:
        status = "empty"
    elif all(item["status"] == "disabled" for item in files):
        status = "disabled"
    elif execute:
        status = "partial" if problem_count else "synced"
    else:
        status = "failed" if problem_count else "dry_run_completed"
    report = _result(
        status,
        "project-memory relay sync completed",
        execute=execute,
        file_count=len(files),
        problem_count=problem_count,
        files=files,
    )
    _write_status(root, report)
    return report


def watch_project_memories(
    agentlab_root: Path,
    *,
    event_run_dir: Path,
    interval_seconds: int | None = None,
    runner: Runner = subprocess.run,
) -> None:
    """Continuously sync new or changed project-memory files until interrupted."""
    import fcntl

    root = Path(agentlab_root).resolve()
    cfg = _truenas_config(root)
    continuous = cfg.get("continuous_project_memory") or {}
    if not cfg.get("enabled") or not continuous.get("enabled"):
        _write_status(
            root,
            _result(
                "disabled",
                "continuous project-memory relay sync is disabled",
                watching=False,
            ),
        )
        raise RuntimeError("continuous project-memory relay sync is disabled")
    interval = watcher_interval_seconds(root, interval_seconds)
    runtime_dir = root / ".agentlab_runtime" / "relay_memory_sync"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    lock_path = runtime_dir / "watcher.lock"
    pending: list[str] = []

    def enqueue(path_text: str) -> None:
        if path_text not in pending:
            pending.append(path_text)

    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("project-memory relay watcher is already running") from exc

        _write_status(
            root,
            _result(
                "starting",
                "project-memory relay watcher is starting",
                watching=True,
                pid=os.getpid(),
                interval_seconds=interval,
                pending_count=0,
            ),
        )
        from task_events import append_task_event

        append_task_event(
            Path(event_run_dir),
            "relay_memory_watcher_started",
            stage="backup",
            message="Continuous project-memory Relay watcher started.",
            payload={"pid": os.getpid(), "interval_seconds": interval},
        )
        failure_message: str | None = None
        try:
            initial = sync_all_project_memories(root, execute=False, runner=runner)
            retry_statuses = {"error", "conflict", "rejected", "disabled"}
            initial_pending_statuses = retry_statuses | {"would_update", "would_conflict"}
            for item in initial["files"]:
                if item["status"] in initial_pending_statuses:
                    enqueue(item["local_path"])
            previous = _snapshot(root)
            _write_status(
                root,
                {
                    **initial,
                    "watching": True,
                    "pid": os.getpid(),
                    "interval_seconds": interval,
                    "pending_count": len(pending),
                },
            )
            while True:
                time.sleep(interval)
                current = _snapshot(root)
                changed = {
                    path
                    for path, signature in current.items()
                    if previous.get(path) != signature
                }
                for path_text in sorted(changed):
                    enqueue(path_text)
                results: list[dict[str, Any]] = []
                scheduled = pending.pop(0) if pending else None
                for path_text in [scheduled] if scheduled else []:
                    path = Path(path_text)
                    if not path.is_file():
                        continue
                    result = sync_project_memory_file(root, path, execute=True, runner=runner)
                    results.append(result)
                    if result["status"] in retry_statuses:
                        enqueue(path_text)
                previous = current
                report = _result(
                    "watching" if not pending else "degraded",
                    "project-memory relay watcher heartbeat",
                    watching=True,
                    pid=os.getpid(),
                    interval_seconds=interval,
                    watched_file_count=len(current),
                    changed_file_count=len(changed),
                    processed_file_count=len(results),
                    pending_count=len(pending),
                    pending_paths=pending,
                    files=results,
                )
                _write_status(root, report)
        except Exception as exc:
            failure_message = str(exc)
            raise
        finally:
            append_task_event(
                Path(event_run_dir),
                "relay_memory_watcher_stopped",
                stage="backup",
                severity=(
                    "FAILED_RECOVERABLE"
                    if failure_message
                    else "RISK_WARNING"
                    if pending
                    else "INFO"
                ),
                message=(
                    f"Continuous project-memory Relay watcher failed: {failure_message}"
                    if failure_message
                    else "Continuous project-memory Relay watcher stopped."
                ),
                payload={
                    "pid": os.getpid(),
                    "pending_count": len(pending),
                    "error": failure_message,
                },
            )
            _write_status(
                root,
                _result(
                    "failed" if failure_message else "stopped",
                    (
                        f"project-memory relay watcher failed: {failure_message}"
                        if failure_message
                        else "project-memory relay watcher stopped"
                    ),
                    watching=False,
                    pid=os.getpid(),
                    pending_count=len(pending),
                ),
            )
