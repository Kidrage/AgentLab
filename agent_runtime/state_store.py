"""Task state storage for AgentLab CLI — v3 with atomic writes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from atomic_io import atomic_write_text, atomic_write_yaml
from schemas import TaskState


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def state_path(run_dir: Path) -> Path:
    return run_dir / "state.yml"


def load_state(run_dir: Path, project: str, task_id: str) -> TaskState:
    path = state_path(run_dir)
    if not path.exists():
        return TaskState(project=project, task_id=task_id)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return TaskState(**data)


def save_state(run_dir: Path, state: TaskState) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    state.updated_at = utc_now()
    path = state_path(run_dir)
    atomic_write_yaml(path, state.model_dump(mode="json"))
    return path


def mark_planned(run_dir: Path, project: str, task_id: str) -> TaskState:
    state = load_state(run_dir, project, task_id)
    state.status = "planned"
    state.last_event = "Workflow plan prepared."
    save_state(run_dir, state)
    return state


def mark_agent_completed(run_dir: Path, project: str, task_id: str, agent_name: str, report_path: Path) -> TaskState:
    state = load_state(run_dir, project, task_id)
    if agent_name not in state.completed_agents:
        state.completed_agents.append(agent_name)
    state.current_agent = None
    state.status = "running"
    state.reports[agent_name] = str(report_path)
    state.last_event = f"{agent_name} completed report."
    save_state(run_dir, state)
    return state


def mark_failed_recoverable(run_dir: Path, project: str, task_id: str, reason: str, failed_agent: str | None = None) -> TaskState:
    """Mark task as failed_recoverable with context for recovery."""
    state = load_state(run_dir, project, task_id)
    state.status = "failed_recoverable"
    if failed_agent:
        state.current_agent = failed_agent
    state.last_event = reason
    save_state(run_dir, state)
    return state