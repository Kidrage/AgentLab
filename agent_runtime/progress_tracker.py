"""Progress tracking for task state — read/write progress.yml.

Single-source-of-truth progress file consumed by both CLI and Web UI.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from atomic_io import atomic_write_yaml, safe_read_yaml


DEFAULT_AGENT_WEIGHTS = {
    "Supervisor": 15,
    "RepoScout": 15,
    "Researcher": 15,
    "InterfaceMapper": 15,
    "Coder": 25,
    "TesterAuditor": 20,
    "Verifier": 10,
    "Archivist": 10,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def progress_path(run_dir: Path) -> Path:
    return run_dir / "progress.yml"


def create_progress(
    run_dir: Path,
    project: str,
    task_id: str,
    route: list[str],
    risk_level: str = "R1",
    budget_mode: str = "balanced",
) -> dict:
    """Initialise progress.yml for a task."""
    agents = {}
    for idx, name in enumerate(route):
        agents[name] = {
            "order": idx + 1,
            "status": "waiting",
            "provider_key": None,
            "model": None,
            "started_at": None,
            "completed_at": None,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "report_path": None,
        }

    data = {
        "version": 1,
        "project": project,
        "task_id": task_id,
        "status": "new",
        "risk_level": risk_level,
        "budget_mode": budget_mode,
        "route": route,
        "current_agent": None,
        "current_stage": "initialized",
        "percent_complete": 0,
        "last_event": "Task created.",
        "last_event_at": utc_now(),
        "last_checkpoint": None,
        "last_call_id": None,
        "provider_status": {
            "current_provider": None,
            "failed_provider": None,
            "fallback_available": True,
            "paused_for_provider": False,
        },
        "agents": agents,
        "incidents": {"open_count": 0, "latest": None},
        "backup": {"p0_synced": False, "last_backup_at": None},
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(progress_path(run_dir), data)
    try:
        from task_snapshot import safe_write_task_snapshot
        safe_write_task_snapshot(run_dir, project, task_id)
    except Exception:
        pass
    return data


def load_progress(run_dir: Path) -> dict | None:
    """Read progress.yml, return None if missing."""
    return safe_read_yaml(progress_path(run_dir))


def save_progress(run_dir: Path, data: dict) -> None:
    data["last_event_at"] = utc_now()
    atomic_write_yaml(progress_path(run_dir), data)
    try:
        from task_snapshot import safe_write_task_snapshot
        safe_write_task_snapshot(run_dir, data.get("project"), data.get("task_id"))
    except Exception:
        pass


def mark_agent_started(run_dir: Path, agent_name: str, provider_key: str, model: str) -> dict | None:
    """Mark agent as active in progress.yml."""
    data = load_progress(run_dir)
    if data is None:
        return None
    data["current_agent"] = agent_name
    data["current_stage"] = "llm_call_started"
    data["status"] = "running"
    data.setdefault("agents", {})

    if agent_name in data.get("agents", {}):
        data["agents"][agent_name]["status"] = "active"
        data["agents"][agent_name]["provider_key"] = provider_key
        data["agents"][agent_name]["model"] = model
        data["agents"][agent_name]["started_at"] = utc_now()

    provider_status = data.setdefault("provider_status", {})
    provider_status["current_provider"] = provider_key
    data["percent_complete"] = _calc_percent(data)
    save_progress(run_dir, data)
    return data


def mark_agent_completed(run_dir: Path, agent_name: str, report_path: str, input_tokens: int = 0, output_tokens: int = 0, total_tokens: int = 0) -> dict | None:
    data = load_progress(run_dir)
    if data is None:
        return None
    data.setdefault("agents", {})
    if agent_name in data.get("agents", {}):
        data["agents"][agent_name]["status"] = "completed"
        data["agents"][agent_name]["completed_at"] = utc_now()
        data["agents"][agent_name]["report_path"] = report_path
        data["agents"][agent_name]["input_tokens"] = input_tokens
        data["agents"][agent_name]["output_tokens"] = output_tokens
        data["agents"][agent_name]["total_tokens"] = total_tokens

    data["current_agent"] = None
    data["current_stage"] = "agent_completed"
    data["last_event"] = f"{agent_name} completed."
    data["percent_complete"] = _calc_percent(data)
    save_progress(run_dir, data)
    return data


def mark_agent_paused(run_dir: Path, agent_name: str, reason: str) -> dict | None:
    data = load_progress(run_dir)
    if data is None:
        return None
    data.setdefault("agents", {})
    if agent_name in data.get("agents", {}):
        data["agents"][agent_name]["status"] = "paused"
    data["status"] = "paused"
    data["current_stage"] = "paused"
    data["last_event"] = f"{agent_name} paused: {reason}"
    data.setdefault("provider_status", {})["paused_for_provider"] = True
    save_progress(run_dir, data)
    return data


def _calc_percent(data: dict) -> int:
    agents = data.get("agents", {})
    completed_weight = 0
    total_weight = 0
    for name, state in agents.items():
        w = DEFAULT_AGENT_WEIGHTS.get(name, 10)
        total_weight += w
        if state.get("status") == "completed":
            completed_weight += w
        elif state.get("status") == "active":
            completed_weight += w * 0.3  # in-progress = partial

    if total_weight == 0:
        return 0
    return min(100, int(100 * completed_weight / total_weight))


def progress_summary(data: dict) -> dict:
    """Extract a compact progress summary for CLI/Web UI."""
    agents_list = []
    for name in data.get("route", []):
        ag = data.get("agents", {}).get(name, {})
        agents_list.append({
            "name": name,
            "status": ag.get("status", "waiting"),
            "provider": ag.get("provider_key", "—"),
            "tokens": ag.get("total_tokens", 0) or 0,
        })

    return {
        "project": data.get("project"),
        "task_id": data.get("task_id"),
        "status": data.get("status"),
        "percent": data.get("percent_complete", 0),
        "current_agent": data.get("current_agent"),
        "current_stage": data.get("current_stage"),
        "last_event": data.get("last_event"),
        "agents": agents_list,
        "provider_status": data.get("provider_status"),
        "incidents": data.get("incidents"),
    }
