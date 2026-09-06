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
_legacy_handle_get_task_events = _legacy.handle_get_task_events
_legacy_handle_get_task_decisions = _legacy.handle_get_task_decisions
_legacy_handle_resolve_task_decision = _legacy.handle_resolve_task_decision
_legacy_handle_create_project = _legacy.handle_create_project
_legacy_handle_post_decision = _legacy.handle_post_decision
_legacy_handle_run_agent = _legacy.handle_run_agent
_LegacyAgentLabAPIHandler = _legacy.AgentLabAPIHandler


def _sync_legacy_root() -> None:
    """Keep the compatibility module bound to the public bridge root.

    Tests and embedded callers intentionally redirect ``web_ui.server.AGENTLAB_ROOT``.
    The moved legacy module must observe the same root or compatibility reads would
    silently consult a different project tree.
    """

    _legacy.AGENTLAB_ROOT = AGENTLAB_ROOT
    _legacy.AGENTLAB_RUNTIME = AGENTLAB_ROOT / "agent_runtime"


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
    _sync_legacy_root()
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


def handle_get_task_events(project: str, task_id: str) -> dict:
    """Return events from the authoritative v2 ledger or a legacy-only run."""
    project = _project(project)
    _sync_legacy_root()
    if not _v2_exists(project, task_id):
        return _legacy_handle_get_task_events(project, task_id)
    try:
        projection = _read_v2_projection(project, task_id)
    except (TaskRuntimeError, OSError, ValueError) as exc:
        return {"success": False, "error": str(exc), "events": []}
    events = []
    for item in _v2_events(project, task_id):
        raw = dict(item.get("raw") or {})
        events.append(
            {
                "event": raw.get("event_type") or "TASK_EVENT",
                "time": raw.get("recorded_at") or raw.get("timestamp") or "",
                "status": (projection.get("task") or {}).get("status"),
                "message": raw.get("event_type") or "task_event",
                "payload": raw,
            }
        )
    return {
        "success": True,
        "project": project,
        "task_id": task_id,
        "events": events,
        "authority": "task_runtime_v2",
    }


def handle_get_status(project: str, task_id: str):
    """Return a Web-UI-compatible snapshot backed by v2 when that identity exists."""
    project = _project(project)
    _sync_legacy_root()
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


def handle_get_task_decisions(project: str, task_id: str, *, all_statuses: bool = False) -> dict:
    """Expose historical decision cards only for legacy-only task identities."""
    project = _project(project)
    _sync_legacy_root()
    if _v2_exists(project, task_id):
        return {
            "success": True,
            "project": project,
            "task_id": task_id,
            "decisions": [],
            "pending_count": 0,
            "authority": "task_runtime_v2",
        }
    return _legacy_handle_get_task_decisions(project, task_id, all_statuses=all_statuses)


def handle_resolve_task_decision(
    project: str,
    task_id: str,
    decision_id: str,
    resolution: str,
    data: dict,
) -> dict:
    """Resolve a compatibility decision card without introducing a second v2 writer."""
    project = _project(project)
    _sync_legacy_root()
    if _v2_exists(project, task_id):
        return {
            "success": False,
            "error": "Runtime v2 decisions require a governed v2 decision contract.",
            "authority": "task_runtime_v2",
        }
    return _legacy_handle_resolve_task_decision(
        project,
        task_id,
        decision_id,
        resolution,
        data,
    )


def handle_task_control(project: str, task_id: str, action: str, data: dict | None = None) -> dict:
    """Route pause/resume/stop through the shared Operator OS command boundary."""
    project = _project(project)
    _sync_legacy_root()
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


def _create_v2_task(
    project: str,
    task_id: str,
    request_text: str,
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    runtime = _runtime(project)
    return runtime.create_task(
        task_id=task_id,
        title=_legacy.first_line_title(request_text, task_id),
        user_goal=request_text or task_id,
        idempotency_key=idempotency_key,
    )


def _ready_created_task(
    project: str,
    task_id: str,
    *,
    reason: str,
    idempotency_key: str,
) -> dict[str, Any]:
    result = execute_operator_action(
        AGENTLAB_ROOT,
        {
            "action": "resume",
            "target_type": "task",
            "target_id": task_id,
            "project": project,
            "actor": "web_ui",
            "reason": reason,
            "idempotency_key": idempotency_key,
            "source_surface": "web_ui",
        },
    )
    if not result.get("success"):
        raise TaskRuntimeError("; ".join(result.get("errors") or ["failed to ready task"]))
    return _read_v2_projection(project, task_id)


def handle_create_task(data: dict):
    """Create new Web UI tasks in Runtime v2; never create a new legacy run."""
    project = _project(data.get("project", "AgentLab"))
    _sync_legacy_root()
    task_id = str(data.get("taskId") or "").strip()
    request_text = str(data.get("requestText") or "").strip()
    if not task_id:
        return {"success": False, "error": "taskId is required"}
    create_key = str(data.get("idempotencyKey") or f"web-ui-create-{task_id}")
    try:
        projection = _create_v2_task(
            project,
            task_id,
            request_text,
            idempotency_key=create_key,
        )
        if (projection.get("task") or {}).get("status") == "created":
            projection = _ready_created_task(
                project,
                task_id,
                reason="created_from_web_ui",
                idempotency_key=f"{create_key}-ready",
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
    """Create a natural-language request and ready it through Operator OS."""
    project = _project(data.get("project", "AgentLab"))
    _sync_legacy_root()
    request_text = str(data.get("text") or "").strip()
    if not request_text:
        return {"success": False, "error": "任务描述不能为空"}
    task_id = _next_task_id(project)
    create_key = str(data.get("idempotencyKey") or f"web-ui-nl-{task_id}")
    try:
        projection = _create_v2_task(
            project,
            task_id,
            request_text,
            idempotency_key=create_key,
        )
        if (projection.get("task") or {}).get("status") == "created":
            ready = execute_operator_action(
                AGENTLAB_ROOT,
                {
                    "action": "resume",
                    "target_type": "task",
                    "target_id": task_id,
                    "project": project,
                    "actor": data.get("actor") or "web_ui",
                    "reason": data.get("reason") or "natural_language_task_created",
                    "idempotency_key": f"{create_key}-ready",
                    "source_surface": "web_ui",
                },
            )
            if not ready.get("success"):
                raise TaskRuntimeError(
                    "; ".join(ready.get("errors") or ["failed to ready task"])
                )
            projection = _read_v2_projection(project, task_id)
    except (TaskRuntimeError, OSError, ValueError) as exc:
        return {"success": False, "taskId": task_id, "project": project, "error": str(exc)}
    return {
        "success": True,
        "taskId": task_id,
        "project": project,
        "stage": (projection.get("task") or {}).get("status"),
        "authority": "task_runtime_v2",
        "autoExecute": False,
        "message": f"任务 {task_id} 已进入 Task Runtime；实时执行需走受控执行入口",
    }


def handle_create_project(data: dict):
    """Preserve project bootstrap compatibility while the task authority migrates."""
    _sync_legacy_root()
    return _legacy_handle_create_project(data)


def handle_post_decision(data: dict):
    """Resolve a legacy decision through the shared Operator OS boundary."""
    _sync_legacy_root()
    project = _project(data.get("project", "AgentLab"))
    task_id = str(data.get("taskId") or "")
    action = data.get("action", "yes")
    if not task_id:
        return {"error": "taskId is required", "success": False}
    if _v2_exists(project, task_id):
        return {
            "error": "Runtime v2 decisions require a governed v2 decision contract.",
            "success": False,
            "authority": "task_runtime_v2",
        }

    run_dir = AGENTLAB_ROOT / "projects" / project / "runs" / task_id
    if not run_dir.exists():
        return {"error": "Task not found", "success": False}

    operator_action = "approve" if action == "yes" else ("pause" if action == "later" else "reject")
    target_type = "decision_card" if operator_action in {"approve", "reject"} else "task"
    target_id = task_id
    decision_id = data.get("decisionId") or data.get("decision_id")
    option_id = data.get("option") or data.get("option_id")
    if target_type == "decision_card":
        if not decision_id:
            from agent_runtime.feedback_manager import load_pending_decision_cards

            pending = load_pending_decision_cards(run_dir)
            if len(pending) == 1:
                decision_id = pending[0].get("id")
            elif len(pending) > 1:
                return {
                    "error": "decisionId is required when multiple decision cards are pending",
                    "success": False,
                }
            else:
                return {"error": "No pending decision card found", "success": False}
        target_id = str(decision_id)

    result = execute_operator_action(
        AGENTLAB_ROOT,
        {
            "action": operator_action,
            "target_type": target_type,
            "target_id": target_id,
            "task_id": task_id,
            "decision_id": decision_id,
            "option_id": option_id,
            "project": project,
            "actor": data.get("actor") or "web_ui",
            "reason": data.get("reason") or f"web_ui_decision_{action}",
            "source_surface": "web_ui",
        },
    )
    event_text = f"用户{'批准' if action == 'yes' else ('推迟' if action == 'later' else '拒绝')}了决策"
    return {
        "success": bool(result.get("success")),
        "action": action,
        "message": event_text,
        "actionResult": result.get("runtime_status", ""),
        "operator_action": result,
    }


def handle_run_agent(data: dict):
    """Translate historical agent controls into bounded Operator OS actions."""
    _sync_legacy_root()
    project = _project(data.get("project", "AgentLab"))
    task_id = str(data.get("taskId") or "")
    agent_name = data.get("agentName", "")
    action = data.get("action", "run")
    if not task_id:
        return {"success": False, "agentName": agent_name, "error": "taskId is required"}

    if action == "execute":
        result = execute_operator_action(
            AGENTLAB_ROOT,
            {
                "action": "retry",
                "target_type": "task",
                "target_id": task_id,
                "project": project,
                "actor": data.get("actor") or "web_ui",
                "reason": data.get("reason") or f"web_ui_execute_requested:{agent_name}",
                "requested_effects": ["external_executor_enablement"],
                "source_surface": "web_ui",
            },
        )
        return {
            "success": False,
            "agentName": agent_name,
            "action": action,
            "error": "; ".join(result.get("errors") or ["external execution blocked"]),
            "operator_action": result,
        }

    mapped_action = {"run": "resume", "pause": "pause", "stop": "pause"}.get(action)
    if not mapped_action:
        return {
            "success": False,
            "agentName": agent_name,
            "error": f"Unsupported action: {action}",
        }
    result = execute_operator_action(
        AGENTLAB_ROOT,
        {
            "action": mapped_action,
            "target_type": "task",
            "target_id": task_id,
            "project": project,
            "actor": data.get("actor") or "web_ui",
            "reason": data.get("reason") or f"web_ui_agent_action:{action}:{agent_name}",
            "source_surface": "web_ui",
        },
    )
    return {
        "success": bool(result.get("success")),
        "agentName": agent_name,
        "action": action,
        "message": f"Agent {agent_name} {action}",
        "operator_action": result,
    }


# Install the bridge into the historical handler module. The HTTP handler looks
# up these names dynamically in its own module globals.
_legacy.handle_get_tasks = handle_get_tasks
_legacy.handle_get_status = handle_get_status
_legacy.handle_get_task_events = handle_get_task_events
_legacy.handle_get_task_decisions = handle_get_task_decisions
_legacy.handle_resolve_task_decision = handle_resolve_task_decision
_legacy.handle_task_control = handle_task_control
_legacy.handle_create_task = handle_create_task
_legacy.handle_natural_language_task = handle_natural_language_task
_legacy.handle_create_project = handle_create_project
_legacy.handle_post_decision = handle_post_decision
_legacy.handle_run_agent = handle_run_agent


class AgentLabAPIHandler(_LegacyAgentLabAPIHandler):
    """Compatibility HTTP handler that keeps the legacy module on bridge state."""

    def _sse_task_events(self, project: str, task_id: str) -> None:
        _sync_legacy_root()
        return _LegacyAgentLabAPIHandler._sse_task_events(self, project, task_id)


_legacy.AgentLabAPIHandler = AgentLabAPIHandler


def main() -> None:
    _sync_legacy_root()
    _legacy.main()


if __name__ == "__main__":
    main()
