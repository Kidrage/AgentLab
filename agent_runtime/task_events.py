"""Task event log primitives for AgentLab feedback loops."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

from agent_runtime.atomic_io import atomic_write_text


TASK_STATUSES = {
    "QUEUED",
    "PLANNING",
    "WAITING_FOR_APPROVAL",
    "RUNNING",
    "RUNNING_DEGRADED",
    "BLOCKED_PERMISSION",
    "BLOCKED_BUDGET",
    "BLOCKED_MISSING_INFO",
    "BLOCKED_ENVIRONMENT",
    "BLOCKED_TEST_FAILURE",
    "BLOCKED_REPO_DIRTY",
    "FAILED_RECOVERABLE",
    "FAILED_FINAL",
    "COMPLETED_NEEDS_REVIEW",
    "COMPLETED_PASS",
    "COMPLETED_WITH_WARNINGS",
    "STALE_RUNNING",
}

NOTIFICATION_LEVELS = {
    "INFO",
    "MILESTONE",
    "ACTION_REQUIRED",
    "RISK_WARNING",
    "BUDGET_WARNING",
    "BLOCKED",
    "FAILED_RECOVERABLE",
    "COMPLETED",
}

BLOCK_TYPE_TO_STATUS = {
    "permission": "BLOCKED_PERMISSION",
    "budget": "BLOCKED_BUDGET",
    "missing_info": "BLOCKED_MISSING_INFO",
    "environment": "BLOCKED_ENVIRONMENT",
    "test_failure": "BLOCKED_TEST_FAILURE",
    "repo_dirty": "BLOCKED_REPO_DIRTY",
    "validation_command_failed": "BLOCKED_TEST_FAILURE",
    "quota": "BLOCKED_BUDGET",
    "quota_exhausted": "BLOCKED_BUDGET",
    "artifact_validation": "FAILED_RECOVERABLE",
    "artifact_gate": "FAILED_RECOVERABLE",
    "pipeline_error": "FAILED_RECOVERABLE",
    "exception": "FAILED_RECOVERABLE",
    "fallback_handoff": "WAITING_FOR_APPROVAL",
    "user_decision": "WAITING_FOR_APPROVAL",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def task_event_log_path(run_dir: Path) -> Path:
    return run_dir / "task_events.jsonl"


def classify_blocked_status(block_type: str | None) -> str:
    if not block_type:
        return "FAILED_RECOVERABLE"
    return BLOCK_TYPE_TO_STATUS.get(block_type, "FAILED_RECOVERABLE")


def append_task_event(
    run_dir: Path,
    event_type: str,
    *,
    stage: str | None = None,
    status: str | None = None,
    severity: str = "INFO",
    message: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if severity not in NOTIFICATION_LEVELS:
        raise ValueError(f"Unknown notification level: {severity}")
    if status and status not in TASK_STATUSES:
        raise ValueError(f"Unknown task status: {status}")

    event = {
        "time": utc_now(),
        "event": event_type,
        "stage": stage,
        "status": status,
        "severity": severity,
        "message": message,
        "payload": payload or {},
    }
    path = task_event_log_path(run_dir)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    line = json.dumps(event, ensure_ascii=False, sort_keys=True)
    atomic_write_text(path, existing + line + "\n")
    return event


def load_task_events(run_dir: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    path = task_event_log_path(run_dir)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            events.append(data)
    if limit is not None and limit >= 0:
        return events[-limit:]
    return events


def build_decision_card(
    *,
    task_id: str,
    card_type: str,
    title: str,
    reason: str,
    options: list[dict[str, Any]],
    stage: str | None = None,
    recommended_action: str | None = None,
    cost_preview: dict[str, Any] | None = None,
    risk: str = "medium",
) -> dict[str, Any]:
    if not options:
        raise ValueError("Decision card requires at least one option.")
    if recommended_action is None:
        recommended_action = options[0].get("id")
    return {
        "schema_version": 1,
        "id": f"decision_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
        "task_id": task_id,
        "type": card_type,
        "title": title,
        "stage": stage,
        "reason": reason,
        "options": options,
        "recommended_action": recommended_action,
        "risk": risk,
        "cost_preview": cost_preview or {},
        "status": "pending_user_approval",
        "created_at": utc_now(),
    }
