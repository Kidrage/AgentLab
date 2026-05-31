"""Provider incident tracking — records quota, rate-limit, and outage events."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from atomic_io import atomic_write_yaml, safe_read_yaml


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def incidents_path(run_dir: Path) -> Path:
    return run_dir / "provider_incidents.yml"


def record_incident(
    run_dir: Path,
    project: str,
    task_id: str,
    agent_name: str,
    provider_key: str,
    model: str,
    error_class: str,
    error_message: str,
    call_id: str = "",
) -> dict:
    """Append a provider incident to the task's incident log."""
    data = safe_read_yaml(incidents_path(run_dir)) or {"incidents": []}
    entry = {
        "at": utc_now(),
        "project": project,
        "task_id": task_id,
        "agent": agent_name,
        "provider": provider_key,
        "model": model,
        "error_class": error_class,
        "error_message": error_message,
        "call_id": call_id,
        "resolved": False,
    }
    data.setdefault("incidents", []).append(entry)
    atomic_write_yaml(incidents_path(run_dir), data)
    return entry


def latest_incident(run_dir: Path) -> dict | None:
    data = safe_read_yaml(incidents_path(run_dir))
    if not data:
        return None
    incidents = data.get("incidents", [])
    return incidents[-1] if incidents else None


def open_incidents(run_dir: Path) -> list[dict]:
    data = safe_read_yaml(incidents_path(run_dir))
    if not data:
        return []
    return [i for i in data.get("incidents", []) if not i.get("resolved", False)]