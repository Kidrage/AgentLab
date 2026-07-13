"""Operator handoff for trusted role-session acceptance smoke execution.

This report is intentionally non-executing. It packages the trusted-runner
request into terminal-safe instructions and records how AgentLab will verify
returned run-local candidate artifacts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

try:
    from agent_runtime.report_sanitizer import write_report_yaml
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from report_sanitizer import write_report_yaml

try:
    from audit_helpers import normalize_trusted_pending_live_smoke_item
except ModuleNotFoundError:
    from agent_runtime.audit_helpers import normalize_trusted_pending_live_smoke_item


ACCEPTANCE_SMOKE_KIND = "private_role_session_acceptance_smoke"
ACCEPTANCE_SMOKE_LABEL = "private role-session acceptance smoke"


def _acceptance_smoke_terminology(request: dict[str, Any]) -> dict[str, Any]:
    terminology = request.get("terminology")
    if isinstance(terminology, dict) and terminology.get("canonical_kind"):
        return terminology
    return {
        "canonical_kind": ACCEPTANCE_SMOKE_KIND,
        "canonical_label": ACCEPTANCE_SMOKE_LABEL,
        "legacy_terms": ["private live smoke", "private live-smoke", "live-smoke"],
        "meaning": (
            "A minimal trusted-runner acceptance run that loads private project context "
            "through the configured AgentLab role-session worker and returns run-local "
            "candidate artifacts for structural QC."
        ),
        "not_a_default_production_workflow": True,
    }


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _contains_secret_text(data: dict[str, Any]) -> bool:
    rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    return "sk-" in rendered or "test-key" in rendered


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _request_path(root: Path, request_path: Path | None) -> Path:
    path = request_path or (
        root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_request.yml"
    )
    return path if path.is_absolute() else root / path


def _status_path(root: Path, request: dict[str, Any], request_path: Path) -> Path:
    package = request.get("local_runner_package") if isinstance(request.get("local_runner_package"), dict) else {}
    status_text = package.get("status_path")
    if status_text:
        path = Path(str(status_text))
        return path if path.is_absolute() else root / path
    return request_path.with_name("trusted_live_runner_status.yml")


def _preflight_path(root: Path, request: dict[str, Any], request_path: Path) -> Path:
    package = request.get("local_runner_package") if isinstance(request.get("local_runner_package"), dict) else {}
    preflight_text = package.get("preflight_report_path")
    if preflight_text:
        path = Path(str(preflight_text))
        return path if path.is_absolute() else root / path
    return request_path.with_name("trusted_live_runner_preflight.yml")


def _collect_path(root: Path, request: dict[str, Any], request_path: Path) -> Path:
    package = request.get("local_runner_package") if isinstance(request.get("local_runner_package"), dict) else {}
    collect_text = package.get("collect_report_path")
    if collect_text:
        path = Path(str(collect_text))
        return path if path.is_absolute() else root / path
    return request_path.with_name("trusted_live_runner_collect.yml")


def _script_path(root: Path, request: dict[str, Any], request_path: Path) -> Path:
    script_text = request.get("script_path")
    if script_text:
        path = Path(str(script_text))
        return path if path.is_absolute() else root / path
    return request_path.with_suffix(".sh")


def _candidate_items(request: dict[str, Any], status: dict[str, Any]) -> list[dict[str, Any]]:
    status_by_id = {
        str(item.get("id")): item
        for item in status.get("items", [])
        if isinstance(item, dict) and item.get("id")
    }
    items: list[dict[str, Any]] = []
    for item in request.get("items", []) if isinstance(request.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "")
        expected = item.get("expected_outputs") if isinstance(item.get("expected_outputs"), dict) else {}
        current = status_by_id.get(item_id, {})
        if current:
            normalized_current = normalize_trusted_pending_live_smoke_item(current)
            current_status = normalized_current.get("status", "unknown")
            current_pending_reason = normalized_current.get("pending_reason")
            missing = normalized_current.get("missing") or []
            required_files_exist = normalized_current["required_files_exist"]
            returned_candidate_artifacts_accepted = normalized_current["returned_candidate_artifacts_accepted"]
            acceptance_blocker = normalized_current["acceptance_blocker"]
        else:
            current_status = "missing"
            current_pending_reason = "trusted_status_item_missing"
            missing = []
            required_files_exist = False
            returned_candidate_artifacts_accepted = False
            acceptance_blocker = "trusted_status_item_missing"
        items.append(
            {
                "id": item_id,
                "agentlab_execution_owner": item.get("agentlab_execution_owner"),
                "assigned_worker": item.get("assigned_worker"),
                "expected_type": expected.get("type"),
                "candidate_only": expected.get("candidate_only") is True,
                "required_files": expected.get("required_files") or [],
                "trusted_status_item_present": bool(current),
                "current_status": current_status,
                "current_pending_reason": current_pending_reason,
                "missing": missing,
                "required_files_exist": required_files_exist,
                "returned_candidate_artifacts_accepted": returned_candidate_artifacts_accepted,
                "acceptance_blocker": acceptance_blocker,
            }
        )
    return items


def build_trusted_live_runner_operator_handoff(
    root: Path,
    request_path: Path | None = None,
) -> dict[str, Any]:
    """Build a safe operator handoff without running role-session acceptance commands."""
    root = root.resolve()
    request_abs = _request_path(root, request_path)
    request = _read_yaml(request_abs)
    status_abs = _status_path(root, request, request_abs)
    preflight_abs = _preflight_path(root, request, request_abs)
    collect_abs = _collect_path(root, request, request_abs)
    script_abs = _script_path(root, request, request_abs)
    readiness_abs = root / "acceptance_runs" / "agentlab_capability_acceptance" / "internal_live_readiness.yml"
    legacy_readiness_abs = root / "acceptance_runs" / "agentlab_capability_acceptance" / "external_acceptance_readiness.yml"
    if not readiness_abs.exists():
        readiness_abs = legacy_readiness_abs
    rejection_abs = (
        root
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / "frontdesk_runtime_private_context_rejection_trusted_runner_20260708.yml"
    )
    status = _read_yaml(status_abs)
    preflight = _read_yaml(preflight_abs)
    readiness = _read_yaml(readiness_abs)
    rejection = _read_yaml(rejection_abs)

    script_rel = _rel(root, script_abs)
    status_rel = _rel(root, status_abs)
    collect_rel = _rel(root, collect_abs)
    request_rel = _rel(root, request_abs)
    local_runner_package = (
        request.get("local_runner_package")
        if isinstance(request.get("local_runner_package"), dict)
        else {}
    )
    full_run_requires_trusted_status_pass = (
        local_runner_package.get("full_run_requires_trusted_status_pass") is True
    )
    selective_run_examples = (
        local_runner_package.get("selective_run_examples")
        if isinstance(local_runner_package.get("selective_run_examples"), dict)
        else {}
    )
    selected_collect_commands = (
        local_runner_package.get("post_run_selected_collect_commands")
        if isinstance(local_runner_package.get("post_run_selected_collect_commands"), dict)
        else {}
    )
    selective_run_supported = local_runner_package.get("selective_run_supported") is True
    readiness_clean = (
        readiness.get("status") == "ready_for_internal_live_smoke"
        and readiness.get("session_health_issues") == []
    )
    session_health_issues = (
        readiness.get("session_health_issues")
        if isinstance(readiness.get("session_health_issues"), list)
        else []
    )
    session_health_issue_ids = {
        str(issue.get("id"))
        for issue in session_health_issues
        if isinstance(issue, dict) and issue.get("id")
    }
    selected_session_requirements = {
        "run_crown_internal_writer_eval": ["current_claude_writer_session_health"],
        "run_crown_internal_media_smoke": ["current_grok_session_health"],
    }

    def selected_session_health_gate(item_id: str) -> dict[str, Any]:
        required_issue_ids = selected_session_requirements.get(item_id, [])
        blocking_issue_ids = [
            issue_id for issue_id in required_issue_ids if issue_id in session_health_issue_ids
        ]
        return {
            "required_issue_ids": required_issue_ids,
            "blocking_issue_ids": blocking_issue_ids,
            "clean": not blocking_issue_ids,
            "blocked_until_relevant_session_health_clean": bool(blocking_issue_ids),
        }

    writer_session_gate = selected_session_health_gate("run_crown_internal_writer_eval")
    media_session_gate = selected_session_health_gate("run_crown_internal_media_smoke")
    selected_session_gates = {
        "run_crown_internal_writer_eval": writer_session_gate,
        "run_crown_internal_media_smoke": media_session_gate,
    }
    selected_item_readiness = {
        item_id: {
            "can_run_now": bool(selective_run_supported and gate["clean"]),
            "blocked_by_session_health": not gate["clean"],
            "required_session_health_issue_ids": gate["required_issue_ids"],
            "blocking_session_health_issue_ids": gate["blocking_issue_ids"],
        }
        for item_id, gate in selected_session_gates.items()
    }
    selected_items_ready_now = [
        item_id
        for item_id, readiness in selected_item_readiness.items()
        if readiness["can_run_now"]
    ]
    selected_items_blocked_now = [
        item_id
        for item_id, readiness in selected_item_readiness.items()
        if readiness["blocked_by_session_health"]
    ]
    trusted_runner_env = str(local_runner_package.get("trusted_runner_env_required") or "").strip()
    role_session_approval_env = str(
        local_runner_package.get("role_session_acceptance_approval_env_required") or ""
    ).strip()
    trusted_script_rel = f"{trusted_runner_env} {script_rel}".strip()
    approved_trusted_script_rel = f"{trusted_runner_env} {role_session_approval_env} {script_rel}".strip()
    command_block = {
        "preflight_only": f"{script_rel} --preflight-only",
        "session_health_only": str(
            local_runner_package.get("session_health_only_command")
            or f"{trusted_script_rel} --session-health-only"
        ),
        "full_role_session_acceptance_smoke": approved_trusted_script_rel,
        "writer_role_session_acceptance_smoke": selective_run_examples.get(
            "writer_only",
            f"{approved_trusted_script_rel} --only run_crown_internal_writer_eval",
        ),
        "media_role_session_acceptance_smoke": selective_run_examples.get(
            "media_only",
            f"{approved_trusted_script_rel} --only run_crown_internal_media_smoke",
        ),
        "refresh_status": (
            f"./agentlab.sh trusted-live-runner-status --request {request_rel} --out {status_rel}"
        ),
        "collect_and_refresh_acceptance": (
            f"./agentlab.sh trusted-live-runner-collect --request {request_rel} --out {collect_rel}"
        ),
        "collect_writer_selected": selected_collect_commands.get(
            "writer_only",
            (
                f"./agentlab.sh trusted-live-runner-collect --request {request_rel} "
                f"--out {_rel(root, collect_abs.with_name('trusted_live_runner_collect_writer.yml'))} "
                "--item run_crown_internal_writer_eval"
            ),
        ),
        "collect_media_selected": selected_collect_commands.get(
            "media_only",
            (
                f"./agentlab.sh trusted-live-runner-collect --request {request_rel} "
                f"--out {_rel(root, collect_abs.with_name('trusted_live_runner_collect_media.yml'))} "
                "--item run_crown_internal_media_smoke"
            ),
        ),
    }
    candidate_items = _candidate_items(request, status)
    writer_request_item = next(
        (
            item
            for item in request.get("items", [])
            if isinstance(item, dict) and item.get("id") == "run_crown_internal_writer_eval"
        ),
        {},
    )
    writer_request_route_current = (
        writer_request_item.get("assigned_worker") == "claude_code"
        and "--writer-worker claude_code"
        in str(writer_request_item.get("command") or "")
        and "--writer-worker agy" not in str(writer_request_item.get("command") or "")
    )
    issues: list[str] = []
    if request.get("status") != "ready_for_trusted_runner":
        issues.append("trusted_live_runner_request_not_ready")
    if preflight.get("status") != "pass":
        issues.append("trusted_live_runner_preflight_not_pass")
    if not readiness_clean:
        issues.append("internal_live_readiness_not_clean")
    if not script_abs.exists():
        issues.append("trusted_live_runner_script_missing")
    if not writer_request_route_current:
        issues.append("trusted_live_runner_writer_route_stale")

    report = {
        "schema_version": 1,
        "report_type": "agentlab_trusted_live_runner_operator_handoff",
        "root": str(root),
        "status": "ready_for_trusted_runner" if not issues else "needs_attention",
        "source_reports": {
            "trusted_live_runner_request": request_rel,
            "trusted_live_runner_preflight": _rel(root, preflight_abs),
            "trusted_live_runner_status": status_rel,
            "trusted_live_runner_collect": collect_rel,
            "trusted_live_runner_collect_writer": _rel(
                root,
                collect_abs.with_name("trusted_live_runner_collect_writer.yml"),
            ),
            "trusted_live_runner_collect_media": _rel(
                root,
                collect_abs.with_name("trusted_live_runner_collect_media.yml"),
            ),
            "internal_live_readiness": _rel(root, readiness_abs),
            "external_acceptance_readiness": _rel(root, legacy_readiness_abs),
            "codex_frontdesk_private_context_rejection": _rel(root, rejection_abs)
            if rejection_abs.exists()
            else None,
        },
        "terminology": _acceptance_smoke_terminology(request),
        "execution_boundary": {
            "codex_frontdesk_executes_private_live_commands": False,
            "codex_frontdesk_executes_role_session_acceptance_commands": False,
            "trusted_agentlab_runner_required": True,
            "user_terminal_fallback_allowed": True,
            "trusted_runner_or_user_terminal_required": True,
            "non_private_session_health_clean": readiness_clean,
            "codex_frontdesk_private_context_rejected": bool(rejection),
            "agentlab_internal_route_blocked": False,
            "full_run_requires_trusted_status_pass": full_run_requires_trusted_status_pass,
            "approval_gate_before_private_context": (
                local_runner_package.get("approval_gate_before_private_context") is True
            ),
            "exact_outbound_context_manifest_required": (
                local_runner_package.get("exact_outbound_context_manifest_required") is True
            ),
            "writer_sealed_context_required": (
                local_runner_package.get("writer_sealed_context_required") is True
            ),
            "media_prompt_digest_required": (
                local_runner_package.get("media_prompt_digest_required") is True
            ),
            "secret_pattern_gate_before_provider_call": (
                local_runner_package.get("secret_pattern_gate_before_provider_call") is True
            ),
            "role_session_acceptance_approval_env_required": role_session_approval_env,
            "selective_run_supported": selective_run_supported,
            "selective_run_requires_selected_item_pass": (
                local_runner_package.get("selective_run_requires_selected_item_pass") is True
            ),
            "selected_session_health_gates": selected_session_gates,
            "writer_request_route_current": writer_request_route_current,
        },
        "selected_item_readiness": {
            "summary": (
                "top-level handoff status covers the full writer+media acceptance set; "
                "selected items may still be runnable when their own session gate is clean"
            ),
            "ready_item_ids": selected_items_ready_now,
            "blocked_item_ids": selected_items_blocked_now,
            "items": selected_item_readiness,
        },
        "operator_steps": [
            {
                "step": "preflight",
                "loads_private_project_context": False,
                "command": command_block["preflight_only"],
            },
            {
                "step": "session_health",
                "loads_private_project_context": False,
                "command": command_block["session_health_only"],
                "pass_condition": "internal_live_readiness.session_health_issues is empty",
            },
            {
                "step": "role_session_acceptance_smoke",
                "loads_private_project_context": True,
                "command": command_block["full_role_session_acceptance_smoke"],
                "must_run_from": "trusted AgentLab runner or user-operated terminal/session",
                "approval_env_required": role_session_approval_env,
                "runtime_outbound_context_manifest_required": True,
                "blocked_until_session_health_clean": not readiness_clean,
                "required_session_health_issue_ids": [
                    "current_claude_writer_session_health",
                    "current_grok_session_health",
                ],
                "blocking_session_health_issue_ids": sorted(session_health_issue_ids),
                "runs_all_items": True,
            },
            {
                "step": "writer_role_session_acceptance_smoke",
                "loads_private_project_context": True,
                "command": command_block["writer_role_session_acceptance_smoke"],
                "must_run_from": "trusted AgentLab runner or user-operated terminal/session",
                "approval_env_required": role_session_approval_env,
                "runtime_outbound_context_manifest_required": True,
                "sealed_writer_context_required": True,
                "blocked_until_session_health_clean": (
                    writer_session_gate["blocked_until_relevant_session_health_clean"]
                ),
                "blocked_until_relevant_session_health_clean": (
                    writer_session_gate["blocked_until_relevant_session_health_clean"]
                ),
                "relevant_session_health_issue_ids": writer_session_gate["required_issue_ids"],
                "blocking_session_health_issue_ids": writer_session_gate["blocking_issue_ids"],
                "runs_only": "run_crown_internal_writer_eval",
                "recommended_before_media_for_incremental_acceptance": True,
                "selective_run_supported": selective_run_supported,
            },
            {
                "step": "writer_selected_collect",
                "loads_private_project_context": False,
                "command": command_block["collect_writer_selected"],
                "runs_only": "run_crown_internal_writer_eval",
                "pass_condition": "selected_item_collect_status is pass",
            },
            {
                "step": "media_role_session_acceptance_smoke",
                "loads_private_project_context": True,
                "command": command_block["media_role_session_acceptance_smoke"],
                "must_run_from": "trusted AgentLab runner or user-operated terminal/session",
                "approval_env_required": role_session_approval_env,
                "runtime_outbound_context_manifest_required": True,
                "exact_media_prompt_digest_required": True,
                "blocked_until_session_health_clean": (
                    media_session_gate["blocked_until_relevant_session_health_clean"]
                ),
                "blocked_until_relevant_session_health_clean": (
                    media_session_gate["blocked_until_relevant_session_health_clean"]
                ),
                "relevant_session_health_issue_ids": media_session_gate["required_issue_ids"],
                "blocking_session_health_issue_ids": media_session_gate["blocking_issue_ids"],
                "runs_only": "run_crown_internal_media_smoke",
                "recommended_after_writer_or_after_grok_session_health_is_clean": True,
                "selective_run_supported": selective_run_supported,
            },
            {
                "step": "media_selected_collect",
                "loads_private_project_context": False,
                "command": command_block["collect_media_selected"],
                "runs_only": "run_crown_internal_media_smoke",
                "pass_condition": "selected_item_collect_status is pass",
            },
            {
                "step": "refresh_status",
                "loads_private_project_context": False,
                "command": command_block["refresh_status"],
            },
            {
                "step": "refresh_acceptance_reports",
                "loads_private_project_context": False,
                "command": command_block["collect_and_refresh_acceptance"],
                "refreshes": [
                    "trusted_live_runner_status",
                    "trusted_live_runner_operator_handoff",
                    "live_unblock_plan",
                    "capability_acceptance",
                    "objective_requirement_audit",
                    "goal_completion_audit",
                    "acceptance_report_hygiene",
                ],
            },
        ],
        "candidate_items": candidate_items,
        "session_health": {
            "status": readiness.get("status", "missing"),
            "clean": readiness_clean,
            "issue_count": len(session_health_issues),
            "issues": session_health_issues,
            "next_action": (
                "rerun_session_health_from_trusted_runtime_before_role_session_acceptance_smoke"
                if session_health_issues
                else "run_role_session_acceptance_smoke"
            ),
        },
        "current_return_status": {
            "status": status.get("status", "missing"),
            "missing_item_count": len(status.get("missing_items", []) if isinstance(status.get("missing_items"), list) else []),
            "stale_item_count": len(status.get("stale_items", []) if isinstance(status.get("stale_items"), list) else []),
            "artifact_qc_failure_count": len(
                status.get("artifact_qc_failures", [])
                if isinstance(status.get("artifact_qc_failures"), list)
                else []
            ),
            "full_run_requires_trusted_status_pass": full_run_requires_trusted_status_pass,
            "selective_run_supported": selective_run_supported,
            "selective_run_requires_selected_item_pass": (
                local_runner_package.get("selective_run_requires_selected_item_pass") is True
            ),
        },
        "acceptance_rule": (
            "AgentLab accepts returned role-session acceptance smoke evidence only when trusted-live-runner-status "
            "passes local structural QC; the generated full-run script exits nonzero unless that status is pass; "
            "Writer/media provider calls must first produce a passing exact outbound-context manifest; "
            "selective --only runs exit nonzero unless the selected item status is pass; "
            "generated outputs remain run-local candidates until explicit promotion."
        ),
        "secret_values_rendered": False,
        "issues": issues,
        "notes": [
            "This handoff does not execute private role-session acceptance commands.",
            "It is safe for Codex/frontdesk to generate and inspect this report.",
            "The full role-session acceptance smoke command must run from a trusted AgentLab runner; a user-operated terminal is only a fallback execution surface.",
        ],
    }
    report["secret_values_rendered"] = _contains_secret_text(report)
    if report["secret_values_rendered"]:
        report["status"] = "needs_attention"
        report["issues"] = [*issues, "secret_values_rendered"]
    return report


def write_trusted_live_runner_operator_handoff(
    root: Path,
    out: Path,
    request_path: Path | None = None,
) -> dict[str, Any]:
    report = build_trusted_live_runner_operator_handoff(root, request_path=request_path)
    write_report_yaml(out, report, root)
    return report
