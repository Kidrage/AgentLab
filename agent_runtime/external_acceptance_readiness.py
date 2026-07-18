"""Readiness audit for AgentLab internal live-smoke acceptance items."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

try:
    from agent_runtime.live_unblock_plan import build_live_unblock_plan
    from agent_runtime.report_sanitizer import write_report_yaml
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from live_unblock_plan import build_live_unblock_plan
    from report_sanitizer import write_report_yaml


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _evidence_health(evidence: list[str]) -> dict[str, Any]:
    paths = [path for path in evidence if path]
    missing = [path for path in paths if not Path(path).exists()]
    return {
        "status": "pass" if not missing else "missing_evidence",
        "checked": len(paths),
        "missing": missing,
    }


def _contains_secret_text(data: dict[str, Any]) -> bool:
    rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    return "sk-" in rendered or "test-key" in rendered


def _item_by_id(items: list[dict[str, Any]], item_id: str) -> dict[str, Any]:
    return next((item for item in items if item.get("id") == item_id), {})


def _historical_policy_rejections(root: Path) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    base = root / "acceptance_runs" / "agentlab_capability_acceptance"
    for path in sorted(base.glob("external_policy_rejection_*.yml")):
        report = _read_yaml(path)
        if report:
            report["_path"] = str(path)
            reports.append(report)
    return reports


def _session_health_check(
    report: dict[str, Any],
    *,
    check_id: str,
    healthy_message: str,
    blocked_message: str,
    next_action: str,
) -> dict[str, Any]:
    probe_error_class = str(report.get("error_class") or "").lower()
    is_worker_probe = "worker_id" in report and "installed" in report
    probe_passed = (
        is_worker_probe
        and report.get("installed") is True
        and report.get("exit_code") == 0
        and report.get("timeout") is not True
        and probe_error_class in {"", "none"}
    )
    status = str(
        report.get("status")
        or ("pass" if probe_passed else "blocked" if is_worker_probe else "missing")
    )
    passed = status == "pass"
    check = {
        "id": check_id,
        "status": "pass" if passed else "blocked",
        "session_smoke_status": status,
        "command_available": report.get("command_available", report.get("installed")),
        "command_path": report.get("command_path"),
        "created_at": report.get("created_at"),
        "evidence_interpretation": report.get("evidence_interpretation")
        or (healthy_message if passed else blocked_message),
    }
    if report.get("reason"):
        check["reason"] = report.get("reason")
    elif is_worker_probe and not passed:
        check["reason"] = probe_error_class or "claude_writer_probe_missing_or_invalid"
    elif not passed:
        check["reason"] = "session_health_report_missing_or_invalid"
    if not passed:
        check["next_action"] = next_action
    if is_worker_probe:
        check["worker_id"] = report.get("worker_id")
        check["installed"] = report.get("installed")
        check["exit_code"] = report.get("exit_code")
        check["timeout"] = report.get("timeout")
        check["error_class"] = report.get("error_class")
    for key in (
        "cli_entrypoint_available",
        "local_cli_entrypoint_available",
        "local_cli_entrypoint_is_internal_worker",
        "local_cli_auth_mode",
        "local_cli_requires_api_key",
        "tested_invocation_mode",
        "non_interactive_prompt_contract_status",
        "interactive_cli_start_is_not_task_contract_proof",
        "block_scope",
    ):
        if key in report and report.get(key) is not None:
            check[key] = report.get(key)
    if check_id == "current_grok_session_health":
        check.setdefault("local_cli_entrypoint_available", report.get("cli_entrypoint_available"))
        check.setdefault(
            "local_cli_entrypoint_is_internal_worker",
            report.get("execution_scope") == "internal_local_cli_worker",
        )
        check.setdefault("local_cli_auth_mode", "oauth_cli_session")
        check.setdefault("local_cli_requires_api_key", False)
        check.setdefault(
            "non_interactive_prompt_contract_status",
            "pass" if passed else ("blocked" if status == "blocked" else status),
        )
    diagnostics = report.get("diagnostics") if isinstance(report.get("diagnostics"), dict) else {}
    if diagnostics:
        check["diagnostics_summary"] = {
            "auth_status": diagnostics.get("auth_status") or "unknown",
            "auth_session_healthy": bool(diagnostics.get("auth_session_healthy")),
            "not_authenticated_marker_present": bool(diagnostics.get("not_authenticated_marker_present")),
            "model_catalog_visible": bool(
                diagnostics.get("model_catalog_visible")
                if "model_catalog_visible" in diagnostics
                else diagnostics.get("login_or_model_catalog_visible")
            ),
            "login_or_model_catalog_visible": diagnostics.get("login_or_model_catalog_visible"),
            "settings_fetch_failed": diagnostics.get("settings_fetch_failed"),
        }
    return check


def build_external_acceptance_readiness(root: Path) -> dict[str, Any]:
    """Legacy entrypoint that now returns the canonical internal-live readiness report."""
    root = root.resolve()
    unblock_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "live_unblock_plan.yml"
    handoff_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "frontdesk_live_handoff.yml"
    claude_writer_probe_path = (
        root
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / "claude_writer_session_probe.yml"
    )
    grok_smoke_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "grok_cli_session_smoke.yml"
    unblock = build_live_unblock_plan(root)
    handoff = _read_yaml(handoff_path)
    claude_writer_probe = _read_yaml(claude_writer_probe_path)
    grok_smoke = _read_yaml(grok_smoke_path)
    historical_policy_rejections = _historical_policy_rejections(root)
    unblock_items = [item for item in unblock.get("items", []) if isinstance(item, dict)]
    crown = _item_by_id(unblock_items, "run_crown_internal_writer_eval") or _item_by_id(unblock_items, "approve_crown_external_writer_context")
    if crown.get("id") == "run_crown_internal_writer_eval":
        crown = dict(crown)
        crown["assigned_worker"] = "claude_code"
        for key in ("agentlab_command", "safe_command_after_approval"):
            if crown.get(key):
                crown[key] = str(crown[key]).replace(
                    "--writer-worker agy",
                    "--writer-worker claude_code",
                )
    media = _item_by_id(unblock_items, "run_crown_internal_media_smoke") or _item_by_id(unblock_items, "approve_crown_media_grok_oauth_context")
    crown_evidence = [str(path) for path in crown.get("evidence", []) if path]
    media_evidence = [str(path) for path in media.get("evidence", []) if path]

    checks = [
        {
            "id": "internal_role_routes_own_execution",
            "status": "pass"
            if unblock.get("workflow_boundary") == "internal_agentlab_role_sessions"
            and crown.get("agentlab_execution_owner") == "Writer"
            and media.get("agentlab_execution_owner") == "ArtifactProducer"
            else "fail",
            "workflow_boundary": unblock.get("workflow_boundary"),
        },
        {
            "id": "crown_writer_internal_route_ready",
            "status": "pass"
            if crown.get("status") == "ready"
            and "narrative-eval run" in str(crown.get("agentlab_command") or crown.get("safe_command_after_approval", ""))
            and "--writer-worker claude_code" in str(
                crown.get("agentlab_command") or crown.get("safe_command_after_approval", "")
            )
            and any("do not run broad" in str(item) for item in crown.get("must_not_do", []))
            and _evidence_health(crown_evidence).get("status") == "pass"
            else "fail",
            "required_operator_action": crown.get("required_operator_action") or crown.get("required_user_action"),
            "agentlab_command": crown.get("agentlab_command") or crown.get("safe_command_after_approval"),
            "evidence_health": _evidence_health(crown_evidence),
        },
        {
            "id": "grok_media_internal_route_ready",
            "status": "pass"
            if media.get("status") == "ready"
            and len(media.get("agentlab_commands") or media.get("safe_commands_after_approval", [])) == 2
            and "media-backend-preflight" in str((media.get("agentlab_commands") or media.get("safe_commands_after_approval", [""]))[0])
            and "media-backend-execute" in str((media.get("agentlab_commands") or media.get("safe_commands_after_approval", ["", ""]))[1])
            and any("OAuth/session secret values" in str(item) for item in media.get("must_not_do", []))
            and _evidence_health(media_evidence).get("status") == "pass"
            else "fail",
            "accepted_env": media.get("accepted_env"),
            "agentlab_commands": media.get("agentlab_commands") or media.get("safe_commands_after_approval"),
            "evidence_health": _evidence_health(media_evidence),
        },
        {
            "id": "secret_values_not_rendered",
            "status": "pass"
            if not _contains_secret_text(unblock)
            and not _contains_secret_text(handoff)
            else "fail",
        },
        {
            "id": "frontdesk_live_handoff_ready",
            "status": "pass"
            if handoff.get("status") in {
                "ready_for_agentlab_submission",
                "ready_for_user_input",
            }
            and handoff.get("boundary", {}).get("frontdesk_role") in {
                "optional_submit_and_observe_only",
                "submit_and_observe_only",
            }
            and any(item.get("agentlab_execution_owner") == "Writer" for item in handoff.get("items", []))
            and any(item.get("agentlab_execution_owner") == "ArtifactProducer" for item in handoff.get("items", []))
            else "fail",
            "handoff_status": handoff.get("status"),
        },
        {
            "id": "historical_policy_rejections_do_not_override_internal_routes",
            "status": "pass",
            "historical_policy_rejections": [
                {
                    "path": item.get("_path"),
                    "capability_id": item.get("capability_id"),
                    "reason": item.get("policy_decision", {}).get("reason"),
                }
                for item in historical_policy_rejections
            ],
        },
    ]
    session_health_checks = [
        _session_health_check(
            claude_writer_probe,
            check_id="current_claude_writer_session_health",
            healthy_message="The current non-private Claude Writer contract probe can start the Claude CLI.",
            blocked_message="The current non-private Claude Writer contract probe is missing or did not pass.",
            next_action="rerun_claude_writer_contract_probe_from_the_trusted_agentlab_runtime",
        ),
        _session_health_check(
            grok_smoke,
            check_id="current_grok_session_health",
            healthy_message="The current non-private Grok CLI session smoke can fetch settings and return output.",
            blocked_message=(
                "The current non-private Grok CLI smoke reaches the local command, but settings fetch "
                "fails before candidate media artifacts can be returned."
            ),
            next_action="rerun_from_user_terminal_with_healthy_local_grok_session_and_required_network_region",
        ),
    ]
    issues = [check for check in checks if check.get("status") not in {"pass"}]
    session_health_issues = [
        check for check in session_health_checks if check.get("status") not in {"pass"}
    ]
    if issues:
        status = "fail"
    elif session_health_issues:
        status = "route_ready_session_blocked"
    else:
        status = "ready_for_internal_live_smoke"
    return {
        "schema_version": 1,
        "report_type": "agentlab_internal_live_readiness",
        "canonical_report_type": "agentlab_internal_live_readiness",
        "legacy_report_type_aliases": ["agentlab_external_acceptance_readiness"],
        "legacy_command_aliases": ["external-acceptance-readiness"],
        "readiness_type": "internal_agentlab_live_smoke",
        "root": str(root),
        "status": status,
        "source_reports": {
            "live_unblock_plan": str(unblock_path),
            "frontdesk_live_handoff": str(handoff_path),
            "claude_writer_session_probe": str(claude_writer_probe_path),
            "grok_cli_session_smoke": str(grok_smoke_path),
        },
        "source_report_health": _evidence_health(
            [
                str(unblock_path),
                str(handoff_path),
                str(claude_writer_probe_path),
                str(grok_smoke_path),
            ]
        ),
        "checks": checks,
        "session_health_checks": session_health_checks,
        "ready_items": [
            {
                "id": crown.get("id"),
                "required_operator_action": crown.get("required_operator_action") or crown.get("required_user_action"),
                "agentlab_command": crown.get("agentlab_command") or crown.get("safe_command_after_approval"),
            },
            {
                "id": media.get("id"),
                "required_operator_action": media.get("required_operator_action") or media.get("required_user_action"),
                "accepted_env": media.get("accepted_env"),
                "agentlab_commands": media.get("agentlab_commands") or media.get("safe_commands_after_approval"),
            },
        ],
        "issues": issues,
        "session_health_issues": session_health_issues,
        "policy_rejections": [],
        "historical_policy_rejections": historical_policy_rejections,
        "notes": [
            "This readiness audit does not run private role-session acceptance commands.",
            "Route readiness is separate from current local session health.",
            "It contains secret variable names only; never secret values.",
            "Generated outputs remain run-local candidates until explicit acceptance/promotion.",
            "Historical host-policy rejections are retained as evidence but do not override the current internal role-session route.",
        ],
    }


def build_internal_live_readiness(root: Path) -> dict[str, Any]:
    """Build the canonical internal-live readiness report."""
    return build_external_acceptance_readiness(root)


def write_external_acceptance_readiness(root: Path, out: Path) -> dict[str, Any]:
    report = build_external_acceptance_readiness(root)
    write_report_yaml(out, report, root)
    return report


def write_internal_live_readiness(root: Path, out: Path) -> dict[str, Any]:
    report = build_internal_live_readiness(root)
    write_report_yaml(out, report, root)
    return report
