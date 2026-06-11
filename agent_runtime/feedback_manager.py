"""Feedback and intervention scaffolding for AgentLab."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_json, atomic_write_text, atomic_write_yaml, safe_read_yaml
from task_events import append_task_event, build_decision_card, load_task_events


def decision_cards_dir(run_dir: Path) -> Path:
    return run_dir / "decision_cards"


def feedback_status_path(run_dir: Path) -> Path:
    return run_dir / "feedback_status.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_from_run_dir(run_dir: Path) -> tuple[Path, str, str]:
    task_id = run_dir.name
    project = run_dir.parent.parent.name
    agentlab_root = run_dir.parent.parent.parent.parent
    return agentlab_root, project, task_id


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
    try:
        from webhook_dispatcher import dispatch_event

        agentlab_root, project, task_id = _project_from_run_dir(run_dir)
        dispatch_event(
            agentlab_root,
            event="ACTION_REQUIRED",
            project=project,
            task_id=task_id,
            stage=card.get("stage"),
            severity="ACTION_REQUIRED",
            summary=card.get("title", "Decision required"),
            reason=card.get("reason", ""),
            decision_card={
                "id": card.get("id"),
                "options": card.get("options", []),
            },
        )
    except Exception:
        pass
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


def load_decision_card(run_dir: Path, decision_id: str) -> tuple[dict[str, Any] | None, Path | None]:
    root = decision_cards_dir(run_dir)
    path = root / f"{decision_id}.yml"
    if path.exists():
        data = safe_read_yaml(path, default={}) or {}
        return (data if isinstance(data, dict) else {}), path
    for candidate in sorted(root.glob("*.yml")) if root.exists() else []:
        data = safe_read_yaml(candidate, default={}) or {}
        if isinstance(data, dict) and data.get("id") == decision_id:
            return data, candidate
    return None, None


def resolve_decision_card(
    run_dir: Path,
    decision_id: str,
    *,
    option_id: str | None = None,
    resolution: str = "approved",
    actor: str = "user",
) -> dict[str, Any]:
    card, path = load_decision_card(run_dir, decision_id)
    if not card or path is None:
        raise FileNotFoundError(f"Decision card not found: {decision_id}")

    valid_resolutions = {"approved", "rejected", "deferred"}
    if resolution not in valid_resolutions:
        raise ValueError(f"Unsupported decision resolution: {resolution}")

    if option_id:
        options = {item.get("id") for item in card.get("options", [])}
        if option_id not in options:
            raise ValueError(f"Unknown option for {decision_id}: {option_id}")
    elif resolution == "approved":
        option_id = card.get("recommended_action")

    card["status"] = resolution
    card["selected_option"] = option_id
    card["resolved_by"] = actor
    card["resolved_at"] = utc_now()
    atomic_write_yaml(path, card)

    user_decision_path = run_dir / "USER_DECISION_REQUIRED.md"
    archived_user_decision = None
    if resolution == "approved" and user_decision_path.exists():
        archive_path = decision_cards_dir(run_dir) / f"{decision_id}_USER_DECISION_REQUIRED.approved.md"
        atomic_write_text(archive_path, user_decision_path.read_text(encoding="utf-8"), encoding="utf-8")
        user_decision_path.unlink()
        archived_user_decision = str(archive_path)

    append_task_event(
        run_dir,
        "USER_DECISION_RECORDED",
        stage=card.get("stage"),
        status="RUNNING" if resolution == "approved" else "WAITING_FOR_APPROVAL",
        severity="MILESTONE" if resolution == "approved" else "ACTION_REQUIRED",
        message=f"Decision {decision_id} {resolution}.",
        payload={
            "decision_id": decision_id,
            "selected_option": option_id,
            "resolution": resolution,
            "archived_user_decision": archived_user_decision,
        },
    )
    write_feedback_status(run_dir)
    return card


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
    legacy_decision_count = 1 if user_decision.exists() and not pending_cards else 0

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
        "pending_decision_count": len(pending_cards) + legacy_decision_count,
        "pending_decisions": pending_cards,
        "recent_events": events,
    }


def write_feedback_status(run_dir: Path, *, stale_after_seconds: int = 600) -> Path:
    status = assess_task_feedback_state(run_dir, stale_after_seconds=stale_after_seconds)
    path = feedback_status_path(run_dir)
    atomic_write_json(path, status)
    return path


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
