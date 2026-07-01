"""Deterministic, local-only S11 operations console snapshot API."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import re

import yaml

from agent_runtime.capabilities import create_builtin_registry
from agent_runtime.operator_os import build_operator_action_catalog, build_operator_state

_SECRET_RE = re.compile(r"(?i)(api[_-]?key|token|secret|password|bearer)\s*[:=]\s*[^\s]+")
_PRIVATE_PATH_RE = re.compile(r"/" + r"Users/[^/\s]+")


def _load_yaml(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if data is not None else default


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        text = _PRIVATE_PATH_RE.sub("<redacted-user-path>", value)
        return _SECRET_RE.sub(lambda match: match.group(0).split(match.group(1))[0] + match.group(1) + ": <redacted>", text)
    return value


def validate_dashboard_policy(path: Path) -> dict[str, Any]:
    policy = _load_yaml(path, {})
    policy.setdefault("bind_host", "127.0.0.1")
    policy.setdefault("public_bind_allowed", False)
    policy.setdefault("default_mode", "read_only")
    policy.setdefault("redact_secrets", True)
    policy.setdefault("redact_private_paths", True)
    policy.setdefault("ui_failure_is_non_blocking", True)
    if policy["bind_host"] != "127.0.0.1":
        raise ValueError("S11 dashboard policy must default to 127.0.0.1")
    if policy["public_bind_allowed"]:
        raise ValueError("S11 dashboard policy must not allow public bind by default")
    if policy["default_mode"] != "read_only":
        raise ValueError("S11 dashboard policy must default to read_only")
    if not policy["redact_secrets"] or not policy["redact_private_paths"]:
        raise ValueError("S11 dashboard policy must redact secrets and private paths")
    return policy


def _project_status(root: Path, project: str) -> dict[str, Any]:
    brain_dir = root / "projects" / project / "project_brain"
    acceptance_reports = sorted((root / "acceptance_runs").glob("*/S*_*.md")) if (root / "acceptance_runs").exists() else []
    return {
        "name": project,
        "project_brain_present": brain_dir.exists(),
        "acceptance_report_count": len(acceptance_reports),
        "latest_acceptance_reports": [path.name for path in acceptance_reports[-5:]],
    }


def _skill_status(root: Path) -> dict[str, Any]:
    registry = _load_yaml(root / "projects" / "AgentLab" / "skill_vault" / "registry.yml", {})
    request_files = list(root.glob("projects/*/runs/*/skill_requests.yml"))
    request_counts: dict[str, int] = {"pending_user_approval": 0, "approved": 0, "staging": 0, "validated": 0, "active": 0, "retired": 0}
    for path in request_files:
        data = _load_yaml(path, {})
        requests = data.get("requests", []) if isinstance(data, dict) else []
        for request in requests:
            status = str(request.get("status", "unknown"))
            request_counts[status] = request_counts.get(status, 0) + 1
    if not any(request_counts.values()):
        request_counts["active"] = len(registry.get("skills", [])) if isinstance(registry, dict) else 0
    return {
        "request_counts": request_counts,
        "registry_present": bool(registry),
        "read_only": True,
    }


def _decision_status(root: Path) -> dict[str, Any]:
    cards = list(root.glob("projects/*/runs/*/*DECISION*.md")) + list(root.glob("projects/*/runs/*/decision_cards/*.yml"))
    return {
        "pending_count": len(cards),
        "supported_actions": ["approve", "reject", "resume", "request_replanning"],
        "actions_require_explicit_cli": True,
    }


def build_ops_console_snapshot(root: Path, project: str = "AgentLab") -> dict[str, Any]:
    root = root.resolve()
    policy = validate_dashboard_policy(root / "config" / "ops_console_policy.yml")
    records = create_builtin_registry().to_sorted_records()
    snapshot: dict[str, Any] = {
        "console": {
            "stage": "S11",
            "mode": "ops_console_snapshot",
            "bind_host": policy["bind_host"],
            "read_only": policy["default_mode"] == "read_only",
            "ui_failure_is_non_blocking": policy["ui_failure_is_non_blocking"],
        },
        "project": _project_status(root, project),
        "operator_state": build_operator_state(root, project),
        "operator_actions": build_operator_action_catalog(),
        "roadmap": {
            "visible_sections": ["Project Overview", "Project Brain", "Roadmap / Milestones", "Phase Status", "Task Packets"],
        },
        "skills": _skill_status(root),
        "capabilities": {
            "total": len(records),
            "ids": [record.capability_id for record in records],
            "missing_backend": [record.capability_id for record in records if record.status.value == "missing_backend"],
            "requires_approval": [record.capability_id for record in records if record.status.value == "requires_approval"],
        },
        "decisions": _decision_status(root),
        "evidence": {
            "acceptance_runs_present": (root / "acceptance_runs").exists(),
            "artifact_links_are_relative": True,
        },
        "budget": {
            "resource_ledger_visible": (root / "costs" / "cost_ledger.jsonl").exists(),
            "secrets_displayed": False,
        },
        "security": {
            "local_only": policy["bind_host"] == "127.0.0.1",
            "public_bind_allowed": policy["public_bind_allowed"],
            "secrets_displayed": False,
            "private_paths_redacted": policy["redact_private_paths"],
            "read_only_unless_explicit_action": True,
        },
    }
    return _redact(snapshot)


def write_ops_console_snapshot(root: Path, project: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "ops_console_snapshot.yml"
    data = build_ops_console_snapshot(root, project)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def dry_run_server_plan(root: Path, host: str, port: int) -> dict[str, Any]:
    policy = validate_dashboard_policy(root / "config" / "ops_console_policy.yml")
    if host != "127.0.0.1":
        raise ValueError("S11 ops console may only bind 127.0.0.1 by default; public bind is blocked")
    return {
        "stage": "S11",
        "host": host,
        "port": port,
        "mode": policy["default_mode"],
        "read_only": True,
        "dry_run": True,
        "start_command": f"uvicorn agent_runtime.ops_console.dashboard_app:app --host {host} --port {port}",
    }
