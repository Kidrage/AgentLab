"""Materialize a human-facing, rebuildable view of governed project results."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml


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


def _read_governed_payload(task_root: Path, item: dict[str, Any]) -> tuple[bytes, Path, str]:
    relative = Path(str(item.get("path", "")))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("artifact path must be task-relative")
    _assert_no_symlink_ancestry(task_root / relative, boundary=task_root)
    source = (task_root / relative).resolve(strict=True)
    boundary = task_root.resolve(strict=True)
    if not _is_relative_to(source, boundary) or not source.is_file() or source.is_symlink():
        raise ValueError("artifact payload must be a regular file inside the task")
    payload = source.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    expected = str(item.get("sha256", ""))
    if not expected or digest != expected:
        raise ValueError(f"artifact hash mismatch: {item.get('version_id', 'unknown')}")
    if int(item.get("size_bytes", -1)) != len(payload):
        raise ValueError(f"artifact size mismatch: {item.get('version_id', 'unknown')}")
    return payload, source, digest


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _candidate_items(task_root: Path) -> list[dict[str, Any]]:
    index_path = task_root / "projections" / "artifact_index.yml"
    if not index_path.is_file() or index_path.is_symlink():
        return []
    raw = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("artifact index must be a mapping")
    return [
        dict(item)
        for item in raw.values()
        if isinstance(item, dict)
        and item.get("disposition") == "eligible"
        and item.get("selection_eligible") is True
    ]


def _task_summary(task_root: Path) -> dict[str, Any]:
    progress_path = task_root / "projections" / "progress.yml"
    if not progress_path.is_file() or progress_path.is_symlink():
        return {}
    _assert_no_symlink_ancestry(progress_path, boundary=task_root)
    raw = yaml.safe_load(progress_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("task progress projection must be a mapping")
    allowed = ("task_id", "task_status", "work_item_counts", "attempt_count", "last_event_sequence")
    return {key: raw[key] for key in allowed if key in raw}


def _production_payloads(project_root: Path) -> list[tuple[str, Path, Path, bytes, str]]:
    production_root = project_root / "production"
    index_path = project_root / "project_artifact_index.yml"
    if not production_root.exists() or not index_path.is_file() or index_path.is_symlink():
        return []
    if not production_root.is_dir() or production_root.is_symlink():
        raise ValueError("project production root must be a regular directory")
    index = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
    records = index.get("artifacts", []) if isinstance(index, dict) else []
    if not isinstance(records, list):
        raise ValueError("project artifact index artifacts must be a list")
    payloads: list[tuple[str, Path, Path, bytes, str]] = []
    for record in sorted(
        (item for item in records if isinstance(item, dict) and item.get("status") == "current"),
        key=lambda item: str(item.get("production_path", "")),
    ):
        artifact_id = _validated_identifier(str(record.get("artifact_id", "")), field="artifact_id")
        declared = Path(str(record.get("production_path", "")))
        if declared.is_absolute() or ".." in declared.parts or not declared.parts or declared.parts[0] != "production":
            raise ValueError("current production path must be project-relative under production/")
        source = project_root / declared
        _assert_no_symlink_ancestry(source, boundary=project_root)
        resolved = source.resolve(strict=True)
        if not resolved.is_file() or resolved.is_symlink() or not _is_relative_to(resolved, production_root.resolve()):
            raise ValueError(f"production result must be a bounded regular file: {source}")
        payload = resolved.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if not record.get("production_sha256") or digest != str(record.get("production_sha256")):
            raise ValueError(f"production result hash mismatch: {artifact_id}")
        payloads.append(
            (
                artifact_id,
                source.relative_to(production_root),
                resolved,
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
    task_summary = manifest.get("task_summary", {})
    if task_summary:
        lines.extend(
            [
                "## Task 状态",
                "",
                f"- Task：`{task_summary.get('task_id', 'unknown')}`",
                f"- 状态：`{task_summary.get('task_status', 'unknown')}`",
                f"- Attempt 数：{task_summary.get('attempt_count', 'unknown')}",
                f"- 最后事件序号：{task_summary.get('last_event_sequence', 'unknown')}",
                "",
            ]
        )
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


def _load_previous_manifest(output_root: Path, *, project: str) -> dict[str, Any]:
    path = output_root / "manifest.yml"
    if not path.is_file() or path.is_symlink():
        return {}
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return value if isinstance(value, dict) and _managed_export_paths(value, project=project) else {}


def _remove_stale_managed_files(
    output_root: Path,
    *,
    repo_root: Path,
    previous: dict[str, Any],
    current: dict[str, Any],
) -> None:
    stale = _managed_export_paths(previous, project=str(current["project"])) - _managed_export_paths(
        current,
        project=str(current["project"]),
    )
    for relative in sorted(stale):
        path = output_root / relative
        _assert_no_symlink_ancestry(path, boundary=repo_root)
        if path.exists():
            if not path.is_file() or path.is_symlink():
                raise ValueError(f"managed result path is not a regular file: {path}")
            path.unlink()


def export_project_results(
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

    task_root: Path | None = None
    if task_id is not None:
        task_root = project_root / "runtime" / "tasks" / task_id
        _assert_no_symlink_ancestry(task_root, boundary=root)
        if not task_root.is_dir() or task_root.is_symlink():
            raise ValueError(f"task does not exist: {task_id}")

    output_root = root / "outputs" / project
    _assert_no_symlink_ancestry(output_root, boundary=root)
    output_root.mkdir(parents=True, exist_ok=True)
    previous_manifest = _load_previous_manifest(output_root, project=project)

    manifest: dict[str, Any] = {
        "schema_version": "agentlab-project-results/v1",
        "project": project,
        "authority": "inspection_projection_only",
        "production_modified": False,
        "candidates": [],
        "current": [],
    }

    if task_id is not None:
        assert task_root is not None
        manifest["task_summary"] = _task_summary(task_root)
        for item in sorted(_candidate_items(task_root), key=lambda value: str(value.get("artifact_id", ""))):
            artifact_id = _validated_identifier(str(item.get("artifact_id", "")), field="artifact_id")
            payload, source, digest = _read_governed_payload(task_root, item)
            suffix = source.suffix or ".bin"
            filename = f"{artifact_id}--{digest[:12]}{suffix}"
            destination = output_root / "candidates" / task_id / filename
            _assert_no_symlink_ancestry(destination, boundary=root)
            _atomic_write_bytes(destination, payload)
            manifest["candidates"].append(
                {
                    "artifact_id": artifact_id,
                    "version_id": str(item.get("version_id", "")),
                    "task_id": task_id,
                    "lifecycle": "candidate",
                    "sha256": digest,
                    "size_bytes": len(payload),
                    "source_path": source.relative_to(root).as_posix(),
                    "export_path": destination.relative_to(output_root).as_posix(),
                }
            )

    for artifact_id, relative, source, payload, digest in _production_payloads(project_root):
        destination = output_root / "current" / relative
        _assert_no_symlink_ancestry(destination, boundary=root)
        _atomic_write_bytes(destination, payload)
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

    atomic_write_yaml(output_root / "manifest.yml", manifest)
    atomic_write_text(output_root / "README.md", _render_readme(project, manifest))
    _remove_stale_managed_files(
        output_root,
        repo_root=root,
        previous=previous_manifest,
        current=manifest,
    )
    return {
        "status": "pass",
        "project": project,
        "output_root": output_root.as_posix(),
        "exported_count": len(manifest["candidates"]) + len(manifest["current"]),
        "production_modified": False,
    }
