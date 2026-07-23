"""Skill usage ledgers for AgentLab active skill injection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from agent_runtime.atomic_io import atomic_write_yaml
    from agent_runtime.state_store import utc_now
except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
    from atomic_io import atomic_write_yaml
    from state_store import utc_now


def task_skill_usage_path(run_dir: Path) -> Path:
    return run_dir / "skill_usage.yml"


def build_usage_entry(
    *,
    project: str,
    task_id: str,
    skill: dict[str, Any],
    reason: str,
    injected_into: list[str],
) -> dict[str, Any]:
    return {
        "timestamp": utc_now(),
        "project": project,
        "task_id": task_id,
        "skill_id": skill.get("skill_id"),
        "name": skill.get("name") or skill.get("skill_name"),
        "reason": reason,
        "load_tokens": skill.get("load_tokens", 0),
        "expected_saving_tokens": skill.get("expected_saving_tokens", 0),
        "injected_into": injected_into,
    }


def write_task_skill_usage(
    run_dir: Path,
    *,
    project: str,
    task_id: str,
    selected: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    entries: list[dict[str, Any]],
) -> Path:
    data = {
        "schema_version": 2,
        "scope": "run_local",
        "project": project,
        "task_id": task_id,
        "updated_at": utc_now(),
        "selected": selected,
        "rejected": rejected,
        "entries": entries,
    }
    path = task_skill_usage_path(run_dir)
    atomic_write_yaml(path, data)
    return path


def record_skill_usage(
    run_dir: Path,
    *,
    project: str,
    task_id: str,
    selected: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
) -> dict[str, Any]:
    entries = [
        build_usage_entry(
            project=project,
            task_id=task_id,
            skill=item,
            reason=item.get("reason", ""),
            injected_into=item.get("injected_into", []),
        )
        for item in selected
    ]
    task_path = write_task_skill_usage(
        run_dir,
        project=project,
        task_id=task_id,
        selected=selected,
        rejected=rejected,
        entries=entries,
    )
    return {
        "task_usage": str(task_path),
        "scope": "run_local",
    }
