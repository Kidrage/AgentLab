"""Watchdog checks for stale AgentLab task runs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_json, safe_read_yaml
from feedback_manager import create_decision_card, load_pending_decision_cards, write_feedback_status
from task_events import append_task_event, load_task_events


RUNNING_STATUSES = {"running", "in_progress", "active"}
WAITING_STATUSES = {"paused", "blocked", "waiting_for_approval", "blocked_user_decision"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def age_seconds(value: str | None) -> int | None:
    parsed = parse_time(value)
    if parsed is None:
        return None
    return int((utc_now() - parsed).total_seconds())


def load_policy(agentlab_root: Path) -> dict[str, Any]:
    policy = safe_read_yaml(agentlab_root / "config" / "watchdog_policy.yml", default={}) or {}
    thresholds = policy.setdefault("thresholds", {})
    thresholds.setdefault("running_without_heartbeat_seconds", 900)
    thresholds.setdefault("running_without_event_seconds", 900)
    thresholds.setdefault("waiting_for_approval_seconds", 86400)
    thresholds.setdefault("stale_lock_seconds", 1800)
    actions = policy.setdefault("stale_actions", {})
    actions.setdefault("append_event", True)
    actions.setdefault("write_feedback_status", True)
    actions.setdefault("create_decision_card", True)
    actions.setdefault(
        "decision_options",
        [
            {"id": "continue_waiting", "label": "Continue waiting", "risk": "low"},
            {"id": "retry_current_stage", "label": "Retry current stage", "risk": "medium"},
            {"id": "stop_task", "label": "Stop task", "risk": "medium"},
            {"id": "mark_failed_recoverable", "label": "Mark failed recoverable", "risk": "low"},
        ],
    )
    return policy


def _file_age(path: Path) -> int | None:
    if not path.exists():
        return None
    return int(utc_now().timestamp() - path.stat().st_mtime)


def _latest_event_age(run_dir: Path) -> int | None:
    events = load_task_events(run_dir)
    if not events:
        return _file_age(run_dir / "task_events.jsonl")
    return age_seconds(events[-1].get("time"))


def _heartbeat_age(run_dir: Path, progress: dict[str, Any], state: dict[str, Any]) -> int | None:
    for key in ("heartbeat_at", "last_heartbeat_at"):
        value = progress.get(key) or state.get(key)
        age = age_seconds(value)
        if age is not None:
            return age
    for name in ("heartbeat.yml", "heartbeat.json", ".agentlab_heartbeat"):
        age = _file_age(run_dir / name)
        if age is not None:
            return age
    return None


def _raw_status(progress: dict[str, Any], state: dict[str, Any]) -> str:
    return str(progress.get("status") or state.get("status") or "unknown").lower()


def _stale_decision_exists(run_dir: Path) -> bool:
    for card in load_pending_decision_cards(run_dir):
        if card.get("type") == "stale_running":
            return True
    return False


def inspect_task(agentlab_root: Path, project: str, task_id: str, *, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = policy or load_policy(agentlab_root)
    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    progress = safe_read_yaml(run_dir / "progress.yml", default={}) or {}
    state = safe_read_yaml(run_dir / "state.yml", default={}) or {}
    thresholds = policy["thresholds"]
    status = _raw_status(progress, state)
    event_age = _latest_event_age(run_dir)
    heartbeat_age = _heartbeat_age(run_dir, progress, state)
    approval_age = None
    pending = load_pending_decision_cards(run_dir)
    if pending:
        approval_age = age_seconds(pending[0].get("created_at"))
    lock_age = _file_age(run_dir / ".agentlab.lock") or _file_age(run_dir / "task.lock")

    reasons: list[str] = []
    if status in RUNNING_STATUSES:
        if heartbeat_age is None or heartbeat_age > int(thresholds["running_without_heartbeat_seconds"]):
            reasons.append("running_without_heartbeat")
        if event_age is None or event_age > int(thresholds["running_without_event_seconds"]):
            reasons.append("running_without_event")
    if status in WAITING_STATUSES and approval_age is not None:
        if approval_age > int(thresholds["waiting_for_approval_seconds"]):
            reasons.append("waiting_for_approval_too_long")
    if lock_age is not None and lock_age > int(thresholds["stale_lock_seconds"]):
        reasons.append("stale_lock")

    return {
        "project": project,
        "task_id": task_id,
        "run_dir": str(run_dir),
        "raw_status": status,
        "is_stale": bool(reasons),
        "reasons": reasons,
        "event_age_seconds": event_age,
        "heartbeat_age_seconds": heartbeat_age,
        "approval_age_seconds": approval_age,
        "lock_age_seconds": lock_age,
        "pending_decision_count": len(pending),
    }


def mark_stale(agentlab_root: Path, project: str, task_id: str, status: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    actions = policy["stale_actions"]
    created_card = None
    reason = ", ".join(status.get("reasons", [])) or "stale task run"

    if actions.get("append_event", True):
        append_task_event(
            run_dir,
            "STALE_RUNNING",
            stage=status.get("raw_status"),
            status="STALE_RUNNING",
            severity="BLOCKED",
            message=f"Watchdog marked task stale: {reason}.",
            payload={
                "reasons": status.get("reasons", []),
                "event_age_seconds": status.get("event_age_seconds"),
                "heartbeat_age_seconds": status.get("heartbeat_age_seconds"),
                "lock_age_seconds": status.get("lock_age_seconds"),
            },
        )

    if actions.get("create_decision_card", True) and not _stale_decision_exists(run_dir):
        card, _path = create_decision_card(
            run_dir,
            task_id=task_id,
            card_type="stale_running",
            title="Stale running task",
            reason=f"Watchdog detected stale task state: {reason}.",
            stage=status.get("raw_status"),
            options=list(actions.get("decision_options", [])),
            recommended_action="retry_current_stage",
            risk="medium",
        )
        created_card = card

    if actions.get("write_feedback_status", True):
        write_feedback_status(run_dir, stale_after_seconds=0)

    try:
        from webhook_dispatcher import dispatch_event

        dispatch_event(
            agentlab_root,
            event="STALE_RUNNING",
            project=project,
            task_id=task_id,
            stage=status.get("raw_status"),
            severity="BLOCKED",
            summary="Watchdog detected a stale task run.",
            reason=reason,
            decision_card={
                "id": created_card.get("id"),
                "options": created_card.get("options", []),
            } if created_card else None,
        )
    except Exception:
        pass

    result = dict(status)
    result["marked_stale"] = True
    result["decision_card_id"] = created_card.get("id") if created_card else None
    return result


def scan_project(agentlab_root: Path, project: str, *, task_id: str | None = None) -> dict[str, Any]:
    policy = load_policy(agentlab_root)
    runs_root = agentlab_root / "projects" / project / "runs"
    run_dirs = [runs_root / task_id] if task_id else sorted(p for p in runs_root.iterdir() if p.is_dir()) if runs_root.exists() else []
    results: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        if not run_dir.exists():
            continue
        status = inspect_task(agentlab_root, project, run_dir.name, policy=policy)
        if policy.get("enabled", True) and status["is_stale"]:
            status = mark_stale(agentlab_root, project, run_dir.name, status, policy)
        results.append(status)
    summary = {
        "project": project,
        "task_count": len(results),
        "stale_count": len([item for item in results if item.get("is_stale")]),
        "tasks": results,
    }
    atomic_write_json(agentlab_root / "projects" / project / "watchdog_status.json", summary)
    return summary


def watchdog_status(agentlab_root: Path, project: str, task_id: str) -> dict[str, Any]:
    policy = load_policy(agentlab_root)
    return inspect_task(agentlab_root, project, task_id, policy=policy)
