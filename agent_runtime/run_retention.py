"""Archive inactive project runs without deleting historical evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import fnmatch
import os
from pathlib import Path
from typing import Any

import yaml

from agent_runtime.atomic_io import atomic_write_yaml, safe_read_yaml


POLICY_FILE = "run_retention_policy.yml"
STATUS_FILES = ("task_snapshot.yml", "state.yml", "progress.yml")


def _load_policy(root: Path) -> dict[str, Any]:
    path = root / "config" / POLICY_FILE
    data = safe_read_yaml(path, default={})
    return data if isinstance(data, dict) else {}


def _path_component(value: str, label: str) -> str:
    value = str(value).strip()
    if not value or value in {".", ".."} or Path(value).name != value:
        raise ValueError(f"{label} must be one path component")
    return value


def _archive_history_root(project_root: Path, policy: dict[str, Any]) -> Path:
    archive_root = Path(str(policy.get("archive_root") or "archive/run_history"))
    if archive_root.is_absolute() or ".." in archive_root.parts:
        raise ValueError("run retention archive_root must stay inside the project")
    return project_root / archive_root


def resolve_run_dir(root: Path, project: str, task_id: str) -> Path:
    """Resolve an active run first, then an exact retained run.

    Missing runs resolve to their canonical active path so callers can report a
    useful expected location. Retention archives are read-only evidence and are
    never restored to the active ``runs`` directory.
    """
    root = root.resolve()
    project = _path_component(project, "project")
    task_id = _path_component(task_id, "task_id")
    project_root = root / "projects" / project
    active = project_root / "runs" / task_id
    if active.is_dir():
        return active

    archive_history = _archive_history_root(project_root, _load_policy(root))
    if not archive_history.is_dir():
        return active
    matches = sorted(
        (
            batch / "runs" / task_id
            for batch in archive_history.iterdir()
            if batch.is_dir() and (batch / "runs" / task_id).is_dir()
        ),
        key=lambda path: path.parent.parent.name,
        reverse=True,
    )
    return matches[0] if matches else active


def _patterns(policy: dict[str, Any], project: str, key: str) -> list[str]:
    shared = policy.get(key) if isinstance(policy.get(key), list) else []
    overrides = policy.get("project_overrides")
    project_policy = overrides.get(project, {}) if isinstance(overrides, dict) else {}
    local = project_policy.get(key) if isinstance(project_policy.get(key), list) else []
    return [str(pattern) for pattern in [*shared, *local]]


def _first_match(name: str, patterns: list[str]) -> str | None:
    return next((pattern for pattern in patterns if fnmatch.fnmatch(name, pattern)), None)


def _run_status(run_dir: Path) -> str:
    for filename in STATUS_FILES:
        data = safe_read_yaml(run_dir / filename, default={})
        if not isinstance(data, dict):
            continue
        status = data.get("status")
        if status:
            return str(status).strip().lower()
    return "unknown"


def build_run_retention_plan(
    root: Path,
    project: str,
    *,
    allow_protected_status: bool = False,
) -> dict[str, Any]:
    """Classify active run directories; never mutate the project."""
    root = root.resolve()
    project_root = root / "projects" / project
    runs_root = project_root / "runs"
    if not project_root.is_dir():
        raise FileNotFoundError(project_root)
    policy = _load_policy(root)
    archive_patterns = _patterns(policy, project, "archive_name_patterns")
    protect_patterns = _patterns(policy, project, "protect_name_patterns")
    protect_statuses = {
        str(status).strip().lower()
        for status in policy.get("protect_statuses", [])
    }
    protect_marker = str(policy.get("protect_marker") or ".agentlab_keep")
    candidates: list[dict[str, Any]] = []
    protected: list[dict[str, Any]] = []
    ignored_count = 0

    run_dirs = sorted(
        (path for path in runs_root.iterdir() if path.is_dir()),
        key=lambda path: path.name,
    ) if runs_root.is_dir() else []
    for run_dir in run_dirs:
        archive_match = _first_match(run_dir.name, archive_patterns)
        if not archive_match:
            ignored_count += 1
            continue
        status = _run_status(run_dir)
        protection_reason = None
        if (run_dir / protect_marker).exists():
            protection_reason = f"marker:{protect_marker}"
        else:
            protect_match = _first_match(run_dir.name, protect_patterns)
            if protect_match:
                protection_reason = f"pattern:{protect_match}"
            elif status in protect_statuses and not allow_protected_status:
                protection_reason = f"status:{status}"
        item = {
            "run_id": run_dir.name,
            "source": str(run_dir.relative_to(root)),
            "status": status,
            "archive_pattern": archive_match,
        }
        if protection_reason:
            protected.append({**item, "protection_reason": protection_reason})
        else:
            candidates.append(item)

    return {
        "schema_version": 1,
        "report_type": "agentlab_run_retention_plan",
        "project": project,
        "runs_root": str(runs_root.relative_to(root)),
        "candidate_count": len(candidates),
        "protected_count": len(protected),
        "ignored_count": ignored_count,
        "allow_protected_status": allow_protected_status,
        "candidates": candidates,
        "protected": protected,
    }


def archive_runs_from_plan(
    root: Path,
    plan: dict[str, Any],
    *,
    batch_id: str | None = None,
) -> dict[str, Any]:
    """Atomically move planned runs and update a recovery manifest after each move."""
    root = root.resolve()
    project = str(plan.get("project") or "")
    if not project or not (root / "projects" / project).is_dir():
        raise ValueError("retention plan has no valid project")
    policy = _load_policy(root)
    batch_id = batch_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    batch_root = _archive_history_root(root / "projects" / project, policy) / batch_id
    manifest_path = batch_root / "archive_manifest.yml"
    if manifest_path.exists():
        raise FileExistsError(manifest_path)
    entries = []
    for item in plan.get("candidates", []):
        if not isinstance(item, dict) or not item.get("run_id"):
            continue
        source = root / str(item["source"])
        destination = batch_root / "runs" / str(item["run_id"])
        entries.append(
            {
                **item,
                "destination": str(destination.relative_to(root)),
                "moved": False,
            }
        )
    manifest = {
        "schema_version": 1,
        "report_type": "agentlab_run_archive_manifest",
        "project": project,
        "batch_id": batch_id,
        "status": "applying",
        "entry_count": len(entries),
        "entries": entries,
    }
    batch_root.mkdir(parents=True, exist_ok=False)
    atomic_write_yaml(manifest_path, manifest)
    for entry in entries:
        source = root / str(entry["source"])
        destination = root / str(entry["destination"])
        if not source.is_dir():
            manifest["status"] = "incomplete"
            manifest["error"] = f"source_missing:{entry['source']}"
            atomic_write_yaml(manifest_path, manifest)
            raise FileNotFoundError(source)
        if destination.exists():
            manifest["status"] = "incomplete"
            manifest["error"] = f"destination_exists:{entry['destination']}"
            atomic_write_yaml(manifest_path, manifest)
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)
        entry["moved"] = True
        atomic_write_yaml(manifest_path, manifest)
    manifest["status"] = "complete"
    manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write_yaml(manifest_path, manifest)
    return manifest
