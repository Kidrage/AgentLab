"""Task state storage for AgentLab CLI."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

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
    path.write_text(yaml.safe_dump(state.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
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
