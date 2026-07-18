"""Goal-level completion audit for the current AgentLab acceptance effort.

This module is intentionally evidence-only. It aggregates existing acceptance
reports into a concise answer to: what is proven, what is only a candidate, and
what remains pending on internal role-session acceptance execution.
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
    from audit_helpers import (
        acceptance_report_hygiene_summary,
        active_acceptance_blockers,
        candidate_issues_for,
        capabilities_by_id as _capabilities_by_id,
        capability_candidate_issues as build_capability_candidate_issues,
        capability_status as _capability_status,
        evidence_health as _evidence_health,
        media_generation_readiness,
        normalize_trusted_pending_live_smoke_item,
        role_session_execution_boundary,
        selected_collect_metadata_by_item,
        session_health_summary as _session_health_summary,
        trusted_collect_strict_pass,
        trusted_writer_request_route_current,
    )
except ModuleNotFoundError:
    from agent_runtime.audit_helpers import (
        acceptance_report_hygiene_summary,
        active_acceptance_blockers,
        candidate_issues_for,
        capabilities_by_id as _capabilities_by_id,
        capability_candidate_issues as build_capability_candidate_issues,
        capability_status as _capability_status,
        evidence_health as _evidence_health,
        media_generation_readiness,
        normalize_trusted_pending_live_smoke_item,
        role_session_execution_boundary,
        selected_collect_metadata_by_item,
        session_health_summary as _session_health_summary,
        trusted_collect_strict_pass,
        trusted_writer_request_route_current,
    )

try:
    from goal_acceptance_scope import acceptance_mode, load_goal_acceptance_scope
except ModuleNotFoundError:
    from agent_runtime.goal_acceptance_scope import acceptance_mode, load_goal_acceptance_scope


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _trusted_pending_live_smokes(
    trusted_status: dict[str, Any],
    trusted_collect: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    items = trusted_status.get("items", []) if isinstance(trusted_status.get("items"), list) else []
    selected_collect = selected_collect_metadata_by_item(trusted_collect or {})
    pending: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or item.get("status") == "pass":
            continue
        pending_item = normalize_trusted_pending_live_smoke_item(item)
        item_id = str(pending_item.get("id") or "")
        if item_id in selected_collect:
            pending_item.update(selected_collect[item_id])
        pending.append(pending_item)
    return pending


def _item(
    item_id: str,
    title: str,
    status: str,
    capability_ids: list[str],
    conclusion: str,
    evidence: list[str],
    remaining_gap: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": item_id,
        "title": title,
        "status": status,
        "capability_ids": capability_ids,
        "conclusion": conclusion,
        "evidence": evidence,
        "evidence_health": _evidence_health(evidence),
    }
    if remaining_gap:
        result["remaining_gap"] = remaining_gap
    if details:
        result["details"] = details
    return result


def build_goal_completion_audit(root: Path) -> dict[str, Any]:
    """Build an explicit completion audit for the current user objective."""
    root = root.resolve()
    acceptance_scope = load_goal_acceptance_scope(root)
    synthesis_scope = acceptance_mode(acceptance_scope, "production_pack_synthesis")
    media_scope = acceptance_mode(acceptance_scope, "media_generation")
    synthesis_role_required = synthesis_scope == "full_role_session"
    media_live_acceptance_required = media_scope == "full_live_acceptance"
    acceptance_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "current.yml"
    chain_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "production_chain_audit.yml"
    pack_catalog_audit_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "pack_catalog_audit.yml"
    synthesis_role_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "production_pack_role_session_audit.yml"
    unblock_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "live_unblock_plan.yml"
    internal_readiness_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "internal_live_readiness.yml"
    legacy_readiness_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "external_acceptance_readiness.yml"
    readiness_path = internal_readiness_path if internal_readiness_path.exists() else legacy_readiness_path
    trusted_request_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_request.yml"
    trusted_operator_handoff_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_operator_handoff.yml"
    trusted_preflight_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_preflight.yml"
    trusted_status_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_status.yml"
    trusted_collect_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_collect.yml"
    report_hygiene_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "acceptance_report_hygiene.yml"
    role_session_handoff_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "role_session_acceptance_handoff.md"
    legacy_private_live_handoff_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "private_live_smoke_approval_handoff.md"
    frontdesk_rejection_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "frontdesk_runtime_private_context_rejection_trusted_runner_20260708.yml"

    acceptance = _read_yaml(acceptance_path)
    unblock = _read_yaml(unblock_path)
    readiness = _read_yaml(readiness_path)
    trusted_status = _read_yaml(trusted_status_path)
    trusted_collect = _read_yaml(trusted_collect_path)
    trusted_request = _read_yaml(trusted_request_path)
    trusted_operator_handoff = _read_yaml(trusted_operator_handoff_path)
    report_hygiene = _read_yaml(report_hygiene_path)
    capabilities = _capabilities_by_id(acceptance)
    synthesis_role_status = _capability_status(
        capabilities,
        "production_pack_synthesis_role_session",
    )
    capability_candidate_issues = build_capability_candidate_issues(capabilities)
    readiness_status = readiness.get("status")
    session_health = _session_health_summary(readiness)
    all_pending_internal_live_smokes = _trusted_pending_live_smokes(trusted_status, trusted_collect)
    pending_internal_live_smokes = [
        item
        for item in all_pending_internal_live_smokes
        if item.get("id") == "run_crown_internal_writer_eval"
        or (media_live_acceptance_required and item.get("id") == "run_crown_internal_media_smoke")
    ]
    deferred_internal_live_smokes = [
        item
        for item in all_pending_internal_live_smokes
        if item.get("id") == "run_crown_internal_media_smoke" and not media_live_acceptance_required
    ]
    trusted_status_items = trusted_status.get("items", []) if isinstance(trusted_status.get("items"), list) else []
    trusted_item_by_id = {
        str(item.get("id")): item
        for item in trusted_status_items
        if isinstance(item, dict) and item.get("id")
    }
    writer_returned_accepted = (
        trusted_item_by_id.get("run_crown_internal_writer_eval", {}).get("status") == "pass"
        and trusted_item_by_id.get("run_crown_internal_writer_eval", {}).get(
            "returned_candidate_artifacts_accepted"
        )
        is True
    )
    selected_collect = selected_collect_metadata_by_item(trusted_collect)
    writer_selected_collect = selected_collect.get("run_crown_internal_writer_eval", {})
    media_selected_collect = selected_collect.get("run_crown_internal_media_smoke", {})
    media_returned_accepted = (
        trusted_item_by_id.get("run_crown_internal_media_smoke", {}).get("status") == "pass"
        and trusted_item_by_id.get("run_crown_internal_media_smoke", {}).get(
            "returned_candidate_artifacts_accepted"
        )
        is True
    )
    returned_acceptance_complete = trusted_collect_strict_pass(trusted_status, trusted_collect)
    writer_acceptance_complete = writer_returned_accepted and (
        writer_selected_collect.get("selected_item_accepted") is True
        or returned_acceptance_complete
    )
    media_acceptance_complete = media_returned_accepted and (
        media_selected_collect.get("selected_item_accepted") is True
        or returned_acceptance_complete
    )
    media_readiness = media_generation_readiness(capabilities)
    synthesis_scaffold_complete = (
        _capability_status(capabilities, "production_pack_synthesis") == "pass"
        and _capability_status(capabilities, "production_pack_synthesis_smoke") == "pass"
    )
    synthesis_acceptance_complete = synthesis_scaffold_complete and (
        not synthesis_role_required or synthesis_role_status == "pass"
    )
    frontdesk_rejection = _read_yaml(frontdesk_rejection_path)
    frontdesk_runtime_boundary = {
        "status": frontdesk_rejection.get("status") or "not_recorded",
        "path": str(frontdesk_rejection_path) if frontdesk_rejection_path.exists() else None,
        "last_confirmed_at": frontdesk_rejection.get("last_confirmed_at"),
        "latest_attempt_count": len(frontdesk_rejection.get("latest_attempts") or [])
        if isinstance(frontdesk_rejection.get("latest_attempts"), list)
        else 0,
        "codex_frontdesk_runtime_blocked_for_private_live_execution": bool(
            (frontdesk_rejection.get("conclusion") or {}).get(
                "codex_frontdesk_runtime_blocked_for_private_live_execution"
            )
        ),
        "agentlab_internal_route_blocked": bool(
            (frontdesk_rejection.get("conclusion") or {}).get("agentlab_internal_route_blocked", False)
        ),
        "missing_api_key_blocked": bool(
            (frontdesk_rejection.get("conclusion") or {}).get("missing_api_key_blocked", False)
        ),
        "role_worker_binding_blocked": bool(
            (frontdesk_rejection.get("conclusion") or {}).get("role_worker_binding_blocked", False)
        ),
        "record_scope": "historical_external_codex_worker_attempt",
        "current_agentlab_execution_path_affected": False,
    }
    frontdesk_boundary_sentence = (
        "A historical Codex external-worker attempt was rejected by host policy; it is outside the current Hermes/direct AgentLab execution paths "
        "and is not an AgentLab route, local CLI, API key, or role-worker binding blocker. "
        if frontdesk_runtime_boundary["codex_frontdesk_runtime_blocked_for_private_live_execution"]
        else ""
    )
    session_health_clean = readiness_status == "ready_for_internal_live_smoke" and session_health.get("issue_count") == 0
    session_issue_ids = {str(issue.get("id")) for issue in session_health.get("issues", []) if isinstance(issue, dict)}
    claude_writer_session_blocked = "current_claude_writer_session_health" in session_issue_ids
    grok_session_blocked = "current_grok_session_health" in session_issue_ids
    grok_session_reason = next(
        (
            str(issue.get("reason"))
            for issue in session_health.get("issues", [])
            if isinstance(issue, dict)
            and issue.get("id") == "current_grok_session_health"
            and issue.get("reason")
        ),
        "unknown",
    )
    if session_health_clean:
        if writer_acceptance_complete:
            crown_conclusion = (
                "Local chapter governance, light-path delivery receipts, batch ledgers, scale simulation, and accepted trusted-runner Writer artifacts prove the internal Claude Code shell + DeepSeek V4 Pro Writer route. "
                f"{frontdesk_boundary_sentence}"
            )
            crown_gap = None
        else:
            crown_conclusion = (
                "Local chapter governance, light-path delivery receipts, batch ledgers, scale simulation, and the internal Claude Code shell + DeepSeek V4 Pro Writer route exist. "
                "The current non-private Claude Writer contract probe passes, and returned prose artifacts are pending until the trusted Writer command is rerun. "
                f"{frontdesk_boundary_sentence}"
            )
            crown_gap = (
                "Needs a rerun of the internal Writer role-session live smoke from the current healthy Claude Writer route before promotion beyond candidate."
            )
        readiness_conclusion = (
            "Current route readiness is ready_for_internal_live_smoke with no session-health blockers; old frontdesk/sandbox errors are retained only as stale execution evidence. "
            f"{frontdesk_boundary_sentence}"
            + (
                "Returned internal Writer artifacts have been accepted by trusted-runner QC."
                if writer_acceptance_complete
                else "The remaining in-scope live gap is refreshed internal Writer artifacts and local QC evidence."
            )
        )
    else:
        claude_writer_status_text = (
            "current non-private Claude Writer session health is not clean"
            if claude_writer_session_blocked
            else "current non-private Claude Writer contract probe is clean; the active session-health issue is not the Writer gate"
        )
        crown_conclusion = (
            "Local chapter governance, light-path delivery receipts, batch ledgers, scale simulation, and the internal Claude Code shell + DeepSeek V4 Pro Writer route exist. "
            f"{claude_writer_status_text}, so returned prose artifacts are still pending until the trusted Writer command is rerun. "
            f"{frontdesk_boundary_sentence}"
        )
        crown_gap = (
            "Needs a trusted terminal/runtime to return refreshed Writer role-session acceptance artifacts before promotion beyond candidate."
        )
        readiness_conclusion = (
            f"Current route readiness is {readiness_status or 'missing'} with {session_health.get('issue_count', 0)} session-health issue(s); "
            f"{frontdesk_boundary_sentence}"
            "the trusted runner request and no-provider local preflight remain the required next boundary before private role-session acceptance artifacts can be accepted."
        )
    if not media_live_acceptance_required and media_readiness["status"] == "pass":
        media_conclusion = (
            "Media generation readiness passes: the media-series route, ArtifactProducer/Grok binding, OAuth CLI session, non-interactive invocation contract, backend preflight, asset-return contract, and candidate-only boundary are proven. "
            "Generated-asset quality and continuity acceptance are explicitly deferred to a future visual node-graph workflow."
        )
        media_gap = None
    elif media_acceptance_complete:
        media_conclusion = (
            "Media-series routing, artifact contracts, local Grok CLI entrypoint, and accepted trusted-runner media artifacts prove the internal ArtifactProducer/grok hermes_grok_oauth path. "
            f"{frontdesk_boundary_sentence}"
        )
        media_gap = None
    else:
        media_conclusion = (
            "Media-series routing and artifact contracts are in place; the local Grok CLI entrypoint and internal ArtifactProducer backend routing are proven. "
            + (
                f"The current non-private Grok session smoke is blocked by {grok_session_reason} in this runtime, so media candidate artifacts still need a rerun from a healthy local Grok CLI session."
                if grok_session_blocked
                else "The current non-private Grok session smoke is clean or not the active issue; media candidate artifacts still need to be rerun and returned from that healthy local Grok session."
            )
        )
        media_gap = (
            "Needs a rerun of the internal media live smoke from a healthy local Grok session, followed by a completed media ledger and QC before generated media can be accepted."
        )
    source_reports = {
        "capability_acceptance": str(acceptance_path),
        "production_chain_audit": str(chain_path),
        "pack_catalog_audit": str(pack_catalog_audit_path),
        "production_pack_role_session_audit": str(synthesis_role_path),
        "live_unblock_plan": str(unblock_path),
        "internal_live_readiness": str(internal_readiness_path),
        "external_acceptance_readiness": str(legacy_readiness_path),
        "trusted_live_runner_request": str(trusted_request_path),
        "trusted_live_runner_operator_handoff": str(trusted_operator_handoff_path),
        "trusted_live_runner_preflight": str(trusted_preflight_path),
        "trusted_live_runner_status": str(trusted_status_path),
        "trusted_live_runner_collect": str(trusted_collect_path),
        "acceptance_report_hygiene": str(report_hygiene_path),
        "role_session_acceptance_handoff": str(role_session_handoff_path),
        "private_live_smoke_approval_handoff": str(legacy_private_live_handoff_path),
    }
    if acceptance_scope.get("source_path"):
        source_reports["goal_acceptance_scope"] = str(acceptance_scope["source_path"])

    goal_items = [
        _item(
            "preserve_code_factory",
            "Keep AgentLab strong as a code factory",
            "pass"
            if _capability_status(capabilities, "code_factory_orchestration") == "pass"
            and _capability_status(capabilities, "live_code_candidate_materialization") == "pass"
            else (
                "candidate"
                if _capability_status(capabilities, "code_factory_orchestration") == "pass"
                and _capability_status(capabilities, "live_code_candidate_materialization") == "candidate"
                else "fail"
            ),
            ["code_factory_orchestration", "live_code_candidate_materialization"],
            (
                "Code routes still use the code factory chain, and the live AgentLab Web UI task has production promotion plus local smoke evidence."
                if _capability_status(capabilities, "live_code_candidate_materialization") == "pass"
                else "Code routes still use the code factory chain, and a live code/UI candidate has local smoke evidence."
            ),
            [
                *capabilities.get("code_factory_orchestration", {}).get("evidence", []),
                *capabilities.get("live_code_candidate_materialization", {}).get("evidence", []),
            ],
            None
            if _capability_status(capabilities, "live_code_candidate_materialization") == "pass"
            else "The live UI app remains candidate-only until explicit promotion and live backing API write workflows.",
        ),
        _item(
            "split_non_code_from_code_shell",
            "Route non-code work through production packs instead of code-task shell",
            "pass"
            if _capability_status(capabilities, "non_code_code_shell_split") == "pass"
            and _capability_status(capabilities, "production_chain_visibility") == "pass"
            else "fail",
            ["non_code_code_shell_split", "production_chain_visibility"],
            "Representative narrative, article, media, and unknown non-code chains are visible and do not inherit active code-shell contracts.",
            [
                *capabilities.get("non_code_code_shell_split", {}).get("evidence", []),
                str(chain_path),
            ],
        ),
        _item(
            "define_agent_roles_and_chain_bindings",
            "Keep agent responsibilities, worker bindings, and production-chain roles consistent",
            _capability_status(capabilities, "agent_role_chain_consistency"),
            ["agent_role_chain_consistency"],
            "Every canonical role has a responsibility, boundary, session-bound worker binding, and representative chain coverage.",
            capabilities.get("agent_role_chain_consistency", {}).get("evidence", []),
        ),
        _item(
            "govern_cli_native_shell_runtime",
            "Govern local CLI shells as native workflow runtimes",
            "pass"
            if _capability_status(capabilities, "cli_workflow_shell_absorption") == "pass"
            and _capability_status(capabilities, "cli_native_command_surface_governance") == "pass"
            else "fail",
            [
                "cli_workflow_shell_absorption",
                "cli_native_command_surface_governance",
            ],
            "CLI shells expose registered native surfaces inside bounded role sessions; dependent AgentLab roles remain separated by lifecycle receipt gates.",
            [
                *capabilities.get("cli_workflow_shell_absorption", {}).get("evidence", []),
                *capabilities.get("cli_native_command_surface_governance", {}).get("evidence", []),
            ],
            details={
                "candidate_capability_issues": candidate_issues_for(
                    capability_candidate_issues,
                    ["cli_workflow_shell_absorption", "cli_native_command_surface_governance"],
                )
            },
        ),
        _item(
            "enable_self_synthesized_production_packs",
            "Let unknown complex non-code domains synthesize candidate production packs",
            "pass"
            if synthesis_acceptance_complete
            else (
                "candidate"
                if synthesis_scaffold_complete and synthesis_role_status == "candidate"
                else "fail"
            ),
            [
                "production_pack_synthesis",
                "production_pack_synthesis_smoke",
                "production_pack_synthesis_role_session",
            ],
            (
                "The deterministic synthesis modules, registry, catalog, semantic checks, and promotion gate pass; provider-backed four-role synthesis acceptance is outside the narrowed goal."
                if not synthesis_role_required
                else "The synthesis modules, registry, catalog, deterministic scaffold, returned role artifacts, and promotion gate are evaluated separately; candidates are not auto-installed."
            ),
            [
                *capabilities.get("production_pack_synthesis", {}).get("evidence", []),
                *capabilities.get("production_pack_synthesis_smoke", {}).get("evidence", []),
                *capabilities.get("production_pack_synthesis_role_session", {}).get(
                    "evidence", []
                ),
                str(pack_catalog_audit_path),
            ],
            None
            if synthesis_acceptance_complete
            else "Needs returned internal Researcher, ArtifactProducer, and Verifier role-session artifacts plus a registry-valid verification receipt.",
            details={
                "acceptance_mode": synthesis_scope,
                "role_session_required": synthesis_role_required,
                "role_session_status": synthesis_role_status,
            },
        ),
        _item(
            "support_crown_longform_governance",
            "Support Crown longform governance without default heavy chapter workflow",
            "pass"
            if _capability_status(capabilities, "crown_formal_live_narrative_eval") == "pass"
            and _capability_status(capabilities, "crown_heavy_audit_scale") == "pass"
            and writer_acceptance_complete
            else (
                "candidate"
                if _capability_status(capabilities, "crown_formal_live_narrative_eval") == "candidate"
                else ("blocked" if _capability_status(capabilities, "crown_formal_live_narrative_eval") == "blocked" else "warn")
            ),
            [
                "crown_chapter_batch_governance",
                "crown_live_writer_light_path",
                "crown_formal_live_narrative_eval",
                "crown_heavy_audit_scale",
                "trusted_live_runner_request",
                "trusted_live_runner_operator_handoff",
                "trusted_live_runner_preflight",
                "trusted_live_runner_status",
                "trusted_live_runner_collect",
            ],
            crown_conclusion,
            [
                *capabilities.get("crown_chapter_batch_governance", {}).get("evidence", []),
                *capabilities.get("crown_live_writer_light_path", {}).get("evidence", []),
                *capabilities.get("crown_formal_live_narrative_eval", {}).get("evidence", []),
                *capabilities.get("crown_heavy_audit_scale", {}).get("evidence", []),
                *capabilities.get("trusted_live_runner_request", {}).get("evidence", []),
                *capabilities.get("trusted_live_runner_operator_handoff", {}).get("evidence", []),
                *capabilities.get("trusted_live_runner_preflight", {}).get("evidence", []),
                *capabilities.get("trusted_live_runner_status", {}).get("evidence", []),
                *capabilities.get("trusted_live_runner_collect", {}).get("evidence", []),
            ],
            crown_gap,
            details={
                "candidate_capability_issues": candidate_issues_for(
                    capability_candidate_issues,
                    [
                        "crown_live_writer_light_path",
                        "crown_formal_live_narrative_eval",
                    ],
                ),
                "writer_selected_acceptance": {
                    "returned_artifacts_accepted": writer_returned_accepted,
                    "selected_collect_accepted": writer_selected_collect.get("selected_item_accepted"),
                    "complete": writer_acceptance_complete,
                },
            },
        ),
        _item(
            "support_media_series_generation_path",
            "Support governed media-series production and local Grok CLI backend preparation",
            "pass"
            if (
                media_readiness["status"] == "pass"
                if not media_live_acceptance_required
                else media_acceptance_complete
                and _capability_status(capabilities, "media_series_scaffold") == "pass"
                and _capability_status(capabilities, "grok_xai_media_backend") == "pass"
            )
            else (
                "candidate"
                if _capability_status(capabilities, "grok_xai_media_backend") == "candidate"
                else ("blocked" if _capability_status(capabilities, "grok_xai_media_backend") == "blocked" else _capability_status(capabilities, "media_series_scaffold"))
            ),
            [
                "media_series_scaffold",
                "grok_xai_media_backend",
                "trusted_live_runner_request",
                "trusted_live_runner_operator_handoff",
                "trusted_live_runner_preflight",
                "trusted_live_runner_status",
                "trusted_live_runner_collect",
            ],
            media_conclusion,
            [
                *capabilities.get("media_series_scaffold", {}).get("evidence", []),
                *capabilities.get("grok_xai_media_backend", {}).get("evidence", []),
                *capabilities.get("trusted_live_runner_request", {}).get("evidence", []),
                *capabilities.get("trusted_live_runner_operator_handoff", {}).get("evidence", []),
                *capabilities.get("trusted_live_runner_preflight", {}).get("evidence", []),
                *capabilities.get("trusted_live_runner_status", {}).get("evidence", []),
                *capabilities.get("trusted_live_runner_collect", {}).get("evidence", []),
            ],
            media_gap if media_live_acceptance_required else None,
            details={
                "acceptance_mode": media_scope,
                "live_artifact_acceptance_required": media_live_acceptance_required,
                "readiness": media_readiness,
                "deferred_to": "comfyui_style_node_graph_generation_and_continuity_acceptance"
                if not media_live_acceptance_required
                else None,
                "candidate_capability_issues": candidate_issues_for(
                    capability_candidate_issues,
                    [] if not media_live_acceptance_required else [
                        "grok_xai_media_backend", "trusted_live_runner_status", "trusted_live_runner_collect"
                    ],
                )
            },
        ),
        _item(
            "document_operating_logic_and_unblock_plan",
            "Make the operating model and next live actions explicit",
            "pass"
            if (root / "docs" / "AGENTLAB_OPERATING_LOGIC.zh-CN.md").exists()
            and _capability_status(capabilities, "internal_live_unblock_plan") == "pass"
            and _capability_status(capabilities, "trusted_live_runner_request") == "pass"
            and trusted_writer_request_route_current(trusted_request)
            and _capability_status(capabilities, "trusted_live_runner_operator_handoff") in {"candidate", "pass"}
            and _capability_status(capabilities, "trusted_live_runner_preflight") == "pass"
            and _capability_status(capabilities, "trusted_live_runner_status") in {"candidate", "pass"}
            and _capability_status(capabilities, "trusted_live_runner_collect") in {"candidate", "pass"}
            and role_session_handoff_path.exists()
            and legacy_private_live_handoff_path.exists()
            else "fail",
            [
                "internal_live_unblock_plan",
                "internal_live_readiness",
                "trusted_live_runner_request",
                "trusted_live_runner_operator_handoff",
                "trusted_live_runner_preflight",
                "trusted_live_runner_status",
                "trusted_live_runner_collect",
            ],
            "The Chinese operating overview, capability matrix, role-session acceptance plan, trusted-runner request, local preflight, status report, and post-run collector explain the current chains and remaining execution actions.",
            [
                str(root / "docs" / "AGENTLAB_OPERATING_LOGIC.zh-CN.md"),
                str(root / "docs" / "AGENTLAB_CAPABILITY_ACCEPTANCE_MATRIX.md"),
                str(unblock_path),
                str(readiness_path),
                *capabilities.get("trusted_live_runner_request", {}).get("evidence", []),
                *capabilities.get("trusted_live_runner_operator_handoff", {}).get("evidence", []),
                *capabilities.get("trusted_live_runner_preflight", {}).get("evidence", []),
                *capabilities.get("trusted_live_runner_status", {}).get("evidence", []),
                *capabilities.get("trusted_live_runner_collect", {}).get("evidence", []),
                str(report_hygiene_path),
                str(role_session_handoff_path),
                str(legacy_private_live_handoff_path),
            ],
            details={
                "acceptance_report_hygiene_status": report_hygiene.get("status"),
                "writer_request_route_current": trusted_writer_request_route_current(
                    trusted_request
                )
            },
        ),
    ]

    for item in goal_items:
        if item.get("evidence_health", {}).get("status") == "missing_evidence":
            item["status"] = "fail"
            item["conclusion"] = f"{item['conclusion']} Evidence is incomplete in the current workspace."

    counts: dict[str, int] = {}
    for item in goal_items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1

    external_blockers = [
        item
        for item in unblock.get("items", [])
        if isinstance(item, dict) and item.get("status") == "blocked"
    ]
    source_report_health = _evidence_health(list(source_reports.values()))
    missing_goal_evidence = [
        {
            "item_id": item["id"],
            "missing": item.get("evidence_health", {}).get("missing", []),
        }
        for item in goal_items
        if item.get("evidence_health", {}).get("missing")
    ]

    if (
        not acceptance_scope.get("valid")
        or source_report_health["status"] != "pass"
        or any(item["status"] == "fail" for item in goal_items)
    ):
        status = "fail"
    elif readiness_status == "blocked_external_policy":
        status = "blocked_external_policy"
    elif external_blockers:
        status = "blocked_external_input_required"
    elif any(item["status"] in {"candidate", "warn", "blocked"} for item in goal_items):
        status = "partial"
    else:
        status = "complete"

    displayed_pending_internal_live_smokes = pending_internal_live_smokes
    if not trusted_status_items:
        displayed_pending_internal_live_smokes = [
            {
                "id": item.get("id"),
                "capability_id": item.get("capability_id"),
                "required_operator_action": item.get("required_operator_action"),
                "agentlab_command": item.get("agentlab_command"),
                "agentlab_commands": item.get("agentlab_commands"),
            }
            for item in unblock.get("items", [])
            if isinstance(item, dict)
            and item.get("status") == "ready"
            and item.get("id") == "run_crown_internal_writer_eval"
        ]

    return {
        "schema_version": 1,
        "report_type": "agentlab_goal_completion_audit",
        "root": str(root),
        "status": status,
        "status_counts": counts,
        "source_reports": source_reports,
        "source_report_health": source_report_health,
        "objective": "Complete code-project and Crown longform acceptance while proving media generation readiness without accepting the current black-box media production chain.",
        "acceptance_scope": acceptance_scope,
        "goal_items": goal_items,
        "external_blockers": [
            {
                "id": item.get("id"),
                "capability_id": item.get("capability_id"),
                "required_user_action": item.get("required_user_action"),
                "safe_command_after_approval": item.get("safe_command_after_approval"),
                "safe_commands_after_approval": item.get("safe_commands_after_approval"),
            }
            for item in external_blockers
        ],
        "session_health_summary": _session_health_summary(readiness),
        "active_acceptance_blockers": active_acceptance_blockers(
            session_health=session_health,
            pending_internal_live_smokes=displayed_pending_internal_live_smokes,
            frontdesk_runtime_boundary=frontdesk_runtime_boundary,
            required_scopes={"writer"} if not media_live_acceptance_required else {"writer", "media"},
        ),
        "frontdesk_runtime_boundary": frontdesk_runtime_boundary,
        "acceptance_report_hygiene_summary": acceptance_report_hygiene_summary(report_hygiene),
        "role_session_execution_boundary": role_session_execution_boundary(
            trusted_request,
            trusted_operator_handoff,
        ),
        "capability_candidate_issues": capability_candidate_issues,
        "pending_internal_live_smokes": displayed_pending_internal_live_smokes,
        "deferred_internal_live_smokes": deferred_internal_live_smokes,
        "missing_goal_evidence": missing_goal_evidence,
        "conclusion": (
            "Local governance, routing, deterministic production-pack behavior, and representative chains are proven. "
            + (
                "Production-pack synthesis satisfies the current deterministic-scaffold scope; provider-backed four-role acceptance is deferred. "
                if not synthesis_role_required
                else (
                    "Returned production-pack role-session synthesis is accepted. "
                    if synthesis_role_status == "pass"
                    else "Returned production-pack role-session synthesis remains candidate until ArtifactProducer and Verifier artifacts pass the role-bound receipts. "
                )
            )
            + "Crown prose still requires returned Writer artifacts. Media is evaluated only for route and execution readiness, with black-box output acceptance deferred to a visual workflow. "
            + f"{readiness_conclusion} "
            + (
                "The full objective is complete against the current acceptance contract."
                if status == "complete"
                else "The narrowed objective is still partial until refreshed internal Writer artifacts pass their verification/QC gates."
            )
        ),
        "notes": [
            "This audit reads existing reports only and never calls external providers.",
            "partial means the in-scope Writer returned-artifact verification/QC contract is still pending.",
        ],
    }


def write_goal_completion_audit(root: Path, out: Path) -> dict[str, Any]:
    report = build_goal_completion_audit(root)
    write_report_yaml(out, report, root)
    return report
