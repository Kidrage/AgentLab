"""Shared helpers for acceptance audit reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any


CAPABILITY_ID_ALIASES = {
    "internal_live_unblock_plan": ["live_external_unblock_plan"],
    "internal_live_readiness": ["external_acceptance_readiness"],
}


def capabilities_by_id(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for item in report.get("capabilities", []):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        item_id = str(item.get("id"))
        indexed[item_id] = item
        for legacy_id in item.get("legacy_ids", []) or []:
            indexed.setdefault(str(legacy_id), item)
    for canonical_id, legacy_ids in CAPABILITY_ID_ALIASES.items():
        for legacy_id in legacy_ids:
            if canonical_id not in indexed and legacy_id in indexed:
                indexed[canonical_id] = indexed[legacy_id]
            if legacy_id not in indexed and canonical_id in indexed:
                indexed[legacy_id] = indexed[canonical_id]
    return indexed


def capability_status(capabilities: dict[str, dict[str, Any]], capability_id: str) -> str:
    return str(capabilities.get(capability_id, {}).get("status", "missing"))


def trusted_writer_request_route_current(report: dict[str, Any]) -> bool:
    """Return whether a persisted trusted-runner request uses the current Writer route."""
    items = report.get("items") if isinstance(report.get("items"), list) else []
    writer = next(
        (
            item
            for item in items
            if isinstance(item, dict)
            and item.get("id") == "run_crown_internal_writer_eval"
        ),
        {},
    )
    package = (
        report.get("local_runner_package")
        if isinstance(report.get("local_runner_package"), dict)
        else {}
    )
    preflight_commands = package.get("preflight_commands")
    if not isinstance(preflight_commands, list):
        preflight_commands = []
    command = str(writer.get("command") or "")
    return (
        writer.get("assigned_worker") == "agy"
        and "--writer-worker agy" in command
        and "command -v agy" in preflight_commands
    )


def evidence_health(evidence: list[str]) -> dict[str, Any]:
    paths = [path for path in evidence if path]
    missing = [path for path in paths if not Path(path).exists()]
    return {
        "status": "pass" if not missing else "missing_evidence",
        "checked": len(paths),
        "missing": missing,
    }


def session_health_summary(readiness: dict[str, Any]) -> dict[str, Any]:
    issues = readiness.get("session_health_issues", [])
    if not isinstance(issues, list):
        issues = []
    compact_issues: list[dict[str, Any]] = []
    optional_keys = (
        "cli_entrypoint_available",
        "tested_invocation_mode",
        "interactive_cli_start_is_not_task_contract_proof",
        "block_scope",
        "next_action",
        "diagnostics_summary",
    )
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        compact = {
            "id": issue.get("id"),
            "status": issue.get("status"),
            "reason": issue.get("reason"),
            "command_available": issue.get("command_available"),
            "command_path": issue.get("command_path"),
        }
        for key in optional_keys:
            if key in issue:
                compact[key] = issue.get(key)
        compact_issues.append(compact)
    return {
        "status": readiness.get("status", "missing"),
        "issue_count": len(issues),
        "issues": compact_issues,
    }


def acceptance_report_hygiene_summary(report: dict[str, Any]) -> dict[str, Any]:
    """Compact the report-hygiene gate for higher-level acceptance audits."""
    canonical_text_issues = (
        report.get("canonical_text_issues")
        if isinstance(report.get("canonical_text_issues"), list)
        else []
    )
    stale_marker_hits = (
        report.get("stale_marker_hits")
        if isinstance(report.get("stale_marker_hits"), list)
        else []
    )
    stale_private_selected_command_hits = (
        report.get("stale_private_selected_command_hits")
        if isinstance(report.get("stale_private_selected_command_hits"), list)
        else []
    )
    return {
        "status": report.get("status", "missing"),
        "canonical_text_artifact_count": report.get("canonical_text_artifact_count", 0),
        "canonical_text_issue_count": len(canonical_text_issues),
        "stale_snapshot_count": report.get("stale_snapshot_count", 0),
        "stale_marker_hit_count": len(stale_marker_hits),
        "stale_private_selected_command_hit_count": len(stale_private_selected_command_hits),
        "private_selected_command_policy": report.get("private_selected_command_policy"),
    }


def capability_candidate_issues(capabilities: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Return machine-readable issues for capabilities that are still candidates."""
    issues: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for capability_id, capability in sorted(capabilities.items()):
        if str(capability.get("status")) != "candidate":
            continue
        issue_id = str(capability.get("id") or capability_id)
        if issue_id in seen_ids:
            continue
        seen_ids.add(issue_id)
        details = capability.get("details") if isinstance(capability.get("details"), dict) else {}
        item: dict[str, Any] = {
            "id": issue_id,
            "summary": capability.get("summary"),
            "issues": capability.get("issues", []) if isinstance(capability.get("issues"), list) else [],
        }
        acceptance_blockers = details.get("acceptance_blockers")
        if isinstance(acceptance_blockers, list):
            item["acceptance_blockers"] = acceptance_blockers
        acceptance_blocker_reasons = details.get("acceptance_blocker_reasons")
        if isinstance(acceptance_blocker_reasons, list):
            item["acceptance_blocker_reasons"] = acceptance_blocker_reasons
        if details.get("trusted_runner_item"):
            item["trusted_runner_item"] = details.get("trusted_runner_item")
        issues.append(item)
    return issues


def candidate_issues_for(candidate_issues: list[dict[str, Any]], capability_ids: list[str]) -> list[dict[str, Any]]:
    """Filter candidate issue summaries to a specific requirement or goal item."""
    allowed = set(capability_ids)
    return [item for item in candidate_issues if item.get("id") in allowed]


def media_generation_readiness(capabilities: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Evaluate media execution readiness without claiming generated-asset acceptance."""
    backend = capabilities.get("grok_xai_media_backend", {})
    details = backend.get("details") if isinstance(backend.get("details"), dict) else {}
    checks = {
        "media_series_scaffold": capability_status(capabilities, "media_series_scaffold") == "pass",
        "backend_registered": details.get("backend_id") == "hermes_grok_oauth",
        "artifact_producer_worker_binding": details.get("artifact_producer_grok_binding") is True,
        "invocation_contract": details.get("grok_invocation_contract_ready") is True,
        "internal_cli_entrypoint": details.get("local_cli_entrypoint_available") is True
        and details.get("local_cli_entrypoint_is_internal_worker") is True,
        "oauth_session_smoke": details.get("session_smoke_status") == "pass"
        and details.get("session_auth_healthy") is True,
        "non_interactive_prompt_contract": details.get("non_interactive_prompt_contract_status") == "pass",
        "asset_return_contract": details.get("local_cli_asset_return_contract_ready") is True,
        "candidate_only_boundary": details.get("media_acceptance_requires_generated_assets") is True
        and details.get("media_acceptance_requires_artifact_generation_verified") is True,
    }
    return {
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "backend_capability_status": backend.get("status", "missing"),
        "generated_asset_acceptance_claimed": False,
    }


def trusted_live_acceptance_blocker(
    *,
    missing: list[Any],
    observed_error: Any,
    artifact_qc: dict[str, Any] | None,
    status: str,
) -> str:
    """Return the canonical trusted-live returned-artifact blocker."""
    if missing:
        return "missing_required_files"
    if observed_error:
        return "observed_execution_error_or_stale_ledger"
    if artifact_qc and artifact_qc.get("status") == "fail":
        return "artifact_qc_failed"
    if status == "pass":
        return "none"
    return "pending_without_structured_blocker"


def normalize_trusted_pending_live_smoke_item(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize common pending live-smoke fields shared by audit reports."""
    missing = item.get("missing") or []
    required_files_exist = item.get("required_files_exist")
    if not isinstance(required_files_exist, bool):
        required_files_exist = not bool(missing)

    returned_candidate_artifacts_accepted = item.get("returned_candidate_artifacts_accepted")
    if not isinstance(returned_candidate_artifacts_accepted, bool):
        returned_candidate_artifacts_accepted = item.get("status") == "pass"

    observed_error = item.get("observed_error")
    artifact_qc = item.get("artifact_qc") if isinstance(item.get("artifact_qc"), dict) else None
    acceptance_blocker = item.get("acceptance_blocker")
    if not acceptance_blocker:
        acceptance_blocker = trusted_live_acceptance_blocker(
            missing=missing,
            observed_error=observed_error,
            artifact_qc=artifact_qc,
            status=str(item.get("status") or ""),
        )

    pending_item = {
        "id": item.get("id"),
        "expected_type": item.get("expected_type"),
        "status": item.get("status"),
        "pending_reason": item.get("pending_reason"),
        "evidence_interpretation": item.get("evidence_interpretation"),
        "next_action": item.get("next_action"),
        "agentlab_command": item.get("command"),
        "required_files": item.get("required_files") or [],
        "missing": missing,
        "required_files_exist": required_files_exist,
        "returned_candidate_artifacts_accepted": returned_candidate_artifacts_accepted,
        "acceptance_blocker": acceptance_blocker,
    }
    if observed_error:
        pending_item["observed_error"] = observed_error
    if item.get("cli_contract_health"):
        pending_item["cli_contract_health"] = item.get("cli_contract_health")
    if item.get("session_health_gate"):
        pending_item["session_health_gate"] = item.get("session_health_gate")
    return pending_item


def selected_collect_metadata_by_item(collect_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return selected collect report pointers keyed by trusted live item id."""
    paths = (
        collect_report.get("selected_item_report_paths")
        if isinstance(collect_report.get("selected_item_report_paths"), dict)
        else {}
    )
    summaries = (
        collect_report.get("selected_item_summaries")
        if isinstance(collect_report.get("selected_item_summaries"), dict)
        else {}
    )
    summaries = dict(summaries)
    top_level_item_id = collect_report.get("selected_item_id")
    if top_level_item_id and str(top_level_item_id) not in summaries:
        summaries[str(top_level_item_id)] = {
            key: collect_report[key]
            for key in (
                "selected_item_collect_status",
                "selected_item_status",
                "selected_item_accepted",
                "selected_item_acceptance_blocker",
                "selected_item_pending_reason",
                "selected_item_next_action",
            )
            if key in collect_report
        }
    item_ids = sorted({str(item_id) for item_id in [*paths.keys(), *summaries.keys()] if item_id})
    metadata: dict[str, dict[str, Any]] = {}
    for item_id in item_ids:
        summary = summaries.get(item_id) if isinstance(summaries.get(item_id), dict) else {}
        item_metadata: dict[str, Any] = {}
        if paths.get(item_id):
            item_metadata["selected_collect_report_path"] = paths[item_id]
        for source_key, target_key in (
            ("selected_item_collect_status", "selected_item_collect_status"),
            ("selected_item_status", "selected_item_status"),
            ("selected_item_accepted", "selected_item_accepted"),
            ("selected_item_acceptance_blocker", "selected_item_acceptance_blocker"),
            ("selected_item_pending_reason", "selected_item_pending_reason"),
            ("selected_item_next_action", "selected_item_next_action"),
        ):
            if source_key in summary:
                item_metadata[target_key] = summary[source_key]
        if item_metadata:
            metadata[item_id] = item_metadata
    return metadata


def trusted_collect_strict_pass(
    trusted_status: dict[str, Any],
    trusted_collect: dict[str, Any],
) -> bool:
    """Return true only when returned-artifact acceptance is complete end to end."""
    status_items = trusted_status.get("items", []) if isinstance(trusted_status.get("items"), list) else []
    item_by_id = {
        str(item.get("id")): item
        for item in status_items
        if isinstance(item, dict) and item.get("id")
    }
    required_item_ids = {
        "run_crown_internal_writer_eval",
        "run_crown_internal_media_smoke",
    }
    required_items_accepted = all(
        item_by_id.get(item_id, {}).get("status") == "pass"
        and item_by_id.get(item_id, {}).get("returned_candidate_artifacts_accepted") is True
        for item_id in required_item_ids
    )
    pending_items = (
        trusted_collect.get("pending_items")
        if isinstance(trusted_collect.get("pending_items"), list)
        else []
    )
    acceptance_blockers = (
        trusted_collect.get("acceptance_blockers")
        if isinstance(trusted_collect.get("acceptance_blockers"), list)
        else []
    )
    returned_accepted_count = trusted_collect.get("returned_candidate_artifacts_accepted_count")
    if not isinstance(returned_accepted_count, int):
        returned_accepted_count = 0
    return (
        trusted_status.get("status") == "pass"
        and trusted_collect.get("status") == "pass"
        and required_items_accepted
        and len(status_items) >= len(required_item_ids)
        and returned_accepted_count >= len(required_item_ids)
        and not pending_items
        and not acceptance_blockers
        and trusted_collect.get("secret_values_rendered") is False
    )


def active_acceptance_blockers(
    *,
    session_health: dict[str, Any],
    pending_internal_live_smokes: list[dict[str, Any]],
    frontdesk_runtime_boundary: dict[str, Any] | None = None,
    required_scopes: set[str] | None = None,
) -> dict[str, Any]:
    """Summarize current blockers without mixing in historical evidence."""
    required_scopes = required_scopes or {"writer", "media"}
    session_issues = (
        session_health.get("issues")
        if isinstance(session_health.get("issues"), list)
        else []
    )
    session_issue_by_id = {
        str(issue.get("id")): issue
        for issue in session_issues
        if isinstance(issue, dict) and issue.get("id")
    }
    pending_by_id = {
        str(item.get("id")): item
        for item in pending_internal_live_smokes
        if isinstance(item, dict) and item.get("id")
    }
    current_blockers: list[dict[str, Any]] = []

    writer = pending_by_id.get("run_crown_internal_writer_eval") if "writer" in required_scopes else None
    if writer and writer.get("returned_candidate_artifacts_accepted") is not True:
        current_blockers.append(
            {
                "id": "writer_missing_returned_artifacts",
                "scope": "writer",
                "item_id": "run_crown_internal_writer_eval",
                "reason": writer.get("pending_reason") or writer.get("acceptance_blocker"),
                "acceptance_blocker": writer.get("acceptance_blocker"),
                "next_action": writer.get("next_action"),
                "required_files_exist": writer.get("required_files_exist"),
            }
        )

    grok_issue = session_issue_by_id.get("current_grok_session_health") if "media" in required_scopes else None
    if grok_issue:
        current_blockers.append(
            {
                "id": "media_grok_session_health",
                "scope": "media",
                "issue_id": "current_grok_session_health",
                "reason": grok_issue.get("reason"),
                "next_action": grok_issue.get("next_action"),
                "tested_invocation_mode": grok_issue.get("tested_invocation_mode"),
            }
        )

    media = pending_by_id.get("run_crown_internal_media_smoke") if "media" in required_scopes else None
    if media and media.get("returned_candidate_artifacts_accepted") is not True:
        current_blockers.append(
            {
                "id": "media_returned_artifacts_not_accepted",
                "scope": "media",
                "item_id": "run_crown_internal_media_smoke",
                "reason": media.get("pending_reason") or media.get("acceptance_blocker"),
                "acceptance_blocker": media.get("acceptance_blocker"),
                "next_action": media.get("next_action"),
                "required_files_exist": media.get("required_files_exist"),
            }
        )

    boundary = frontdesk_runtime_boundary or {}
    not_current_blockers = [
        {
            "id": "writer_claude_session_health",
            "active": "current_agy_writer_session_health" in session_issue_by_id,
            "status": (
                "blocking"
                if "current_agy_writer_session_health" in session_issue_by_id
                else "not_blocking"
            ),
        },
        {
            "id": "agentlab_internal_route_or_role_binding",
            "active": bool(boundary.get("agentlab_internal_route_blocked"))
            or bool(boundary.get("role_worker_binding_blocked")),
            "status": (
                "blocking"
                if boundary.get("agentlab_internal_route_blocked")
                or boundary.get("role_worker_binding_blocked")
                else "not_blocking"
            ),
        },
        {
            "id": "api_key_or_provider_registration",
            "active": bool(boundary.get("missing_api_key_blocked")),
            "status": "blocking" if boundary.get("missing_api_key_blocked") else "not_blocking",
        },
        {
            "id": "codex_frontdesk_runtime_policy",
            "active": False,
            "status": "historical_external_worker_attempt"
            if boundary.get("codex_frontdesk_runtime_blocked_for_private_live_execution")
            else "not_blocking",
        },
    ]
    return {
        "status": "pending" if current_blockers else "clear",
        "current_blocker_count": len(current_blockers),
        "current_blockers": current_blockers,
        "not_current_blockers": not_current_blockers,
        "selected_item_gate_summary": {
            "writer_selected_in_scope": "writer" in required_scopes,
            "media_selected_in_scope": "media" in required_scopes,
            "writer_selected_can_run": (
                "current_agy_writer_session_health" not in session_issue_by_id
            ),
            "media_selected_can_run": "current_grok_session_health" not in session_issue_by_id,
        },
    }


def role_session_execution_boundary(
    trusted_request: dict[str, Any],
    operator_handoff: dict[str, Any],
) -> dict[str, Any]:
    """Summarize the gates before private role-session acceptance can run."""
    runner_package = (
        trusted_request.get("local_runner_package")
        if isinstance(trusted_request.get("local_runner_package"), dict)
        else {}
    )
    selective_examples = (
        runner_package.get("selective_run_examples")
        if isinstance(runner_package.get("selective_run_examples"), dict)
        else {}
    )
    entrypoint = str(runner_package.get("entrypoint") or "")
    execution_boundary = (
        operator_handoff.get("execution_boundary")
        if isinstance(operator_handoff.get("execution_boundary"), dict)
        else {}
    )
    steps = (
        operator_handoff.get("operator_steps")
        if isinstance(operator_handoff.get("operator_steps"), list)
        else []
    )
    step_by_id = {
        str(step.get("step")): step
        for step in steps
        if isinstance(step, dict) and step.get("step")
    }
    approval_env = str(
        runner_package.get("role_session_acceptance_approval_env_required")
        or execution_boundary.get("role_session_acceptance_approval_env_required")
        or ""
    )
    trusted_env = str(runner_package.get("trusted_runner_env_required") or "")
    session_health_command = str(
        runner_package.get("session_health_only_command")
        or step_by_id.get("session_health", {}).get("command")
        or ""
    )
    full_command = str(step_by_id.get("role_session_acceptance_smoke", {}).get("command") or "")
    if not full_command and trusted_env and approval_env and entrypoint:
        full_command = f"{trusted_env} {approval_env} {entrypoint}"
    writer_command = str(
        selective_examples.get("writer_only")
        or step_by_id.get("writer_role_session_acceptance_smoke", {}).get("command")
        or ""
    )
    media_command = str(
        selective_examples.get("media_only")
        or step_by_id.get("media_role_session_acceptance_smoke", {}).get("command")
        or ""
    )
    private_commands = [command for command in [full_command, writer_command, media_command] if command]
    return {
        "trusted_runner_env_required": trusted_env,
        "role_session_acceptance_approval_env_required": approval_env,
        "session_health_only_command": session_health_command,
        "full_role_session_acceptance_command": full_command,
        "writer_role_session_acceptance_command": writer_command,
        "media_role_session_acceptance_command": media_command,
        "session_health_requires_approval_env": bool(approval_env and approval_env in session_health_command),
        "approval_gate_before_private_context": (
            runner_package.get("approval_gate_before_private_context") is True
            or execution_boundary.get("approval_gate_before_private_context") is True
        ),
        "private_context_commands_require_approval_env": bool(
            approval_env
            and private_commands
            and all(approval_env in command for command in private_commands)
        ),
        "frontdesk_executes_role_session_acceptance_commands": bool(
            execution_boundary.get("codex_frontdesk_executes_role_session_acceptance_commands", False)
        ),
        "full_run_requires_trusted_status_pass": runner_package.get("full_run_requires_trusted_status_pass") is True
        or execution_boundary.get("full_run_requires_trusted_status_pass") is True,
    }
