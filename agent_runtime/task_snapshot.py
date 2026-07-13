"""Canonical task snapshot for AgentLab task state.

`state.yml`, `progress.yml`, and `lifecycle.yml` intentionally keep different
views of a task.  This module derives one small, machine-readable snapshot from
those files so CLI, UI, task index, and validation can share the same status
contract without guessing which source is authoritative.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_yaml, safe_read_yaml

try:
    from lifecycle_graph import LIFECYCLE_NODES
except ModuleNotFoundError:  # pragma: no cover - package import
    from agent_runtime.lifecycle_graph import LIFECYCLE_NODES


LIFECYCLE_ORDER = list(LIFECYCLE_NODES)

TERMINAL_LIFECYCLE_STATUSES = {"completed", "skipped"}
BLOCKING_STATUSES = {"blocked", "paused", "recoverable", "failed", "failed_recoverable"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def snapshot_path(run_dir: Path) -> Path:
    return run_dir / "task_snapshot.yml"


def normalize_status(raw: Any) -> str:
    """Normalize historical status variants into a stable vocabulary."""
    status = str(raw or "").strip().lower()
    aliases = {
        "": "unknown",
        "complete": "completed",
        "done": "completed",
        "in-progress": "running",
        "in_progress": "running",
        "failed_recoverable": "recoverable",
    }
    status = aliases.get(status, status)
    valid = {
        "new",
        "planned",
        "running",
        "paused",
        "blocked",
        "recoverable",
        "validating",
        "auditing",
        "archiving",
        "syncing",
        "completed",
        "failed",
        "archived",
        "unknown",
    }
    return status if status in valid else "unknown"


def _read_yaml(path: Path) -> dict[str, Any]:
    data = safe_read_yaml(path, {})
    return data if isinstance(data, dict) else {}


def _project_from_run_dir(run_dir: Path) -> str:
    try:
        return run_dir.parent.parent.name
    except Exception:
        return ""


def _route_from_plan(plan: dict[str, Any]) -> list[str]:
    route = plan.get("route", {})
    if isinstance(route, dict):
        return list(route.get("agents", []) or [])
    if isinstance(route, list):
        return list(route)
    return []


def _lifecycle_summary(lifecycle: dict[str, Any]) -> dict[str, Any]:
    nodes = lifecycle.get("nodes", {}) if isinstance(lifecycle, dict) else {}
    node_count = len(LIFECYCLE_ORDER)
    completed = 0
    skipped = 0
    failed = 0
    running = 0
    waiting = 0
    next_node = None
    node_statuses: dict[str, str] = {}

    for node_id in LIFECYCLE_ORDER:
        status = str(nodes.get(node_id, {}).get("status") or "missing")
        node_statuses[node_id] = status
        if status == "completed":
            completed += 1
        elif status == "skipped":
            skipped += 1
        elif status == "failed":
            failed += 1
        elif status == "running":
            running += 1
        elif status == "waiting":
            waiting += 1
        if next_node is None and status in {"waiting", "running", "failed", "paused"}:
            next_node = node_id

    if not nodes:
        lifecycle_status = "unknown"
    elif failed:
        lifecycle_status = "blocked"
    elif running:
        lifecycle_status = "running"
    elif completed + skipped == node_count:
        lifecycle_status = "completed"
    elif completed or skipped or waiting:
        lifecycle_status = "running"
    else:
        lifecycle_status = "unknown"

    percent = int(100 * (completed + skipped) / max(node_count, 1))
    return {
        "status": lifecycle_status,
        "node_count": node_count,
        "completed_count": completed,
        "skipped_count": skipped,
        "failed_count": failed,
        "running_count": running,
        "waiting_count": waiting,
        "percent_complete": min(100, percent),
        "next_node": next_node,
        "nodes": node_statuses,
    }


def _progress_percent(progress: dict[str, Any]) -> int:
    value = progress.get("percent_complete", progress.get("percent", 0))
    try:
        return max(0, min(100, int(value or 0)))
    except Exception:
        return 0


def _completed_agents(state: dict[str, Any], progress: dict[str, Any]) -> list[str]:
    agents = list(state.get("completed_agents", []) or [])
    if agents:
        return agents
    completed = []
    for name, data in (progress.get("agents", {}) or {}).items():
        if isinstance(data, dict) and data.get("status") == "completed":
            completed.append(name)
    return completed


def _status_family(status: str) -> str:
    if status in {"running", "validating", "auditing", "archiving", "syncing"}:
        return "running"
    if status in {"blocked", "paused", "recoverable", "failed"}:
        return "blocked"
    return status


def _choose_status(state_status: str, progress_status: str, lifecycle_status: str, *, has_plan: bool) -> str:
    if state_status in BLOCKING_STATUSES:
        return "recoverable" if state_status == "failed_recoverable" else state_status
    if progress_status in BLOCKING_STATUSES:
        return "recoverable" if progress_status == "failed_recoverable" else progress_status
    if lifecycle_status in {"blocked", "paused"}:
        return lifecycle_status
    if state_status in {"failed", "archived"}:
        return state_status
    if state_status == "completed" or lifecycle_status == "completed":
        return "completed"
    if state_status in {"running", "validating", "auditing", "archiving", "syncing"}:
        return "running"
    if progress_status == "running" or lifecycle_status == "running":
        return "running"
    if state_status == "planned" or has_plan:
        return "planned"
    if state_status == "new":
        return "new"
    return "unknown"


def build_task_snapshot(run_dir: Path, project: str | None = None, task_id: str | None = None) -> dict[str, Any]:
    """Derive a canonical task snapshot from local task artifacts."""
    run_dir = Path(run_dir)
    project = project or _project_from_run_dir(run_dir)
    task_id = task_id or run_dir.name

    state = _read_yaml(run_dir / "state.yml")
    progress = _read_yaml(run_dir / "progress.yml")
    lifecycle = _read_yaml(run_dir / "lifecycle.yml")
    plan = _read_yaml(run_dir / "workflow_plan.yml")
    lifecycle_info = _lifecycle_summary(lifecycle)

    state_status = normalize_status(state.get("status"))
    progress_status = normalize_status(progress.get("status"))
    lifecycle_status = normalize_status(lifecycle_info.get("status"))
    route = _route_from_plan(plan) or list(progress.get("route", []) or [])
    status = _choose_status(state_status, progress_status, lifecycle_status, has_plan=bool(plan))

    percent = _progress_percent(progress)
    if percent == 0 and lifecycle_info.get("percent_complete"):
        percent = int(lifecycle_info["percent_complete"])
    if status == "completed":
        percent = 100

    current_agent = state.get("current_agent") or progress.get("current_agent")
    current_stage = progress.get("current_stage") or lifecycle_info.get("next_node")
    last_event = state.get("last_event") or progress.get("last_event") or ""
    completed_agents = _completed_agents(state, progress)

    drift: list[str] = []
    source_statuses = {
        "state": state_status,
        "progress": progress_status,
        "lifecycle": lifecycle_status,
    }
    non_unknown = {k: v for k, v in source_statuses.items() if v != "unknown"}
    families = {k: _status_family(v) for k, v in non_unknown.items()}
    if len(set(families.values())) > 1:
        drift.append(f"status_mismatch: {non_unknown}")
    if status == "completed" and percent != 100:
        drift.append("completed_status_with_non_100_percent")
    if route and completed_agents and any(agent not in route for agent in completed_agents):
        drift.append("completed_agents_not_in_route")

    return {
        "version": 1,
        "generated_at": utc_now(),
        "project": project,
        "task_id": task_id,
        "status": status,
        "source_statuses": source_statuses,
        "drift": drift,
        "route": route,
        "current_agent": current_agent,
        "current_stage": current_stage,
        "percent_complete": percent,
        "last_event": last_event,
        "completed_agents": completed_agents,
        "reports": state.get("reports", {}) or {},
        "lifecycle": lifecycle_info,
        "paths": {
            "state": "state.yml",
            "progress": "progress.yml",
            "lifecycle": "lifecycle.yml",
            "workflow_plan": "workflow_plan.yml",
        },
    }


def write_task_snapshot(run_dir: Path, project: str | None = None, task_id: str | None = None) -> Path:
    snapshot = build_task_snapshot(run_dir, project=project, task_id=task_id)
    path = snapshot_path(Path(run_dir))
    atomic_write_yaml(path, snapshot)
    return path


def safe_write_task_snapshot(run_dir: Path, project: str | None = None, task_id: str | None = None) -> Path | None:
    """Best-effort snapshot writer used by state/progress/lifecycle writers."""
    try:
        return write_task_snapshot(run_dir, project=project, task_id=task_id)
    except Exception:
        return None
