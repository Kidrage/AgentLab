"""Validate returned artifacts from coalesced CLI workflow-shell sessions.

This module is intentionally read-only with respect to provider execution. It
checks the AgentLab-facing receipts that a trusted shell runner returns after
executing a coalesced Hermes/Claude/etc. session.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

try:
    from agent_runtime.report_sanitizer import write_report_yaml
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from report_sanitizer import write_report_yaml


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _packet_sha256(packet: dict[str, Any]) -> str:
    return hashlib.sha256(
        yaml.safe_dump(packet, sort_keys=True, allow_unicode=True).encode("utf-8")
    ).hexdigest()


def _rel_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve(strict=False).relative_to(root.resolve(strict=False)))
    except ValueError:
        return str(path)


def _resolve(root: Path, base: Path, path_text: str) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    root_relative_prefixes = {
        "acceptance_runs",
        "agent_runtime",
        "config",
        "docs",
        "projects",
        "skills",
        "tests",
    }
    if path.parts and path.parts[0] in root_relative_prefixes:
        return root / path
    return base / path


def _session_receipt_name(coalescing_mode: str) -> str:
    if coalescing_mode == "board_mediated":
        return "shell_board_sync_receipt.yml"
    return "shell_subagent_delegation_receipt.yml"


def _is_pass_receipt(data: dict[str, Any]) -> bool:
    return data.get("status") == "pass" or data.get("accepted") is True


def _role_receipt_check(
    root: Path,
    packet_dir: Path,
    role: dict[str, Any],
    source_packet_sha256: str,
) -> dict[str, Any]:
    role_name = str(role.get("role") or "")
    receipt_path = _resolve(root, packet_dir, str(role.get("receipt_path") or ""))
    validation_path = _resolve(root, packet_dir, str(role.get("validation_evidence_path") or ""))
    receipt = _read_yaml(receipt_path)
    validation = _read_yaml(validation_path)
    receipt_exists = receipt_path.is_file() and receipt_path.stat().st_size > 0
    validation_exists = validation_path.is_file() and validation_path.stat().st_size > 0
    role_matches = not receipt_exists or str(receipt.get("role") or role_name) == role_name
    validation_matches = not validation_exists or str(validation.get("role") or role_name) == role_name
    receipt_pass = receipt_exists and _is_pass_receipt(receipt)
    validation_pass = validation_exists and _is_pass_receipt(validation)
    synthetic_scope_safe = (
        receipt.get("acceptance_scope") == "synthetic_native_surface_smoke"
        and validation.get("acceptance_scope") == "synthetic_native_surface_smoke"
        and receipt.get("private_project_context_loaded") is False
        and validation.get("private_project_context_loaded") is False
    )
    receipt_hash_matches = receipt.get("source_packet_sha256") == source_packet_sha256
    validation_hash_matches = validation.get("source_packet_sha256") == source_packet_sha256
    packet_hash_matches = receipt_hash_matches and validation_hash_matches
    production_safe = (
        receipt.get("production_promotion_attempted") is not True
        and receipt.get("production_promotion_allowed") is not True
        and validation.get("production_promotion_attempted") is not True
        and validation.get("production_promotion_allowed") is not True
    )
    returned_artifacts = receipt.get("returned_artifacts") or receipt.get("artifacts") or []
    returned_artifacts_declared = isinstance(returned_artifacts, list) and bool(returned_artifacts)
    if returned_artifacts_declared:
        returned_artifacts_exist = all(
            _resolve(root, packet_dir, str(item)).is_file()
            for item in returned_artifacts
            if str(item).strip()
        )
    else:
        returned_artifacts_exist = False
    accepted = (
        receipt_exists
        and validation_exists
        and receipt_pass
        and validation_pass
        and role_matches
        and validation_matches
        and synthetic_scope_safe
        and packet_hash_matches
        and production_safe
        and returned_artifacts_declared
        and returned_artifacts_exist
    )
    missing = []
    if not receipt_exists:
        missing.append(_rel_path(root, receipt_path))
    if not validation_exists:
        missing.append(_rel_path(root, validation_path))
    stale = []
    if receipt_exists and not receipt_hash_matches:
        stale.append(_rel_path(root, receipt_path))
    if validation_exists and not validation_hash_matches:
        stale.append(_rel_path(root, validation_path))
    failures = []
    if receipt_exists and receipt_hash_matches and not receipt_pass:
        failures.append("role receipt did not pass")
    if validation_exists and validation_hash_matches and not validation_pass:
        failures.append("validation evidence did not pass")
    if packet_hash_matches and not role_matches:
        failures.append("role receipt role does not match delegated role")
    if packet_hash_matches and not validation_matches:
        failures.append("validation evidence role does not match delegated role")
    if receipt_exists and validation_exists and packet_hash_matches and not synthetic_scope_safe:
        failures.append("role receipt does not prove synthetic scope without private project context")
    if packet_hash_matches and not production_safe:
        failures.append("role receipt or validation attempted production promotion")
    if receipt_exists and receipt_hash_matches and not returned_artifacts_declared:
        failures.append("role receipt did not declare any returned artifacts")
    if receipt_hash_matches and not returned_artifacts_exist:
        if returned_artifacts_declared:
            failures.append("one or more returned artifact paths are missing")
    return {
        "role": role_name,
        "status": "pass" if accepted else ("fail" if failures else ("stale" if stale else "missing")),
        "accepted": accepted,
        "receipt_path": _rel_path(root, receipt_path),
        "validation_evidence_path": _rel_path(root, validation_path),
        "missing": missing,
        "stale": stale,
        "failures": failures,
    }


def _packet_status(root: Path, packet_path: Path) -> dict[str, Any]:
    packet = _read_yaml(packet_path)
    source_packet_sha256 = _packet_sha256(packet)
    packet_exists = packet_path.is_file()
    packet_dir = packet_path.parent
    coalescing_mode = str(packet.get("coalescing_mode") or "")
    session_receipt_path = packet_dir / _session_receipt_name(coalescing_mode)
    session_receipt = _read_yaml(session_receipt_path)
    delegated_roles = (
        packet.get("delegated_roles") if isinstance(packet.get("delegated_roles"), list) else []
    )
    authority = packet.get("agentlab_authority") if isinstance(packet.get("agentlab_authority"), dict) else {}
    contract = packet.get("acceptance_contract") if isinstance(packet.get("acceptance_contract"), dict) else {}
    task_contract = packet.get("task_contract") if isinstance(packet.get("task_contract"), dict) else {}
    execution = packet.get("execution_contract") if isinstance(packet.get("execution_contract"), dict) else {}
    role_checks = [
        _role_receipt_check(root, packet_dir, role, source_packet_sha256)
        for role in delegated_roles
        if isinstance(role, dict)
    ]
    missing: list[str] = []
    stale: list[str] = []
    failures: list[str] = []
    if not packet_exists:
        missing.append(_rel_path(root, packet_path))
    if packet_exists and packet.get("packet_type") != "agentlab_coalesced_cli_shell_session":
        failures.append("packet_type is not agentlab_coalesced_cli_shell_session")
    if packet.get("provider_calls_executed_by_packet_generation") is not False:
        failures.append("packet generation does not record provider_calls_executed_by_packet_generation=false")
    if authority.get("shell_state_counts_as_project_memory") is not False:
        failures.append("packet does not preserve shell_state_counts_as_project_memory=false")
    if authority.get("production_promotion_allowed") is not False:
        failures.append("packet does not preserve production_promotion_allowed=false")
    if contract.get("must_return_one_receipt_per_role") is not True:
        failures.append("packet does not require one receipt per role")
    if contract.get("must_return_validation_evidence_per_role") is not True:
        failures.append("packet does not require validation evidence per role")
    if (
        task_contract.get("acceptance_scope") != "synthetic_native_surface_smoke"
        or task_contract.get("synthetic_input_only") is not True
        or task_contract.get("private_project_context_loaded") is not False
    ):
        failures.append("packet does not preserve synthetic scope without private project context")
    if (
        execution.get("isolated_execution_workspace_required") is not True
        or execution.get("project_read_tools_allowed") is not False
    ):
        failures.append("packet does not require an isolated workspace with project read tools disabled")
    for role in delegated_roles:
        role_task = role.get("task") if isinstance(role, dict) and isinstance(role.get("task"), dict) else {}
        fixture = role_task.get("synthetic_fixture") if isinstance(role_task.get("synthetic_fixture"), dict) else {}
        if (
            role_task.get("read_scope") != []
            or role_task.get("private_project_context_loaded") is not False
            or fixture.get("fixture_id") != "agentlab-cli-native-surface-smoke-v1"
        ):
            failures.append(f"delegated role {role.get('role')} does not preserve synthetic no-read scope")
    if not delegated_roles:
        failures.append("packet has no delegated roles")
    session_receipt_exists = session_receipt_path.is_file() and session_receipt_path.stat().st_size > 0
    session_hash_matches = session_receipt.get("source_packet_sha256") == source_packet_sha256
    if not session_receipt_exists:
        missing.append(_rel_path(root, session_receipt_path))
    elif not session_hash_matches:
        stale.append(_rel_path(root, session_receipt_path))
    else:
        expected_roles = {
            str(role.get("role")) for role in delegated_roles if isinstance(role, dict) and role.get("role")
        }
        returned_roles = {
            str(role) for role in session_receipt.get("delegated_roles", []) if str(role).strip()
        }
        if not _is_pass_receipt(session_receipt):
            failures.append(f"{session_receipt_path.name} did not pass")
        if session_receipt.get("backend") != packet.get("backend"):
            failures.append("shell receipt backend does not match packet backend")
        if session_receipt.get("coalescing_mode") != packet.get("coalescing_mode"):
            failures.append("shell receipt coalescing_mode does not match packet")
        if session_receipt.get("native_surface_used") != execution.get("native_surface"):
            failures.append("shell receipt does not prove the registered native surface was used")
        if returned_roles != expected_roles:
            failures.append("shell receipt delegated roles do not match packet roles")
        if session_receipt.get("frontdesk_role_invocations") != 0:
            failures.append("shell receipt does not preserve frontdesk_role_invocations=0")
        if session_receipt.get("provider_calls_executed_by_shell_session") is not True:
            failures.append("shell receipt does not prove provider execution by the shell session")
        if (
            session_receipt.get("acceptance_scope") != "synthetic_native_surface_smoke"
            or session_receipt.get("private_project_context_loaded") is not False
        ):
            failures.append("shell receipt does not prove synthetic scope without private project context")
        if (
            session_receipt.get("execution_workspace_isolated") is not True
            or session_receipt.get("project_read_tools_enabled") is not False
        ):
            failures.append("shell receipt does not prove isolated execution with project read tools disabled")
        if (
            session_receipt.get("production_promotion_attempted") is not False
            or session_receipt.get("production_promotion_allowed") is not False
        ):
            failures.append("shell receipt does not preserve the production promotion boundary")
    for role_check in role_checks:
        missing.extend(role_check["missing"])
        stale.extend(role_check["stale"])
        failures.extend(role_check["failures"])
    accepted_role_count = sum(1 for role_check in role_checks if role_check["accepted"])
    all_roles_accepted = bool(role_checks) and accepted_role_count == len(role_checks)
    accepted = (
        packet_exists
        and not missing
        and not stale
        and not failures
        and all_roles_accepted
        and session_receipt_path.is_file()
    )
    return {
        "packet_path": _rel_path(root, packet_path),
        "backend": packet.get("backend"),
        "coalescing_mode": coalescing_mode,
        "status": "pass" if accepted else ("fail" if failures else ("stale" if stale else "missing")),
        "accepted": accepted,
        "session_receipt_path": _rel_path(root, session_receipt_path),
        "delegated_role_count": len(role_checks),
        "accepted_role_count": accepted_role_count,
        "missing": missing,
        "stale": stale,
        "failures": failures,
        "role_checks": role_checks,
        "provider_calls_executed_by_shell_session": session_receipt.get(
            "provider_calls_executed_by_shell_session"
        ),
        "source_packet_sha256": source_packet_sha256,
    }


def build_cli_shell_coalescing_status(
    root: Path,
    plan_path: Path | None = None,
) -> dict[str, Any]:
    """Build a returned-artifact status report for coalesced shell sessions."""
    root = root.resolve()
    plan_path = plan_path or (
        root / "acceptance_runs" / "agentlab_capability_acceptance" / "cli_shell_coalescing_plan.yml"
    )
    if not plan_path.is_absolute():
        plan_path = root / plan_path
    plan = _read_yaml(plan_path)
    packet_paths = [
        _resolve(root, plan_path.parent, str(path))
        for path in plan.get("materialized_session_packets", [])
        if str(path).strip()
    ]
    packet_statuses = [_packet_status(root, packet_path) for packet_path in packet_paths]
    missing = sorted(
        {
            path
            for packet_status in packet_statuses
            for path in packet_status.get("missing", [])
            if path
        }
    )
    stale = sorted(
        {
            path
            for packet_status in packet_statuses
            for path in packet_status.get("stale", [])
            if path
        }
    )
    failures = [
        {
            "packet_path": packet_status.get("packet_path"),
            "failures": packet_status.get("failures", []),
        }
        for packet_status in packet_statuses
        if packet_status.get("failures")
    ]
    accepted_packet_count = sum(1 for packet_status in packet_statuses if packet_status.get("accepted") is True)
    total_role_count = sum(int(packet_status.get("delegated_role_count") or 0) for packet_status in packet_statuses)
    accepted_role_count = sum(int(packet_status.get("accepted_role_count") or 0) for packet_status in packet_statuses)
    returned_shell_sessions_provider_calls_executed = bool(packet_statuses) and all(
        packet_status.get("provider_calls_executed_by_shell_session") is True
        for packet_status in packet_statuses
    )
    expected_packet_count = plan.get("eligible_group_count") if isinstance(plan.get("eligible_group_count"), int) else 0
    plan_ready = (
        plan.get("status") == "pass"
        and expected_packet_count > 0
        and len(packet_paths) == expected_packet_count
        and not plan.get("missing_session_packets")
    )
    status = "pass"
    if not plan_ready:
        status = "fail"
    elif failures:
        status = "fail"
    elif missing or stale or accepted_packet_count < expected_packet_count:
        status = "pending_returned_artifacts"
    return {
        "schema_version": 1,
        "report_type": "agentlab_cli_shell_coalescing_status",
        "status": status,
        "plan_path": _rel_path(root, plan_path),
        "plan_status": plan.get("status", "missing"),
        "expected_packet_count": expected_packet_count,
        "packet_count": len(packet_paths),
        "accepted_packet_count": accepted_packet_count,
        "delegated_role_count": total_role_count,
        "accepted_role_count": accepted_role_count,
        "missing_returned_files_count": len(missing),
        "missing_returned_files": missing,
        "stale_returned_files_count": len(stale),
        "stale_returned_files": stale,
        "failure_count": sum(len(item["failures"]) for item in failures),
        "failures": failures,
        "packet_statuses": packet_statuses,
        "secret_values_rendered": False,
        "provider_calls_executed": False,
        "returned_shell_sessions_provider_calls_executed": returned_shell_sessions_provider_calls_executed,
        "acceptance_scope": "synthetic_native_surface_smoke",
        "private_project_context_loaded": False,
        "acceptance_contract": {
            "one_session_receipt_per_packet_required": True,
            "one_role_receipt_per_delegated_role_required": True,
            "validation_evidence_per_delegated_role_required": True,
            "shell_state_counts_as_project_memory": False,
            "production_promotion_allowed": False,
            "synthetic_input_only": True,
            "isolated_execution_workspace_required": True,
            "project_read_tools_allowed": False,
        },
        "next_action": (
            "run trusted shell session packets and return shell receipt, role receipts, and validation evidence"
            if status == "pending_returned_artifacts"
            else ("fix coalesced shell receipt failures" if status == "fail" else "none")
        ),
    }


def write_cli_shell_coalescing_status(
    root: Path,
    out: Path,
    plan_path: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    out = out if out.is_absolute() else root / out
    report = build_cli_shell_coalescing_status(root, plan_path=plan_path)
    write_report_yaml(out, report, root)
    return report
