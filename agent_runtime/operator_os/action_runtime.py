"""Runtime entrypoint for Operator OS actions."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.operator_os.action_contract import validate_operator_action
from agent_runtime.task_events import append_task_event


def execute_operator_action(root: Path | None, request: dict[str, Any]) -> dict[str, Any]:
    """Validate, audit, and apply the minimal durable Operator OS action effect."""
    validation = validate_operator_action(request)
    if validation["status"] == "blocked":
        return {
            "success": False,
            "status": "blocked",
            "validation": validation,
            "mutated_state": False,
            "audit_recorded": False,
            "errors": list(validation["errors"]),
        }

    action = validation["action"]
    if action == "retry" and "external_executor_enablement" in (request.get("requested_effects") or []):
        return _blocked(validation, "external_executor_enablement_requires_explicit_policy")
    if validation["mutates_state"] and (root is None or not request.get("project")):
        return _blocked(validation, "operator_action_requires_project_root")

    audit_event = _audit_event(request, validation)
    audit_path = None
    if root is not None and request.get("project"):
        audit_path = _append_project_action_event(Path(root), str(request["project"]), audit_event)

    runtime_result = _apply_runtime_effect(Path(root) if root is not None else None, request, validation)
    if not runtime_result["success"]:
        return {
            "success": False,
            "status": "blocked",
            "validation": validation,
            "mutated_state": False,
            "audit_recorded": audit_path is not None,
            "audit_path": str(audit_path) if audit_path else None,
            "runtime_status": runtime_result["status"],
            "runtime_result": runtime_result,
            "errors": list(runtime_result.get("errors") or []),
        }

    return {
        "success": True,
        "status": "ok",
        "validation": validation,
        "mutated_state": bool(runtime_result.get("mutated_state")),
        "audit_recorded": audit_path is not None,
        "audit_path": str(audit_path) if audit_path else None,
        "runtime_status": runtime_result["status"],
        "runtime_result": runtime_result,
        "action": action,
        "target_type": validation["target_type"],
        "target_id": request.get("target_id"),
    }


def _blocked(validation: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "success": False,
        "status": "blocked",
        "validation": validation,
        "mutated_state": False,
        "audit_recorded": False,
        "errors": [reason],
    }


def _audit_event(request: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "event_type": validation.get("audit_event_type"),
        "action": validation.get("action"),
        "target_type": validation.get("target_type"),
        "target_id": request.get("target_id"),
        "actor": request.get("actor"),
        "reason": request.get("reason"),
        "requested_effects": list(request.get("requested_effects") or []),
        "runtime_contract": validation.get("runtime_contract"),
        "source_surface": request.get("source_surface") or "unknown",
    }


def _append_project_action_event(root: Path, project: str, event: dict[str, Any]) -> Path:
    project_root = root / "projects" / project
    brain_dir = project_root / "project_brain"
    brain_dir.mkdir(parents=True, exist_ok=True)
    path = brain_dir / "operator_action_ledger.yml"
    ledger = _load_yaml(path, {"schema_version": 1, "entries": []})
    entries = ledger.get("entries") if isinstance(ledger, dict) else []
    entries = entries if isinstance(entries, list) else []
    entries.append(event)
    data = {"schema_version": 1, "entries": entries}
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _apply_runtime_effect(root: Path | None, request: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    if not validation["mutates_state"]:
        return {"success": True, "status": "read_only_contract_validated", "mutated_state": False}
    assert root is not None
    project = str(request["project"])
    target_type = validation["target_type"]
    action = validation["action"]
    target_id = str(request.get("target_id") or "")
    if target_type == "task":
        return _apply_task_effect(root, project, target_id, action, request)
    if target_type == "decision_card":
        return _apply_decision_card_effect(root, project, target_id, action, request)
    if target_type in {"project", "phase", "phase_acceptance", "executor_result"}:
        return _apply_project_brain_effect(root, project, target_type, target_id, action, request)
    return {"success": False, "status": "unsupported_runtime_target", "errors": [f"unsupported_runtime_target:{target_type}"]}


def _apply_task_effect(root: Path, project: str, task_id: str, action: str, request: dict[str, Any]) -> dict[str, Any]:
    run_dir = root / "projects" / project / "runs" / task_id
    if not run_dir.exists():
        return {"success": False, "status": "task_not_found", "errors": [f"task_not_found:{task_id}"]}
    mapping = {
        "pause": ("paused", "paused", "TASK_PAUSED", "WAITING_FOR_APPROVAL", "ACTION_REQUIRED"),
        "resume": ("running", "running", "TASK_RESUMED", "RUNNING", "MILESTONE"),
        "retry": ("retryable", "retry_requested", "TASK_RETRY_REQUESTED", "FAILED_RECOVERABLE", "FAILED_RECOVERABLE"),
    }
    if action not in mapping:
        return _apply_project_brain_effect(root, project, "task", task_id, action, request)
    status, stage, event_name, task_status, severity = mapping[action]
    reason = str(request.get("reason") or action)
    state = _load_yaml(run_dir / "state.yml", {})
    state.update({
        "status": status,
        "last_operator_action": action,
        "last_event": f"Operator {action} requested: {reason}",
        "updated_at": _utc_now(),
    })
    progress = _load_yaml(run_dir / "progress.yml", {})
    progress.update({
        "status": status,
        "current_stage": stage,
        "last_operator_action": action,
        "last_event": f"Operator {action} requested: {reason}",
        "last_event_at": _utc_now(),
    })
    atomic_write_yaml(run_dir / "state.yml", state)
    atomic_write_yaml(run_dir / "progress.yml", progress)
    event = append_task_event(
        run_dir,
        event_name,
        stage=stage,
        status=task_status,
        severity=severity,
        message=f"Operator {action} requested: {reason}",
        payload={
            "actor": request.get("actor"),
            "reason": reason,
            "source_surface": request.get("source_surface") or "unknown",
        },
    )
    return {
        "success": True,
        "status": f"task_{action}_recorded",
        "mutated_state": True,
        "state_path": _rel(run_dir / "state.yml", root),
        "progress_path": _rel(run_dir / "progress.yml", root),
        "event": event,
    }


def _apply_decision_card_effect(root: Path, project: str, target_id: str, action: str, request: dict[str, Any]) -> dict[str, Any]:
    task_id = str(request.get("task_id") or target_id)
    run_dir = root / "projects" / project / "runs" / task_id
    resolution = "approved" if action == "approve" else "rejected" if action == "reject" else None
    if resolution is None:
        return {"success": False, "status": "unsupported_decision_action", "errors": [f"unsupported_decision_action:{action}"]}
    try:
        from agent_runtime.feedback_manager import resolve_decision_card

        card = resolve_decision_card(
            run_dir,
            str(request.get("decision_id") or target_id),
            option_id=request.get("option_id"),
            resolution=resolution,
            actor=str(request.get("actor") or "operator"),
        )
    except Exception as exc:
        return {"success": False, "status": "decision_card_runtime_failed", "errors": [str(exc)]}
    return {"success": True, "status": f"decision_card_{resolution}", "mutated_state": True, "card": card}


def _apply_project_brain_effect(
    root: Path,
    project: str,
    target_type: str,
    target_id: str,
    action: str,
    request: dict[str, Any],
) -> dict[str, Any]:
    brain_dir = root / "projects" / project / "project_brain"
    brain_dir.mkdir(parents=True, exist_ok=True)
    path = brain_dir / "operator_control_state.yml"
    state = _load_yaml(path, {"schema_version": 1, "entries": []})
    entries = state.get("entries") if isinstance(state, dict) else []
    entries = entries if isinstance(entries, list) else []
    entries.append({
        "recorded_at": _utc_now(),
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "actor": request.get("actor"),
        "reason": request.get("reason"),
        "source_surface": request.get("source_surface") or "unknown",
    })
    atomic_write_yaml(path, {
        "schema_version": 1,
        "project_status": _project_status_for_action(action),
        "last_action": action,
        "updated_at": _utc_now(),
        "entries": entries,
    })
    return {
        "success": True,
        "status": f"{target_type}_{action}_recorded",
        "mutated_state": True,
        "control_state_path": _rel(path, root),
    }


def _project_status_for_action(action: str) -> str:
    if action == "pause":
        return "paused"
    if action == "resume":
        return "ready"
    if action == "retry":
        return "retry_requested"
    if action == "reject":
        return "needs_revision"
    if action == "approve":
        return "approved"
    return "updated"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _load_yaml(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return data if data is not None else default
