"""AgentLab Daemon MVP — background task supervisor with --once mode support."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import time

from atomic_io import atomic_write_json, safe_read_yaml
from watchdog import inspect_task, mark_stale, scan_project
from webhook_dispatcher import dispatch_event, record_webhook_failure


def utc_now() -> dict[str, str]:
    """Return a timestamp dict for heartbeat files."""
    now = datetime.now(timezone.utc).isoformat()
    return {"timestamp": now, "tz": "UTC"}


def daemon_policy_path(agentlab_root: Path) -> Path:
    return agentlab_root / "config" / "daemon_policy.yml"


def load_daemon_policy(agentlab_root: Path) -> dict[str, Any]:
    policy = safe_read_yaml(daemon_policy_path(agentlab_root), default={}) or {}
    policy.setdefault("schema_version", 1)
    policy.setdefault("enabled", False)
    policy.setdefault("scan_interval_seconds", 30)
    policy.setdefault("projects", ["AgentLab"])
    policy.setdefault("dispatch_webhooks", True)
    policy.setdefault("write_heartbeat", True)
    return policy


def write_heartbeat(agentlab_root: Path) -> Path:
    """Write a daemon heartbeat file so operators can confirm liveness."""
    path = agentlab_root / ".agentlab_daemon_heartbeat.json"
    atomic_write_json(path, utc_now())
    return path


def _list_runs(agentlab_root: Path, project: str) -> list[Path]:
    runs_root = agentlab_root / "projects" / project / "runs"
    if not runs_root.exists():
        return []
    return [p for p in sorted(runs_root.iterdir()) if p.is_dir()]


def _is_actionable(status: dict[str, Any]) -> bool:
    """Check if a task's feedback state needs daemon action."""
    return status.get("notification_level") in {
        "ACTION_REQUIRED",
        "BLOCKED",
        "FAILED_RECOVERABLE",
    }


def scan_and_act(
    agentlab_root: Path,
    *,
    project: str,
    dispatch_webhooks: bool = True,
    write_heartbeat_flag: bool = True,
) -> dict[str, Any]:
    """Run one watchdog scan + webhook dispatch cycle."""
    from watchdog import load_policy as watchdog_policy, inspect_task, mark_stale
    from feedback_manager import assess_task_feedback_state

    if write_heartbeat_flag:
        write_heartbeat(agentlab_root)

    wd_policy = watchdog_policy(agentlab_root)
    results: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []

    for run_dir in _list_runs(agentlab_root, project):
        task_id = run_dir.name
        if not run_dir.exists():
            continue

        # Run watchdog inspection
        wd_status = inspect_task(agentlab_root, project, task_id, policy=wd_policy)

        # If stale and watchdog policy allows, mark it
        if wd_status["is_stale"] and wd_policy.get("enabled", True):
            wd_status = mark_stale(agentlab_root, project, task_id, wd_status, wd_policy)
            actions.append({
                "task_id": task_id,
                "action": "marked_stale",
                "reasons": wd_status.get("reasons", []),
                "decision_card_id": wd_status.get("decision_card_id"),
            })

        # Check feedback state for ACTION_REQUIRED events
        fb_status = assess_task_feedback_state(run_dir)
        if _is_actionable(fb_status) and dispatch_webhooks:
            try:
                dispatch_event(
                    agentlab_root,
                    event="ACTION_REQUIRED",
                    project=project,
                    task_id=task_id,
                    stage=fb_status.get("raw_status", "unknown"),
                    severity=fb_status.get("notification_level", "ACTION_REQUIRED"),
                    summary=f"Daemon detected {fb_status.get('feedback_status')} for {task_id}",
                    reason=str(fb_status.get("pending_decisions", []) or fb_status.get("feedback_status")),
                )
            except Exception as exc:
                record_webhook_failure(
                    agentlab_root,
                    event="ACTION_REQUIRED",
                    project=project,
                    task_id=task_id,
                    error=str(exc),
                    context={"source": "daemon.scan_and_act"},
                )

        results.append(wd_status)

    summary = {
        "project": project,
        "timestamp": utc_now()["timestamp"],
        "task_count": len(results),
        "stale_count": len([r for r in results if r.get("is_stale")]),
        "actions_taken": len(actions),
        "actions": actions,
    }
    atomic_write_json(agentlab_root / "projects" / project / "daemon_status.json", summary)
    return summary


def run_daemon_once(
    agentlab_root: Path,
    *,
    project: str | None = None,
    dispatch_webhooks: bool | None = None,
) -> dict[str, Any]:
    """Run one daemon scan cycle (--once mode)."""
    policy = load_daemon_policy(agentlab_root)
    projects = [project] if project else policy.get("projects", ["AgentLab"])
    do_webhooks = dispatch_webhooks if dispatch_webhooks is not None else policy.get("dispatch_webhooks", True)
    do_heartbeat = policy.get("write_heartbeat", True)

    all_summaries = []
    for proj in projects:
        summary = scan_and_act(
            agentlab_root,
            project=proj,
            dispatch_webhooks=do_webhooks,
            write_heartbeat_flag=do_heartbeat,
        )
        all_summaries.append(summary)

    return {
        "daemon_mode": "once",
        "projects_scanned": len(all_summaries),
        "summaries": all_summaries,
    }


def daemon_status(agentlab_root: Path, project: str) -> dict[str, Any]:
    """Read the last daemon scan status."""
    path = agentlab_root / "projects" / project / "daemon_status.json"
    if not path.exists():
        return {"project": project, "status": "no_scan_yet", "timestamp": None}
    data = safe_read_yaml(path, default={}) or {}
    # Handle both JSON dict and YAML dict
    if isinstance(data, dict):
        return data
    return {"project": project, "status": "unreadable", "path": str(path)}