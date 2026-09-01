"""Materialize a human-facing, rebuildable view of governed project results."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import os
import re
import stat
import uuid
from pathlib import Path
from typing import Any

import yaml
from agent_runtime.project_artifact_steward import validate_project_artifact_governance
from agent_runtime.task_runtime_v2 import TaskRuntime


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _validated_identifier(value: str, *, field: str) -> str:
    value = str(value).strip()
    if value in {"", ".", ".."} or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {field}: {value!r}")
    return value


def _is_relative_to(path: Path, boundary: Path) -> bool:
    try:
        path.relative_to(boundary)
    except ValueError:
        return False
    return True


def _assert_no_symlink_ancestry(path: Path, *, boundary: Path) -> None:
    boundary = boundary.resolve(strict=True)
    current = path
    pending: list[Path] = []
    while current != boundary:
        if not _is_relative_to(current, boundary):
            raise ValueError(f"path escapes boundary: {path}")
        pending.append(current)
        current = current.parent
    for item in reversed(pending):
        if item.exists() and item.is_symlink():
            raise ValueError(f"symlink is not allowed in result path: {item}")


def _open_bounded_directory(boundary: Path, directory: Path, *, create: bool) -> int:
    lexical_boundary = boundary.absolute()
    lexical_directory = directory.absolute()
    try:
        relative = lexical_directory.relative_to(lexical_boundary)
    except ValueError as exc:
        raise ValueError("project result directory escaped its repository boundary") from exc
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lexical_boundary, flags)
    try:
        for part in relative.parts:
            if part in {"", ".", ".."} or Path(part).name != part:
                raise ValueError("project result path component is invalid")
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except (OSError, ValueError) as exc:
        os.close(descriptor)
        if isinstance(exc, ValueError):
            raise
        raise ValueError(
            "project result ancestry contains a symlink or invalid directory"
        ) from exc


@contextmanager
def _project_export_lock(root: Path, project: str):
    locks_root = root / "outputs" / ".locks"
    directory_fd = _open_bounded_directory(root, locks_root, create=True)
    lock_fd = os.open(
        f"{project}.lock",
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
        dir_fd=directory_fd,
    )
    try:
        if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
            raise ValueError("project result export lock must be a regular file")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
        os.close(directory_fd)


def _read_regular_file_at(directory_fd: int, leaf: str) -> bytes:
    if not leaf or Path(leaf).name != leaf:
        raise ValueError("project result file name is invalid")
    descriptor = os.open(
        leaf,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=directory_fd,
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("project result source must be a regular file")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _read_bounded_file(root: Path, path: Path) -> bytes:
    directory_fd = _open_bounded_directory(root, path.parent, create=False)
    try:
        return _read_regular_file_at(directory_fd, path.name)
    finally:
        os.close(directory_fd)


def _atomic_write_bytes(root: Path, path: Path, payload: bytes) -> None:
    directory_fd = _open_bounded_directory(root, path.parent, create=True)
    temporary = f".tmp.{uuid.uuid4().hex}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        try:
            existing = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None and not stat.S_ISREG(existing.st_mode):
            raise ValueError(f"managed result path is not a regular file: {path}")
        descriptor = os.open(temporary, flags, 0o600, dir_fd=directory_fd)
        try:
            view = memoryview(payload)
            while view:
                view = view[os.write(descriptor, view) :]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(
            temporary,
            path.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
    finally:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        os.close(directory_fd)


def _unlink_bounded_regular_file(root: Path, path: Path) -> None:
    directory_fd = _open_bounded_directory(root, path.parent, create=False)
    try:
        try:
            observed = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if not stat.S_ISREG(observed.st_mode):
            raise ValueError(f"managed result path is not a regular file: {path}")
        os.unlink(path.name, dir_fd=directory_fd)
    finally:
        os.close(directory_fd)


def _read_governed_payload(
    repo_root: Path,
    task_root: Path,
    item: dict[str, Any],
) -> tuple[bytes, Path, str]:
    relative = Path(str(item.get("path", "")))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("artifact path must be task-relative")
    _assert_no_symlink_ancestry(task_root / relative, boundary=task_root)
    source = task_root / relative
    payload = _read_bounded_file(repo_root, source)
    digest = hashlib.sha256(payload).hexdigest()
    expected = str(item.get("sha256", ""))
    if not expected or digest != expected:
        raise ValueError(f"artifact hash mismatch: {item.get('version_id', 'unknown')}")
    if int(item.get("size_bytes", -1)) != len(payload):
        raise ValueError(f"artifact size mismatch: {item.get('version_id', 'unknown')}")
    return payload, source, digest


def _candidate_items(projection: dict[str, Any]) -> list[dict[str, Any]]:
    raw = projection.get("artifacts", {})
    if not isinstance(raw, dict):
        raise ValueError("rebuilt Task artifacts must be a mapping")
    return [
        dict(item)
        for item in raw.values()
        if isinstance(item, dict)
        and item.get("disposition") == "eligible"
        and item.get("selection_eligible") is True
    ]


def _task_summary(task_id: str, projection: dict[str, Any]) -> dict[str, Any]:
    task = projection.get("task", {})
    work_items = projection.get("work_items", {})
    attempts = projection.get("attempts", {})
    if not isinstance(task, dict) or not isinstance(work_items, dict) or not isinstance(attempts, dict):
        raise ValueError("rebuilt Task projection has invalid task/work-item/attempt state")
    work_item_counts: dict[str, int] = {}
    for item in work_items.values():
        if isinstance(item, dict):
            status = str(item.get("status", "unknown"))
            work_item_counts[status] = work_item_counts.get(status, 0) + 1
    return {
        "task_id": task_id,
        "task_status": str(task.get("status", "unknown")),
        "work_item_counts": work_item_counts,
        "attempt_count": len(attempts),
        "last_event_sequence": int(projection.get("last_event_sequence", 0)),
    }


def _rebuilt_task_projections(
    root: Path,
    *,
    project: str,
    requested_task_id: str | None,
) -> list[tuple[str, Path, dict[str, Any]]]:
    runtime = TaskRuntime(root, project=project)
    tasks_root = runtime.tasks_root
    if not tasks_root.exists():
        if requested_task_id is not None:
            raise ValueError(f"task does not exist: {requested_task_id}")
        return []
    _assert_no_symlink_ancestry(tasks_root, boundary=root)
    task_ids: list[str] = []
    for task_root in sorted(tasks_root.iterdir(), key=lambda path: path.name):
        if not task_root.is_dir() or task_root.is_symlink():
            continue
        events = task_root / "events.jsonl"
        if events.is_file() and not events.is_symlink():
            task_ids.append(_validated_identifier(task_root.name, field="task_id"))
    if requested_task_id is not None and requested_task_id not in task_ids:
        raise ValueError(f"task does not exist: {requested_task_id}")
    return [
        (task_id, tasks_root / task_id, runtime.rebuild_task(task_id))
        for task_id in task_ids
    ]


def _production_payloads(
    repo_root: Path,
    *,
    project: str,
    project_root: Path,
) -> list[tuple[str, Path, Path, bytes, str]]:
    production_root = project_root / "production"
    index_path = project_root / "project_artifact_index.yml"
    if not production_root.exists() or not index_path.is_file() or index_path.is_symlink():
        return []
    if not production_root.is_dir() or production_root.is_symlink():
        raise ValueError("project production root must be a regular directory")
    index = yaml.safe_load(_read_bounded_file(repo_root, index_path).decode("utf-8")) or {}
    records = index.get("artifacts", []) if isinstance(index, dict) else []
    if not isinstance(records, list):
        raise ValueError("project artifact index artifacts must be a list")
    current_records = [
        item
        for item in records
        if isinstance(item, dict) and item.get("status") == "current" and not item.get("evidence_only")
    ]
    source_tasks: set[str] = set()
    source_bindings: dict[str, Path] = {}
    for record in current_records:
        source_task = _validated_identifier(str(record.get("source_task", "")), field="source_task")
        source_run_artifact = Path(str(record.get("source_run_artifact", "")).strip())
        if not source_run_artifact.parts:
            raise ValueError(f"current production artifact missing source_run_artifact: {record.get('artifact_id')}")
        if source_run_artifact.is_absolute() or ".." in source_run_artifact.parts:
            raise ValueError("source_run_artifact must be a run-relative path")
        source_tasks.add(source_task)
        source_bindings[str(record.get("artifact_id", ""))] = (
            project_root / "runs" / source_task / source_run_artifact
        )
    governance_issues: list[str] = []
    for source_task in sorted(source_tasks):
        governance_issues.extend(validate_project_artifact_governance(repo_root, project, source_task))
    if governance_issues:
        raise ValueError("project artifact governance failed: " + "; ".join(sorted(set(governance_issues))))
    payloads: list[tuple[str, Path, Path, bytes, str]] = []
    for record in sorted(
        current_records,
        key=lambda item: str(item.get("production_path", "")),
    ):
        artifact_id = _validated_identifier(str(record.get("artifact_id", "")), field="artifact_id")
        source_task = _validated_identifier(
            str(record.get("source_task", "")),
            field="source_task",
        )
        current_version = record.get("current_version")
        if not isinstance(current_version, str) or not current_version.strip():
            raise ValueError(
                f"current production artifact is missing its version: {artifact_id}"
            )
        declared = Path(str(record.get("production_path", "")))
        if declared.is_absolute() or ".." in declared.parts or not declared.parts or declared.parts[0] != "production":
            raise ValueError("current production path must be project-relative under production/")
        source = project_root / declared
        receipt_path = project_root / "runs" / source_task / "archive_receipt.yml"
        try:
            receipt = yaml.safe_load(
                _read_bounded_file(repo_root, receipt_path).decode("utf-8")
            ) or {}
        except (OSError, ValueError) as exc:
            raise ValueError(
                f"production promotion receipt is missing or invalid: {artifact_id}"
            ) from exc
        promotions = receipt.get("promotions_applied", []) if isinstance(receipt, dict) else []
        matching_promotions = [
            item
            for item in promotions
            if isinstance(item, dict)
            and item.get("artifact_id") == artifact_id
            and item.get("source_run_artifact") == record.get("source_run_artifact")
            and item.get("production_path") == declared.as_posix()
            and isinstance(item.get("version"), str)
            and item.get("version") == current_version
        ]
        if any(
            (
                not isinstance(receipt, dict),
                receipt.get("status") != "completed",
                receipt.get("project") != project,
                receipt.get("task_id") != source_task,
                len(matching_promotions) != 1,
            )
        ):
            raise ValueError(
                f"production promotion receipt does not bind current artifact: {artifact_id}"
            )
        _assert_no_symlink_ancestry(source, boundary=project_root)
        payload = _read_bounded_file(repo_root, source)
        digest = hashlib.sha256(payload).hexdigest()
        if not record.get("production_sha256") or digest != str(record.get("production_sha256")):
            raise ValueError(f"production result hash mismatch: {artifact_id}")
        promoted_source = source_bindings[artifact_id]
        try:
            source_payload = _read_bounded_file(repo_root, promoted_source)
        except (OSError, ValueError) as exc:
            raise ValueError(
                f"production result source is missing or invalid: {artifact_id}"
            ) from exc
        if hashlib.sha256(source_payload).hexdigest() != digest:
            raise ValueError(
                f"production result no longer matches its promoted run source: {artifact_id}"
            )
        payloads.append(
            (
                artifact_id,
                source.relative_to(production_root),
                source,
                payload,
                digest,
            )
        )
    return payloads


def _render_readme(project: str, manifest: dict[str, Any]) -> str:
    lines = [
        f"# {project} 产物",
        "",
        "这里是 AgentLab 生成的人工浏览投影。Task 账本、不可变 ArtifactVersion 和晋升门仍是权威来源。",
        "候选文件不代表 canon，也不代表已经通过人工验收。",
        "",
    ]
    task_summaries = manifest.get("task_summaries", [])
    if task_summaries:
        lines.extend(
            [
                "## Task 状态",
                "",
            ]
        )
        for task_summary in task_summaries:
            lines.append(
                f"- `{task_summary.get('task_id', 'unknown')}`："
                f"状态 `{task_summary.get('task_status', 'unknown')}`，"
                f"Attempt {task_summary.get('attempt_count', 'unknown')}，"
                f"最后事件 {task_summary.get('last_event_sequence', 'unknown')}"
            )
        lines.append("")
    lines.extend(
        [
            "## 当前内容",
            "",
        ]
    )
    for item in manifest.get("candidates", []):
        lines.append(f"- 候选 `{item['artifact_id']}`：`{item['export_path']}`")
    for item in manifest.get("current", []):
        lines.append(f"- 正式 `{item['export_path']}`")
    if not manifest.get("candidates") and not manifest.get("current"):
        lines.append("- 暂无可导出的产物。")
    lines.extend(["", "具体哈希和来源见 `manifest.yml`。", ""])
    return "\n".join(lines)


def _managed_export_paths(manifest: dict[str, Any], *, project: str) -> set[str]:
    if (
        manifest.get("schema_version") != "agentlab-project-results/v1"
        or manifest.get("project") != project
        or manifest.get("authority") != "inspection_projection_only"
    ):
        return set()
    paths: set[str] = set()
    for section in ("candidates", "current"):
        records = manifest.get(section, [])
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            relative = Path(str(record.get("export_path", "")))
            if (
                not relative.is_absolute()
                and ".." not in relative.parts
                and relative.parts
                and relative.parts[0] in {"candidates", "current"}
            ):
                paths.add(relative.as_posix())
    return paths


def _pending_cleanup_paths(manifest: dict[str, Any], *, project: str) -> set[str]:
    if (
        manifest.get("schema_version") != "agentlab-project-results/v1"
        or manifest.get("project") != project
        or manifest.get("authority") != "inspection_projection_only"
    ):
        return set()
    paths: set[str] = set()
    records = manifest.get("pending_cleanup", [])
    if not isinstance(records, list):
        return paths
    for value in records:
        relative = Path(str(value))
        if (
            not relative.is_absolute()
            and ".." not in relative.parts
            and relative.parts
            and relative.parts[0] in {"candidates", "current"}
        ):
            paths.add(relative.as_posix())
    return paths


def _load_previous_manifest(
    output_root: Path,
    *,
    repo_root: Path,
    project: str,
) -> dict[str, Any]:
    path = output_root / "manifest.yml"
    try:
        payload = _read_bounded_file(repo_root, path)
    except FileNotFoundError:
        return {}
    value = yaml.safe_load(payload.decode("utf-8")) or {}
    if not isinstance(value, dict):
        return {}
    if any(
        (
            value.get("schema_version") != "agentlab-project-results/v1",
            value.get("project") != project,
            value.get("authority") != "inspection_projection_only",
        )
    ):
        return {}
    return value


def _stale_managed_paths(
    *,
    project: str,
    previous: dict[str, Any],
    current: dict[str, Any],
) -> set[str]:
    previous_paths = _managed_export_paths(previous, project=project)
    previous_paths.update(_pending_cleanup_paths(previous, project=project))
    return previous_paths - _managed_export_paths(current, project=project)


def _remove_stale_managed_files(
    output_root: Path,
    *,
    repo_root: Path,
    stale: set[str],
) -> None:
    for relative in sorted(stale):
        path = output_root / relative
        _unlink_bounded_regular_file(repo_root, path)


def _content_addressed_relative(relative: Path, digest: str) -> Path:
    return relative.with_name(f"{digest}{_safe_export_suffix(relative.suffix)}")


def _safe_export_suffix(suffix: str) -> str:
    normalized = str(suffix or "")
    if (
        normalized.startswith(".")
        and len(normalized.encode("utf-8")) <= 32
        and "/" not in normalized
        and "\\" not in normalized
    ):
        return normalized
    return ".bin"


def _export_project_results_unlocked(
    repo_root: Path,
    *,
    project: str,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Export governed results into ``outputs/<Project>`` without promoting them."""

    root = Path(repo_root).resolve(strict=True)
    project = _validated_identifier(project, field="project")
    task_id = _validated_identifier(task_id, field="task_id") if task_id is not None else None
    project_root = root / "projects" / project
    _assert_no_symlink_ancestry(project_root, boundary=root)
    if not project_root.is_dir() or project_root.is_symlink():
        raise ValueError(f"project does not exist: {project}")

    task_projections = _rebuilt_task_projections(
        root,
        project=project,
        requested_task_id=task_id,
    )

    output_root = root / "outputs" / project
    output_descriptor = _open_bounded_directory(root, output_root, create=True)
    os.close(output_descriptor)
    previous_manifest = _load_previous_manifest(
        output_root,
        repo_root=root,
        project=project,
    )

    manifest: dict[str, Any] = {
        "schema_version": "agentlab-project-results/v1",
        "project": project,
        "authority": "inspection_projection_only",
        "production_modified": False,
        "task_summaries": [],
        "candidates": [],
        "current": [],
        "pending_cleanup": [],
        "pending_materialization": [],
    }
    writes: list[tuple[Path, bytes]] = []

    for current_task_id, task_root, projection in task_projections:
        manifest["task_summaries"].append(_task_summary(current_task_id, projection))
        for item in sorted(_candidate_items(projection), key=lambda value: str(value.get("artifact_id", ""))):
            artifact_id = _validated_identifier(str(item.get("artifact_id", "")), field="artifact_id")
            payload, source, digest = _read_governed_payload(root, task_root, item)
            filename = f"{digest}{_safe_export_suffix(source.suffix)}"
            destination = output_root / "candidates" / current_task_id / filename
            writes.append((destination, payload))
            manifest["candidates"].append(
                {
                    "artifact_id": artifact_id,
                    "version_id": str(item.get("version_id", "")),
                    "task_id": current_task_id,
                    "lifecycle": "candidate",
                    "sha256": digest,
                    "size_bytes": len(payload),
                    "source_path": source.relative_to(root).as_posix(),
                    "export_path": destination.relative_to(output_root).as_posix(),
                }
            )

    for artifact_id, relative, source, payload, digest in _production_payloads(
        root,
        project=project,
        project_root=project_root,
    ):
        destination = output_root / "current" / _content_addressed_relative(relative, digest)
        writes.append((destination, payload))
        manifest["current"].append(
            {
                "artifact_id": artifact_id,
                "lifecycle": "production",
                "sha256": digest,
                "size_bytes": len(payload),
                "source_path": source.relative_to(root).as_posix(),
                "export_path": destination.relative_to(output_root).as_posix(),
            }
        )

    stale = _stale_managed_paths(
        project=project,
        previous=previous_manifest,
        current=manifest,
    )
    manifest["pending_cleanup"] = sorted(stale)
    manifest["pending_materialization"] = sorted(
        path.relative_to(output_root).as_posix() for path, _payload in writes
    )
    manifest["projection_state"] = "materializing"
    _atomic_write_bytes(
        root,
        output_root / "manifest.yml",
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False).encode("utf-8"),
    )
    for destination, payload in writes:
        _atomic_write_bytes(root, destination, payload)
    _atomic_write_bytes(
        root,
        output_root / "README.md",
        _render_readme(project, manifest).encode("utf-8"),
    )
    _remove_stale_managed_files(
        output_root,
        repo_root=root,
        stale=stale,
    )
    manifest["pending_cleanup"] = []
    manifest["pending_materialization"] = []
    manifest["projection_state"] = "complete"
    _atomic_write_bytes(
        root,
        output_root / "manifest.yml",
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False).encode("utf-8"),
    )
    return {
        "status": "pass",
        "project": project,
        "output_root": output_root.as_posix(),
        "exported_count": len(manifest["candidates"]) + len(manifest["current"]),
        "production_modified": False,
    }


def export_project_results(
    repo_root: Path,
    *,
    project: str,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Serialize one rebuild of the governed project-wide result projection."""

    root = Path(repo_root).resolve(strict=True)
    normalized_project = _validated_identifier(project, field="project")
    with _project_export_lock(root, normalized_project):
        return _export_project_results_unlocked(
            root,
            project=normalized_project,
            task_id=task_id,
        )
