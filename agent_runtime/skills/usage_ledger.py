"""External skill usage ledger API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from atomic_io import atomic_write_yaml, safe_read_yaml
from state_store import utc_now


VALID_EVENTS = {"planned", "used", "skipped", "rejected", "distilled"}


def default_skill_usage_ledger(task_id: str | None = None) -> dict[str, Any]:
    return {"schema_version": 1, "task_id": task_id, "entries": []}


def load_skill_usage_ledger(path: Path) -> dict[str, Any]:
    data = safe_read_yaml(path, default={}) or {}
    if not isinstance(data, dict) or not data:
        data = default_skill_usage_ledger()
    data.setdefault("schema_version", 1)
    data.setdefault("entries", [])
    return data


def write_skill_usage_ledger(path: Path, ledger: dict[str, Any]) -> Path:
    ledger.setdefault("schema_version", 1)
    ledger.setdefault("entries", [])
    atomic_write_yaml(path, ledger)
    return path


def record_skill_event(
    ledger: dict[str, Any],
    *,
    task_id: str,
    skill_id: str,
    source: str,
    event: str,
    reason: str,
    executor: str = "agentlab_internal",
    cost_mode: str = "unknown",
    success: bool | None = None,
    quality_score: float | None = None,
    evidence_artifacts: list[str] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    if event not in VALID_EVENTS:
        raise ValueError(f"Invalid skill usage event: {event}")
    ledger.setdefault("schema_version", 1)
    ledger.setdefault("task_id", task_id)
    ledger.setdefault("entries", [])
    entry = {
        "skill_id": skill_id,
        "source": source,
        "event": event,
        "reason": reason,
        "executor": executor,
        "cost_mode": cost_mode,
        "success": success,
        "quality_score": quality_score,
        "evidence_artifacts": list(evidence_artifacts or []),
        "created_at": created_at or utc_now(),
    }
    ledger["entries"].append(entry)
    return entry
