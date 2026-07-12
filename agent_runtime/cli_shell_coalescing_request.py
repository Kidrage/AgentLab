"""Build a trusted-runner request for coalesced CLI shell session receipts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

try:
    from agent_runtime.cli_shell_coalescing_status import build_cli_shell_coalescing_status
    from agent_runtime.report_sanitizer import write_report_yaml
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from cli_shell_coalescing_status import build_cli_shell_coalescing_status
    from report_sanitizer import write_report_yaml


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.resolve(strict=False).relative_to(root.resolve(strict=False)))
    except ValueError:
        return str(path)


def _resolve(root: Path, path_text: str) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else root / path


def _contains_secret_text(data: dict[str, Any]) -> bool:
    rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    return "sk-" in rendered or "test-key" in rendered


def _packet_request(root: Path, packet_status: dict[str, Any]) -> dict[str, Any]:
    packet_path = _resolve(root, str(packet_status.get("packet_path") or ""))
    packet = _read_yaml(packet_path)
    delegated_roles = []
    for role in packet.get("delegated_roles", []) if isinstance(packet.get("delegated_roles"), list) else []:
        if not isinstance(role, dict):
            continue
        receipt_path = packet_path.parent / str(role.get("receipt_path") or "")
        validation_path = packet_path.parent / str(role.get("validation_evidence_path") or "")
        delegated_roles.append(
            {
                "role": role.get("role"),
                "receipt_path": _rel(root, receipt_path),
                "validation_evidence_path": _rel(root, validation_path),
                "required_outputs": role.get("required_outputs") or [],
                "task": role.get("task") if isinstance(role.get("task"), dict) else {},
                "model_route": role.get("model_route") if isinstance(role.get("model_route"), dict) else {},
                "acceptance_rule": (
                    "receipt and validation evidence must both pass, match the delegated role, "
                    "and must not attempt production promotion"
                ),
            }
        )
    return {
        "packet_path": _rel(root, packet_path),
        "source_packet_sha256": packet_status.get("source_packet_sha256"),
        "backend": packet.get("backend") or packet_status.get("backend"),
        "command": packet.get("command"),
        "coalescing_mode": packet.get("coalescing_mode") or packet_status.get("coalescing_mode"),
        "task_contract": packet.get("task_contract") if isinstance(packet.get("task_contract"), dict) else {},
        "execution_contract": (
            packet.get("execution_contract") if isinstance(packet.get("execution_contract"), dict) else {}
        ),
        "provider_calls_executed_by_request_generation": False,
        "session_receipt_path": packet_status.get("session_receipt_path"),
        "session_receipt_acceptance_rule": (
            "shell-level receipt must pass and describe the native subagent or board-mediated "
            "delegation used for this bounded AgentLab shell session"
        ),
        "delegated_roles": delegated_roles,
        "current_status": packet_status.get("status"),
        "accepted": packet_status.get("accepted") is True,
        "missing": packet_status.get("missing") or [],
        "failures": packet_status.get("failures") or [],
    }


def build_cli_shell_coalescing_runner_request(
    root: Path,
    plan_path: Path | None = None,
    status_path: Path | None = None,
) -> dict[str, Any]:
    """Build a non-executing request for trusted shell runners."""
    root = root.resolve()
    plan_path = plan_path or (
        root / "acceptance_runs" / "agentlab_capability_acceptance" / "cli_shell_coalescing_plan.yml"
    )
    if not plan_path.is_absolute():
        plan_path = root / plan_path
    status_path = status_path or (
        root / "acceptance_runs" / "agentlab_capability_acceptance" / "cli_shell_coalescing_status.yml"
    )
    if not status_path.is_absolute():
        status_path = root / status_path
    status_report = build_cli_shell_coalescing_status(root, plan_path=plan_path)
    persisted_status = _read_yaml(status_path)
    if persisted_status.get("status"):
        status_report = persisted_status
    packet_requests = [
        _packet_request(root, packet_status)
        for packet_status in status_report.get("packet_statuses", [])
        if isinstance(packet_status, dict)
    ]
    packet_count = len(packet_requests)
    failure_count = int(status_report.get("failure_count") or 0)
    missing_count = int(status_report.get("missing_returned_files_count") or 0)
    stale_count = int(status_report.get("stale_returned_files_count") or 0)
    plan_ready = status_report.get("plan_status") == "pass" and packet_count > 0
    accepted = status_report.get("status") == "pass"
    ready = plan_ready and failure_count == 0 and not accepted
    canonical_request_path = "acceptance_runs/agentlab_capability_acceptance/cli_shell_coalescing_runner_request.yml"
    runner_result_path = "acceptance_runs/agentlab_capability_acceptance/cli_shell_coalescing_runner_result.yml"
    dry_run_command = (
        "./agentlab.sh cli-shell-coalescing-runner "
        f"--request {canonical_request_path} --out {runner_result_path}"
    )
    execute_command = f"AGENTLAB_TRUSTED_CLI_SHELL_RUNNER=1 {dry_run_command} --execute"
    report = {
        "schema_version": 1,
        "report_type": "agentlab_cli_shell_coalescing_runner_request",
        "status": "accepted" if accepted else ("ready_for_trusted_runner" if ready else "needs_attention"),
        "root": str(root),
        "source_plan": _rel(root, plan_path),
        "source_status": _rel(root, status_path),
        "runner_boundary": {
            "frontdesk_agent_executes_shell_sessions": False,
            "trusted_shell_runner_required": True,
            "provider_calls_executed_by_request_generation": False,
            "shell_state_counts_as_project_memory": False,
            "production_promotion_allowed": False,
            "agentlab_memory_remains_authoritative": True,
            "acceptance_scope": "synthetic_native_surface_smoke",
            "private_project_context_loaded": False,
            "isolated_execution_workspace_required": True,
            "project_read_tools_allowed": False,
        },
        "status_summary": {
            "current_status": status_report.get("status"),
            "expected_packet_count": status_report.get("expected_packet_count", 0),
            "packet_count": packet_count,
            "accepted_packet_count": status_report.get("accepted_packet_count", 0),
            "delegated_role_count": status_report.get("delegated_role_count", 0),
            "accepted_role_count": status_report.get("accepted_role_count", 0),
            "missing_returned_files_count": missing_count,
            "stale_returned_files_count": stale_count,
            "failure_count": failure_count,
        },
        "packets": packet_requests,
        "local_runner_package": {
            "request_path": canonical_request_path,
            "runner_result_path": runner_result_path,
            "status_path": _rel(root, status_path),
            "plan_path": _rel(root, plan_path),
            "dry_run_command": dry_run_command,
            "execute_command": execute_command,
            "execute_claude_only_command": f"{execute_command} --backend claude_code",
            "execute_hermes_only_command": (
                f"{execute_command} --backend hermes --provision-hermes-profiles"
            ),
            "provision_hermes_profiles_command": (
                f"{execute_command} --backend hermes --provision-hermes-profiles --provision-only"
            ),
            "status_command": (
                "./agentlab.sh cli-shell-coalescing-status "
                f"--plan {_rel(root, plan_path)} --out {_rel(root, status_path)}"
            ),
            "acceptance_refresh_command": (
                "./agentlab.sh capability-acceptance "
                "--out acceptance_runs/agentlab_capability_acceptance/current.yml"
            ),
            "post_run_collect_command": (
                "./agentlab.sh cli-shell-coalescing-collect "
                "--plan acceptance_runs/agentlab_capability_acceptance/cli_shell_coalescing_plan.yml "
                "--status acceptance_runs/agentlab_capability_acceptance/cli_shell_coalescing_status.yml "
                f"--request {canonical_request_path} "
                "--out acceptance_runs/agentlab_capability_acceptance/cli_shell_coalescing_collect.yml"
            ),
            "expected_return_files": sorted(
                set(status_report.get("missing_returned_files", []))
                | set(status_report.get("stale_returned_files", []))
            ),
            "must_return_one_shell_receipt_per_packet": True,
            "must_return_one_role_receipt_per_delegated_role": True,
            "must_return_validation_evidence_per_delegated_role": True,
            "full_run_requires_coalescing_status_pass": True,
        },
        "operator_steps": [
            {
                "step": "review_session_packets",
                "loads_private_project_context": False,
                "description": "Read each packet and confirm the backend, command, delegated roles, and receipt paths.",
            },
            {
                "step": "execute_trusted_shell_sessions",
                "loads_private_project_context": False,
                "acceptance_scope": "synthetic_native_surface_smoke",
                "description": (
                    "Run each synthetic shell session from the trusted shell runner, using the shell-native "
                    "subagent or board surface named by coalescing_mode without loading project files."
                ),
                "frontdesk_must_not_execute": True,
                "command": execute_command,
            },
            {
                "step": "return_agentlab_receipts",
                "loads_private_project_context": False,
                "description": "Write the shell-level receipt plus role receipt and validation evidence for every delegated AgentLab role.",
            },
            {
                "step": "refresh_status",
                "loads_private_project_context": False,
                "command": (
                    "./agentlab.sh cli-shell-coalescing-status "
                    f"--plan {_rel(root, plan_path)} --out {_rel(root, status_path)}"
                ),
                "pass_condition": "cli_shell_coalescing_status.status is pass",
            },
            {
                "step": "collect_acceptance",
                "loads_private_project_context": False,
                "command": (
                    "./agentlab.sh cli-shell-coalescing-collect "
                    "--out acceptance_runs/agentlab_capability_acceptance/cli_shell_coalescing_collect.yml"
                ),
                "pass_condition": "cli_shell_coalescing_collect.status is pass",
            },
        ],
        "secret_values_rendered": False,
        "next_action": (
            "run trusted shell sessions and return shell/role receipts"
            if ready
            else ("none" if accepted else "repair coalescing plan or failed returned receipts")
        ),
    }
    report["secret_values_rendered"] = _contains_secret_text(report)
    return report


def write_cli_shell_coalescing_runner_request(
    root: Path,
    out: Path,
    plan_path: Path | None = None,
    status_path: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    out = out if out.is_absolute() else root / out
    report = build_cli_shell_coalescing_runner_request(root, plan_path=plan_path, status_path=status_path)
    write_report_yaml(out, report, root)
    return report
