"""Runtime entrypoint for Operator OS actions."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from agent_runtime.operator_os.action_contract import validate_operator_action


def execute_operator_action(root: Path | None, request: dict[str, Any]) -> dict[str, Any]:
    """Validate and record an operator action through the shared contract.

    This is the only entrypoint UI/TUI code should use for Operator OS mutations.
    It records operator intent and blocks forbidden effects; domain-specific
    acceptance/promotion runtimes remain responsible for durable project changes.
    """
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

    audit_event = _audit_event(request, validation)
    audit_path = None
    if root is not None and request.get("project"):
        audit_path = _append_project_action_event(root, str(request["project"]), audit_event)

    return {
        "success": True,
        "status": "ok",
        "validation": validation,
        "mutated_state": bool(validation["mutates_state"]),
        "audit_recorded": audit_path is not None,
        "audit_path": str(audit_path) if audit_path else None,
        "runtime_status": "audit_recorded" if audit_path else "contract_validated",
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


def _load_yaml(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return data if data is not None else default
