"""Feedback and intervention scaffolding for AgentLab."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_yaml, safe_read_yaml
from task_events import append_task_event, build_decision_card, load_task_events


def decision_cards_dir(run_dir: Path) -> Path:
    return run_dir / "decision_cards"


def write_decision_card(run_dir: Path, card: dict[str, Any]) -> Path:
    card_id = card.get("id")
    if not card_id:
        raise ValueError("Decision card is missing id.")
    path = decision_cards_dir(run_dir) / f"{card_id}.yml"
    atomic_write_yaml(path, card)
    append_task_event(
        run_dir,
        "APPROVAL_REQUIRED",
        stage=card.get("stage"),
        status="WAITING_FOR_APPROVAL",
        severity="ACTION_REQUIRED",
        message=card.get("reason", ""),
        payload={"decision_card": str(path), "type": card.get("type")},
    )
    return path


def create_decision_card(
    run_dir: Path,
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
) -> tuple[dict[str, Any], Path]:
    card = build_decision_card(
        task_id=task_id,
        card_type=card_type,
        title=title,
        reason=reason,
        options=options,
        stage=stage,
        recommended_action=recommended_action,
        cost_preview=cost_preview,
        risk=risk,
    )
    path = write_decision_card(run_dir, card)
    return card, path


def load_pending_decision_cards(run_dir: Path) -> list[dict[str, Any]]:
    root = decision_cards_dir(run_dir)
    if not root.exists():
        return []
    cards: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.yml")):
        data = safe_read_yaml(path, default={}) or {}
        if not isinstance(data, dict):
            continue
        data.setdefault("_path", str(path))
        if data.get("status") in {"pending", "pending_user_approval", "waiting_for_approval"}:
            cards.append(data)
    return cards


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_seconds(value: str | None) -> int | None:
    parsed = _parse_time(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int((datetime.now(timezone.utc) - parsed).total_seconds())


def assess_task_feedback_state(
    run_dir: Path,
    *,
    stale_after_seconds: int = 600,
) -> dict[str, Any]:
    progress = safe_read_yaml(run_dir / "progress.yml", default={}) or {}
    state = safe_read_yaml(run_dir / "state.yml", default={}) or {}
    events = load_task_events(run_dir, limit=10)
    pending_cards = load_pending_decision_cards(run_dir)
    user_decision = run_dir / "USER_DECISION_REQUIRED.md"

    raw_status = progress.get("status") or state.get("status") or "unknown"
    last_event = progress.get("last_event") or state.get("last_event")
    last_event_at = progress.get("last_event_at") or state.get("updated_at")
    age = _age_seconds(last_event_at)

    if pending_cards or user_decision.exists():
        status = "WAITING_FOR_APPROVAL"
        severity = "ACTION_REQUIRED"
    elif raw_status in {"blocked", "paused"}:
        status = "FAILED_RECOVERABLE"
        severity = "BLOCKED"
    elif raw_status in {"running", "in_progress"} and age is not None and age > stale_after_seconds:
        status = "STALE_RUNNING"
        severity = "BLOCKED"
    elif raw_status in {"completed", "complete"}:
        status = "COMPLETED_PASS"
        severity = "COMPLETED"
    elif raw_status in {"failed", "error"}:
        status = "FAILED_FINAL"
        severity = "FAILED_RECOVERABLE"
    else:
        status = str(raw_status).upper()
        severity = "INFO"

    return {
        "run_dir": str(run_dir),
        "raw_status": raw_status,
        "feedback_status": status,
        "notification_level": severity,
        "last_event": last_event,
        "last_event_age_seconds": age,
        "pending_decision_count": len(pending_cards) + (1 if user_decision.exists() else 0),
        "pending_decisions": pending_cards,
        "recent_events": events,
    }


def project_feedback_status(
    agentlab_root: Path,
    project: str,
    *,
    task_id: str | None = None,
    stale_after_seconds: int = 600,
) -> dict[str, Any]:
    runs_root = agentlab_root / "projects" / project / "runs"
    run_dirs = []
    if task_id:
        run_dirs = [runs_root / task_id]
    elif runs_root.exists():
        run_dirs = [p for p in sorted(runs_root.iterdir()) if p.is_dir()]

    tasks = [
        assess_task_feedback_state(run_dir, stale_after_seconds=stale_after_seconds)
        for run_dir in run_dirs
        if run_dir.exists()
    ]
    attention = [
        t for t in tasks
        if t["notification_level"] in {"ACTION_REQUIRED", "BLOCKED", "FAILED_RECOVERABLE"}
    ]
    return {
        "project": project,
        "task_count": len(tasks),
        "needs_attention_count": len(attention),
        "tasks": tasks,
    }
