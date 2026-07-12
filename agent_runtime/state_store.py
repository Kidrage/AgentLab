"""Task state storage for AgentLab CLI."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import json

import yaml

try:
    from atomic_io import atomic_write_yaml
except ImportError:  # pragma: no cover
    from agent_runtime.atomic_io import atomic_write_yaml

try:
    from agent_runtime.schemas import TaskState
except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
    from schemas import TaskState


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def state_path(run_dir: Path) -> Path:
    return run_dir / "state.yml"


def load_state(run_dir: Path, project: str | None = None, task_id: str | None = None) -> TaskState:
    path = state_path(run_dir)
    if not path.exists():
        return TaskState(project=project or "", task_id=task_id or run_dir.name)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.setdefault("project", project or "")
    data.setdefault("task_id", task_id or run_dir.name)
    return TaskState(**data)


def _state_to_dict(state: TaskState | dict[str, Any]) -> dict[str, Any]:
    if isinstance(state, TaskState):
        return state.model_dump(mode="json")
    return dict(state)


def save_state(run_dir: Path, state: TaskState | dict[str, Any]) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    if isinstance(state, TaskState):
        state.updated_at = utc_now()
        project = state.project
        task_id = state.task_id
    else:
        state["updated_at"] = utc_now()
        project = state.get("project")
        task_id = state.get("task_id")
    path = state_path(run_dir)
    atomic_write_yaml(path, _state_to_dict(state))
    try:
        from task_snapshot import safe_write_task_snapshot
        safe_write_task_snapshot(run_dir, project, task_id)
    except Exception:
        pass
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
    state = load_state(run_dir, project, task_id)
    state.status = "failed_recoverable"
    if failed_agent:
        state.current_agent = failed_agent
    state.last_event = reason
    save_state(run_dir, state)
    return state


def mark_failed_blocked(run_dir: Path, project: str, task_id: str, reason: str, failed_agent: str | None = None) -> TaskState:
    """Mark task as blocked / human_review required.

    Use when recovery verdict is human_review or stop.
    """
    state = load_state(run_dir, project, task_id)
    state.status = "blocked"
    if failed_agent:
        state.current_agent = failed_agent
    state.last_event = reason
    save_state(run_dir, state)
    return state


def mark_failed_stopped(run_dir: Path, project: str, task_id: str, reason: str, failed_agent: str | None = None) -> TaskState:
    """Mark task as stopped / unsafe.

    Use when recovery verdict is stop or an unsafe category is detected.
    """
    state = load_state(run_dir, project, task_id)
    state.status = "failed"
    if failed_agent:
        state.current_agent = failed_agent
    state.last_event = reason
    save_state(run_dir, state)
    return state


class TaskEvents:
    """Manage task event recording."""

    def __init__(self, task_id: str, run_dir: Optional[Path] = None):
        self.task_id = task_id
        self.run_dir = run_dir or Path(f"projects/AgentLab/runs/{task_id}")

    def record_event(self, event_data: dict) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        events_path = self.run_dir / "task_events.jsonl"
        event = {"timestamp": utc_now(), **event_data}
        with events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    def get_task_events(self, task_id: str | None = None) -> list:
        events_path = self.run_dir / "task_events.jsonl"
        if not events_path.exists():
            return []
        events = []
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if task_id is None or event.get("task_id") == task_id or task_id == self.task_id:
                events.append(event)
        return events
