#!/usr/bin/env python3
"""AgentLab Web UI authority bridge.

The historical Web UI implementation remains in ``legacy_server`` during the
Task Runtime migration. This module is the public entrypoint and overrides task
reads, creation, and control so Runtime v2 is authoritative whenever a v2 Task
exists. Legacy runs remain visible only as compatibility records.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

AGENTLAB_ROOT = Path(__file__).resolve().parents[1]
if str(AGENTLAB_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENTLAB_ROOT))

from web_ui import legacy_server as _legacy

from agent_runtime.operator_os.action_runtime import execute_operator_action
from agent_runtime.task_runtime_v2.runtime import TaskRuntime, TaskRuntimeError


# Preserve compatibility implementations before installing the bridge.
_legacy_handle_get_tasks = _legacy.handle_get_tasks
_legacy_handle_get_status = _legacy.handle_get_status
_legacy_handle_task_control = _legacy.handle_task_control
_legacy_handle_create_task = _legacy.handle_create_task
_legacy_handle_natural_language_task = _legacy.handle_natural_language_task


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project(project: str) -> str:
    return _legacy.safe_project_name(project)


def _v2_task_dir(project: str, task_id: str) -> Path:
    return AGENTLAB_ROOT / "projects" / project / "runtime" / "tasks" / task_id


def _v2_exists(project: str, task_id: str) -> bool:
    return _v2_task_dir(project, task_id).exists()


def _runtime(project: str) -> TaskRuntime:
    return TaskRuntime(AGENTLAB_ROOT, project=project)


def _read_v2_projection(project: str, task_id: str) -> dict[str, Any]:
    return _runtime(project).rebuild_task(task_id)


def _task_row_from_projection(task_id: str, projection: dict[str, Any]) -> dict[str, Any]:
    task = dict(projection.get("task") or {})
    return {
        "task_id": task_id,
        "title": task.get("title") or task_id,
        "description": task.get("user_goal") or "",
        "status": task.get("status") or "",
        "priority": "",
        "category": task.get("input_classification", {}).get("kind", "")
        if isinstance(task.get("input_classification"), dict)
        else "",
        "depends_on": [],
        "subtasks": [],
        "authority": "task_runtime_v2",
    }


def handle_get_tasks(project: str):
    """List v2 Tasks first, with legacy-only runs appended for compatibility."""
    project = _project(project)
    rows: dict[str, dict[str, Any]] = {}

    tasks_root = AGENTLAB_ROOT / "projects" / project / "runtime" / "tasks"
    if tasks_root.exists():
        for task_dir in sorted(path for path in tasks_root.iterdir() if path.is_dir()):
            try:
                projection = _read_v2_projection(project, task_dir.name)
            except (TaskRuntimeError, OSError, ValueError) as exc:
                rows[task_dir.name] = {
                    "task_id": task_dir.name,
                    "title": task_dir.name,
                    "description": "",
                    "status": "corrupt",
                    "priority": "",
                    "category": "",
                    "depends_on": [],
                    "subtasks": [],
                    "authority": "task_runtime_v2",
                    "error": str(exc),
                }
            else:
                rows[task_dir.name] = _task_row_from_projection(task_dir.name, projection)

    legacy_result = _legacy_handle_get_tasks(project)
    for legacy_row in legacy_result.get("tasks", []):
        task_id = str(legacy_row.get("task_id") or "")
        if not task_id or task_id in rows:
            continue
        row = dict(legacy_row)
        row["authority"] = "legacy_runs_compat"
        rows[task_id] = row

    return {"project": project, "tasks": list(rows.values())}


def _v2_events(project: str, task_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    path = _v2_task_dir(project, task_id) / "events.jsonl"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
            event = json.loads(raw_line)
            events.append(
                {
                    "time": event.get("recorded_at") or event.get("timestamp") or "",
                    "level": "info",
                    "agent": event.get("entity_type") or "TaskRuntime",
                    "text": event.get("event_type") or "task_event",
                    "raw": event,
                }
            )
    except (OSError, json.JSONDecodeError):
        return []
    return events


def handle_get_status(project: str, task_id: str):
    """Return a Web-UI-compatible snapshot backed by v2 when that identity exists."""
    project = _project(project)
    if not task_id or not _v2_exists(project, task_id):
        return _legacy_handle_get_status(project, task_id)

    try:
        projection = _read_v2_projection(project, task_id)
    except (TaskRuntimeError, OSError, ValueError) as exc:
        return {
            "generatedAt": _utc_now_iso(),
            "project": project,
            "taskId": task_id,
            "taskStatus": "corrupt",
            "stage": "Task Runtime integrity failure",
            "authority": "task_runtime_v2",
            "error": str(exc),
            "route": [],
            "agents": [],
            "events": [],
            "costLedger": [],
            "decisions": [],
            "hasUserDecision": False,
            "userDecisionText": "",
        }

    task = dict(projection.get("task") or {})
    overview = _legacy_handle_get_status(project, "")
    overview.update(
        {
            "generatedAt": _utc_now_iso(),
            "project": project,
            "taskId": task_id,
            "taskStatus": task.get("status") or "created",
            "stage": task.get("status") or "created",
            "snapshot": projection,
            "userRequest": str(task.get("user_goal") or "")[:2000],
            "workflowDriver": "task_runtime_v2",
            "authority": "task_runtime_v2",
            "route": [],
            "agents": [],
            "events": _v2_events(project, task_id)
            or [{"time": "--", "level": "info", "agent": "TaskRuntime", "text": "No events"}],
            "costLedger": [],
            "decisions": [],
            "hasUserDecision": False,
            "userDecisionText": "",
        }
    )
    return overview


def handle_task_control(project: str, task_id: str, action: str, data: dict | None = None) -> dict:
    """Route pause/resume/stop through the shared Operator OS command boundary."""
    project = _project(project)
    data = data or {}
    mapped_action = {"pause": "pause", "resume": "resume", "stop": "cancel"}.get(action)
    if mapped_action is None:
        return {"success": False, "error": f"Unsupported action: {action}"}

    # Preserve the legacy decision-card guard without permitting direct YAML writes.
    if action == "resume" and not _v2_exists(project, task_id):
        run_dir = AGENTLAB_ROOT / "projects" / project / "runs" / task_id
        if run_dir.exists():
            from agent_runtime.feedback_manager import load_pending_decision_cards

            if load_pending_decision_cards(run_dir):
                return {"success": False, "error": "Task still has pending decision cards."}

    result = execute_operator_action(
        AGENTLAB_ROOT,
        {
            "action": mapped_action,
            "target_type": "task",
            "target_id": task_id,
            "project": project,
            "actor": data.get("actor") or "web_ui",
            "reason": data.get("reason") or f"web_ui_{action}",
            "idempotency_key": data.get("idempotencyKey") or data.get("idempotency_key"),
            "source_surface": "web_ui",
        },
    )
    return {
        "success": bool(result.get("success")),
        "project": project,
        "task_id": task_id,
        "action": action,
        "authority": (result.get("runtime_result") or {}).get("authority"),
        "operator_action": result,
        "error": None if result.get("success") else "; ".join(result.get("errors") or []),
    }


def _create_v2_task(project: str, task_id: str, request_text: str, *, idempotency_key: str) -> dict[str, Any]:
    runtime = _runtime(project)
    projection = runtime.create_task(
        task_id=task_id,
        title=_legacy.first_line_title(request_text, task_id),
        user_goal=request_text or task_id,
        idempotency_key=idempotency_key,
    )
    if (projection.get("task") or {}).get("status") == "created":
        projection = runtime.transition_task(
            task_id,
            status="ready",
            idempotency_key=f"{idempotency_key}-ready",
            reason="created_from_web_ui",
        )
    return projection


def handle_create_task(data: dict):
    """Create new Web UI tasks in Runtime v2; never create a new legacy run."""
    project = _project(data.get("project", "AgentLab"))
    task_id = str(data.get("taskId") or "").strip()
    request_text = str(data.get("requestText") or "").strip()
    if not task_id:
        return {"success": False, "error": "taskId is required"}
    try:
        projection = _create_v2_task(
            project,
            task_id,
            request_text,
            idempotency_key=str(data.get("idempotencyKey") or f"web-ui-create-{task_id}"),
        )
    except (TaskRuntimeError, OSError, ValueError) as exc:
        return {"success": False, "taskId": task_id, "project": project, "error": str(exc)}
    return {
        "success": True,
        "taskId": task_id,
        "project": project,
        "stage": (projection.get("task") or {}).get("status"),
        "authority": "task_runtime_v2",
        "message": f"Task {task_id} created in Task Runtime.",
    }


def _next_task_id(project: str) -> str:
    identifiers: set[str] = set()
    v2_root = AGENTLAB_ROOT / "projects" / project / "runtime" / "tasks"
    legacy_root = AGENTLAB_ROOT / "projects" / project / "runs"
    for root in (v2_root, legacy_root):
        if root.exists():
            identifiers.update(path.name for path in root.iterdir() if path.is_dir())
    max_num = 0
    for identifier in identifiers:
        if not identifier.startswith("task_"):
            continue
        try:
            max_num = max(max_num, int(identifier.removeprefix("task_")))
        except ValueError:
            continue
    return f"task_{max_num + 1:04d}"


def handle_natural_language_task(data: dict):
    """Create a natural-language request as a ready v2 Task."""
    project = _project(data.get("project", "AgentLab"))
    request_text = str(data.get("text") or "").strip()
    if not request_text:
        return {"success": False, "error": "任务描述不能为空"}
    task_id = _next_task_id(project)
    result = handle_create_task(
        {
            "project": project,
            "taskId": task_id,
            "requestText": request_text,
            "idempotencyKey": data.get("idempotencyKey") or f"web-ui-nl-{task_id}",
        }
    )
    if result.get("success"):
        result["autoExecute"] = False
        result["message"] = f"任务 {task_id} 已进入 Task Runtime；实时执行需走受控执行入口"
    return result


# Install the bridge into the historical handler module. The HTTP handler looks
# up these names dynamically in its own module globals.
_legacy.handle_get_tasks = handle_get_tasks
_legacy.handle_get_status = handle_get_status
_legacy.handle_task_control = handle_task_control
_legacy.handle_create_task = handle_create_task
_legacy.handle_natural_language_task = handle_natural_language_task

AgentLabAPIHandler = _legacy.AgentLabAPIHandler


def main() -> None:
    _legacy.main()


if __name__ == "__main__":
    main()
