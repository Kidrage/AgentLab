"""Requirement-level audit for the active AgentLab positioning objective.

This audit is intentionally stricter than the compact goal completion report:
it keeps the user's original objective visible as a list of concrete
requirements, then maps each requirement to current local evidence.
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

try:
    from agent_runtime.run_retention import resolve_run_dir
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from run_retention import resolve_run_dir


STATUS_RANK = {
    "pass": 0,
    "candidate": 1,
    "warn": 2,
    "blocked": 3,
    "fail": 4,
}
def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _unique_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for path in paths:
        if not path or path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def _canonical_evidence_path(path: str, root: Path) -> str:
    source = Path(path)
    resolved = source.resolve() if source.is_absolute() else (root / source).resolve()
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        return path


def _evidence_health_for_root(evidence: list[str], root: Path) -> dict[str, Any]:
    paths = [path for path in evidence if path]
    missing = [
        path
        for path in paths
        if not (Path(path).exists() if Path(path).is_absolute() else (root / path).exists())
    ]
    return {
        "status": "pass" if not missing else "missing_evidence",
        "checked": len(paths),
        "missing": missing,
    }


def _capability_evidence(capabilities: dict[str, dict[str, Any]], *capability_ids: str) -> list[str]:
    evidence: list[str] = []
    for capability_id in capability_ids:
        evidence.extend(str(path) for path in capabilities.get(capability_id, {}).get("evidence", []) if path)
    return _unique_paths(evidence)


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
        item_id = str(item.get("id") or "")
        expected_type = str(item.get("expected_type") or "")
        if "writer" in item_id or expected_type == "narrative_live_smoke":
            requirement_id = "test_crown_longform_1500_chapter_governance_and_live_generation"
        elif "media" in item_id or expected_type == "media_live_smoke":
            requirement_id = "test_grok_media_series_generation_for_crown"
        else:
            requirement_id = "document_complete_logic_and_remaining_unblocks"
        artifact_qc = item.get("artifact_qc") if isinstance(item.get("artifact_qc"), dict) else None
        artifact_qc_failed_checks = [
            str(check.get("id"))
            for check in artifact_qc.get("checks", []) if isinstance(check, dict) and check.get("status") == "fail"
        ] if artifact_qc else []
        common_pending_item = normalize_trusted_pending_live_smoke_item(item)
        pending_item = {
            "id": common_pending_item.get("id"),
            "validates_requirement": requirement_id,
            **{key: value for key, value in common_pending_item.items() if key != "id"},
        }
        if item_id in selected_collect:
            pending_item.update(selected_collect[item_id])
        if artifact_qc:
            pending_item["artifact_qc_status"] = artifact_qc.get("status")
        if artifact_qc_failed_checks:
            pending_item["artifact_qc_failed_checks"] = artifact_qc_failed_checks
        pending.append(pending_item)
    return pending


def _scenario_by_id(chain_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("scenario_id")): item
        for item in chain_report.get("scenarios", [])
        if isinstance(item, dict) and item.get("scenario_id")
    }


def _scenario_has_state_governance(scenario: dict[str, Any]) -> bool:
    pack = scenario.get("production_pack", {}) if isinstance(scenario.get("production_pack"), dict) else {}
    return (
        scenario.get("status") == "pass"
        and bool(pack.get("lifecycle_nodes"))
        and bool(pack.get("memory_contract"))
        and bool(pack.get("quality_gates"))
        and isinstance(scenario.get("artifact_intent"), dict)
    )


def _requirement(
    requirement_id: str,
    source_requirement: str,
    status: str,
    conclusion: str,
    evidence: list[str],
    remaining_gap: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    unique_evidence = _unique_paths(evidence)
    item: dict[str, Any] = {
        "id": requirement_id,
        "source_requirement": source_requirement,
        "status": status,
        "conclusion": conclusion,
        "evidence": unique_evidence,
        "evidence_health": _evidence_health(unique_evidence),
    }
    if remaining_gap:
        item["remaining_gap"] = remaining_gap
    if details:
        item["details"] = details
    return item


def _normalize_requirement_evidence(requirements: list[dict[str, Any]], root: Path) -> None:
    for item in requirements:
        evidence = item.get("evidence", [])
        if not isinstance(evidence, list):
            evidence = []
        normalized = _unique_paths([_canonical_evidence_path(str(path), root) for path in evidence if path])
        item["evidence"] = normalized
        item["evidence_health"] = _evidence_health_for_root(normalized, root)


def build_objective_requirement_audit(root: Path) -> dict[str, Any]:
    """Build a requirement-by-requirement audit for the user's full objective."""
    root = root.resolve()
    acceptance_scope = load_goal_acceptance_scope(root)
    synthesis_scope = acceptance_mode(acceptance_scope, "production_pack_synthesis")
    media_scope = acceptance_mode(acceptance_scope, "media_generation")
    synthesis_role_required = synthesis_scope == "full_role_session"
    media_live_acceptance_required = media_scope == "full_live_acceptance"
    acceptance_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "current.yml"
    chain_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "production_chain_audit.yml"
    role_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "agent_role_chain_audit.yml"
    synthesis_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "production_pack_synthesis_smoke.yml"
    synthesis_role_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "production_pack_role_session_audit.yml"
    pack_catalog_audit_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "pack_catalog_audit.yml"
    goal_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "goal_completion_audit.yml"
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
    media_audit_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "media_series_scaffold_audit.yml"
    ui_run_dir = resolve_run_dir(
        root,
        "AgentLab",
        "task_live_code_ui_app_json_binding_20260707",
    )
    ui_api_report_path = ui_run_dir / "ui_api_smoke_report.json"
    ui_action_ledger_path = ui_run_dir / "ui_action_ledger.json"
    ui_api_report = _read_yaml(ui_api_report_path) if ui_api_report_path.suffix in {".yml", ".yaml"} else {}
    if ui_api_report_path.exists() and not ui_api_report:
        try:
            import json

            ui_api_report = json.loads(ui_api_report_path.read_text(encoding="utf-8"))
        except Exception:
            ui_api_report = {}

    acceptance = _read_yaml(acceptance_path)
    readiness = _read_yaml(readiness_path)
    trusted_status = _read_yaml(trusted_status_path)
    trusted_collect = _read_yaml(trusted_collect_path)
    trusted_request = _read_yaml(trusted_request_path)
    trusted_operator_handoff = _read_yaml(trusted_operator_handoff_path)
    report_hygiene = _read_yaml(report_hygiene_path)
    capabilities = _capabilities_by_id(acceptance)
    chain = _read_yaml(chain_path)
    role = _read_yaml(role_path)
    synthesis = _read_yaml(synthesis_path)
    capability_candidate_issues = build_capability_candidate_issues(capabilities)
    scenarios = _scenario_by_id(chain)
    role_chains = role.get("production_chains", []) if isinstance(role.get("production_chains"), list) else []
    role_chain_lifecycle_failures = [
        str(item.get("scenario_id"))
        for item in role_chains
        if isinstance(item, dict)
        and isinstance(item.get("agent_lifecycle_coverage"), dict)
        and item["agent_lifecycle_coverage"].get("status") != "pass"
    ]
    role_chain_lifecycle_coverage_pass = bool(role_chains) and not role_chain_lifecycle_failures
    required_state_scenarios = [
        "code_factory_web_ui",
        "narrative_light_chapter",
        "article_light_draft",
        "narrative_heavy_audit",
        "media_series_production",
        "unknown_non_code_pack_synthesis",
    ]
    state_scenarios_ok = [
        scenario_id
        for scenario_id in required_state_scenarios
        if _scenario_has_state_governance(scenarios.get(scenario_id, {}))
    ]
    synthesis_validation = synthesis.get("proposal_validation", {})
    generated_artifacts = synthesis.get("generated_artifacts", {})
    synthesis_semantic_checks = (
        synthesis.get("semantic_checks", []) if isinstance(synthesis.get("semantic_checks"), list) else []
    )
    synthesis_semantic_failures = [
        str(check.get("id"))
        for check in synthesis_semantic_checks
        if isinstance(check, dict) and check.get("status") != "pass"
    ]
    synthesis_identity_boundary = (
        synthesis.get("pack_identity_boundary", {})
        if isinstance(synthesis.get("pack_identity_boundary"), dict)
        else {}
    )
    synthesis_identity_boundary_pass = synthesis_identity_boundary.get("status") == "pass"
    synthesis_scaffold_pass = (
        _capability_status(capabilities, "production_pack_synthesis") == "pass"
        and _capability_status(capabilities, "production_pack_synthesis_smoke") == "pass"
        and synthesis_validation.get("valid") is True
        and synthesis_identity_boundary_pass
        and not synthesis_semantic_failures
        and not generated_artifacts.get("missing")
        and synthesis.get("promotion", {}).get("attempted") is False
    )
    synthesis_role_status = _capability_status(
        capabilities,
        "production_pack_synthesis_role_session",
    )
    synthesis_role_details = capabilities.get(
        "production_pack_synthesis_role_session", {}
    ).get("details", {})
    synthesis_role_failed_checks = (
        synthesis_role_details.get("failed_checks", [])
        if isinstance(synthesis_role_details, dict)
        else []
    )
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
    agy_writer_session_blocked = "current_agy_writer_session_health" in session_issue_ids
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
            crown_live_conclusion = (
                "Local Crown governance, batch/scaled ledgers, one live candidate chapter, and accepted trusted-runner Writer artifacts prove the AGY Writer route with governed Claude Code + DeepSeek V4 Pro fallback. "
                f"{frontdesk_boundary_sentence}"
            )
            crown_live_gap = None
        else:
            crown_live_conclusion = (
                "Local Crown governance, batch/scaled ledgers, and one live candidate chapter exist; the formal live eval is routed through AGY with governed Claude Code + DeepSeek V4 Pro fallback. "
                "The current non-private AGY Writer contract probe passes; returned prose artifacts are still pending until the trusted Writer command is rerun and returns required files. "
                f"{frontdesk_boundary_sentence}"
            )
            crown_live_gap = (
                "Needs a rerun of the internal Writer live smoke from the current healthy AGY Writer route, followed by returned candidate artifacts and local delivery/QC evidence."
            )
        readiness_conclusion = (
            "Current route readiness is ready_for_internal_live_smoke with no session-health blockers; old frontdesk/sandbox errors are retained only as stale execution evidence. "
            f"{frontdesk_boundary_sentence}"
            + (
                "Returned internal Writer artifacts have been accepted by trusted-runner QC."
                if writer_acceptance_complete
                else "The remaining in-scope live gap is returned internal Writer artifacts and candidate QC."
            )
        )
    else:
        agy_writer_status_text = (
            "current non-private AGY Writer session health is not clean"
            if agy_writer_session_blocked
            else "current non-private AGY Writer contract probe is clean; the active session-health issue is not the Writer gate"
        )
        crown_live_conclusion = (
            "Local Crown governance, batch/scaled ledgers, and one live candidate chapter exist; the formal live eval is routed through AGY with governed Claude Code + DeepSeek V4 Pro fallback. "
            f"{agy_writer_status_text}; returned prose artifacts are still pending until the trusted Writer command is rerun. "
            f"{frontdesk_boundary_sentence}"
        )
        crown_live_gap = (
            "Needs a trusted terminal/runtime to return one refreshed internal Writer live smoke before the formal generation claim can be promoted beyond candidate."
        )
        readiness_conclusion = (
            f"Current route readiness is {readiness_status or 'missing'} with {session_health.get('issue_count', 0)} session-health issue(s); "
            f"{frontdesk_boundary_sentence}"
            "the trusted runner request and no-provider local preflight remain the required next boundary before private role-session acceptance artifacts can be accepted."
        )
    if not media_live_acceptance_required and media_readiness["status"] == "pass":
        media_conclusion = (
            "Media generation readiness passes: the Crown scaffold, ArtifactProducer/Grok binding, OAuth CLI session, non-interactive invocation contract, backend preflight, asset-return contract, and candidate boundary are proven. "
            "Generated-asset quality and cross-shot continuity acceptance are deferred to a future visual node-graph workflow."
        )
        media_gap = None
    elif media_acceptance_complete:
        media_conclusion = (
            "The Crown media-series scaffold, contracts, visual continuity artifacts, ledgers, local Grok CLI entrypoint, and accepted trusted-runner media artifacts prove the internal ArtifactProducer/grok hermes_grok_oauth path. "
            f"{frontdesk_boundary_sentence}"
        )
        media_gap = None
    else:
        media_conclusion = (
            "The Crown media-series scaffold, contracts, visual continuity artifacts, ledgers, Grok preflight, and local Grok CLI entrypoint evidence exist; ArtifactProducer can use the internal hermes_grok_oauth route. "
            + (
                f"The current non-private Grok session smoke is blocked by {grok_session_reason} in this runtime, so media candidate artifacts still need a rerun from a healthy local Grok CLI session."
                if grok_session_blocked
                else "The current non-private Grok session smoke is clean or not the active issue; media candidate artifacts still need to be rerun and returned from that healthy local Grok session."
            )
        )
        media_gap = (
            "Needs a rerun of the internal media live smoke from a healthy local Grok session, followed by returned media artifacts and QC before generated media quality can be accepted."
        )

    requirements = [
        _requirement(
            "position_agentlab_as_strong_code_factory_plus_governed_project_os",
            "AgentLab should remain a strong code system while reusing its memory and lifecycle system for other generative work.",
            "pass"
            if _capability_status(capabilities, "code_factory_orchestration") == "pass"
            and (root / "OPERATING_MODEL.md").exists()
            and (root / "docs" / "AGENTLAB_OPERATING_LOGIC.zh-CN.md").exists()
            else "fail",
            "The operating model and docs position AgentLab as a code factory plus reusable governance/project-OS layer.",
            [
                str(root / "OPERATING_MODEL.md"),
                str(root / "docs" / "AGENTLAB_OPERATING_LOGIC.zh-CN.md"),
                *_capability_evidence(capabilities, "code_factory_orchestration"),
            ],
        ),
        _requirement(
            "route_code_shell_only_to_code_tasks",
            "The brain layer must know when to use the pure code shell and when to use other production/audit/memory lifecycles.",
            "pass"
            if _capability_status(capabilities, "non_code_code_shell_split") == "pass"
            and _capability_status(capabilities, "production_chain_visibility") == "pass"
            else "fail",
            "Representative code, narrative, article, media, and unknown non-code routes are visible and non-code routes do not inherit active code-shell contracts.",
            [
                *_capability_evidence(capabilities, "non_code_code_shell_split", "production_chain_visibility"),
                str(chain_path),
            ],
            details={
                "scenario_ids": sorted(scenarios),
                "production_chain_status": chain.get("status"),
            },
        ),
        _requirement(
            "reuse_state_governance_memory_and_lifecycle_across_domains",
            "State governance, memory storage/read flows, audit flows, creation flows, and lifecycle should be reusable beyond code.",
            "pass" if len(state_scenarios_ok) == len(required_state_scenarios) else "fail",
            "Each representative chain carries lifecycle nodes, memory contract, quality gates, and candidate/promotion artifact intent.",
            [str(chain_path)],
            details={
                "required_scenarios": required_state_scenarios,
                "passing_scenarios": state_scenarios_ok,
            },
        ),
        _requirement(
            "understand_agents_roles_and_chain_responsibilities",
            "The system should clearly understand every agent's responsibility and each task type's complete production chain.",
            "pass"
            if _capability_status(capabilities, "agent_role_chain_consistency") == "pass"
            and len(role.get("roles", [])) >= 13
            and len(role_chains) >= 6
            and role_chain_lifecycle_coverage_pass
            else "fail",
            "Role bindings, boundaries, worker permissions, and representative production chains have machine-readable audit evidence.",
            [
                *_capability_evidence(capabilities, "agent_role_chain_consistency"),
                str(role_path),
            ],
            details={
                "roles": len(role.get("roles", [])) if isinstance(role.get("roles"), list) else 0,
                "workers": len(role.get("workers", [])) if isinstance(role.get("workers"), list) else 0,
                "production_chains": len(role_chains),
                "agent_lifecycle_coverage_pass": role_chain_lifecycle_coverage_pass,
                "lifecycle_coverage_failures": role_chain_lifecycle_failures,
            },
        ),
        _requirement(
            "govern_cli_shell_native_command_surfaces_and_subagents",
            "Local CLI shells should be treated as controllable workflow runtimes: their native commands, subagents, boards, sessions, tools, and receipts must be inventoried before AgentLab relies on them.",
            "pass"
            if _capability_status(capabilities, "cli_workflow_shell_absorption") == "pass"
            and _capability_status(capabilities, "cli_native_command_surface_governance") == "pass"
            else "fail",
            "AgentLab registers shell-native commands, subagents, boards, sessions, and tools for bounded role sessions while preserving lifecycle gates between dependent roles.",
            _capability_evidence(
                capabilities,
                "cli_native_command_surface_governance",
                "cli_workflow_shell_absorption",
            ),
            details={
                "candidate_capability_issues": candidate_issues_for(
                    capability_candidate_issues,
                    ["cli_workflow_shell_absorption", "cli_native_command_surface_governance"],
                )
            },
        ),
        _requirement(
            "self_synthesize_and_gate_new_production_packs",
            "AgentLab should be able to seek resources outward and synthesize new task production packs internally, with promotion gates.",
            "pass"
            if synthesis_scaffold_pass and (not synthesis_role_required or synthesis_role_status == "pass")
            else ("candidate" if synthesis_scaffold_pass and synthesis_role_status == "candidate" else "fail"),
            (
                "Unknown non-code synthesis has a deterministic scheduling scaffold, registry-valid candidate, semantic checks, and promotion gate; provider-backed four-role synthesis acceptance is outside the narrowed goal."
                if not synthesis_role_required
                else (
                    "Unknown non-code synthesis has both a deterministic scheduling scaffold and a complete returned Researcher, ArtifactProducer, and Verifier role-session chain without auto-promotion."
                    if synthesis_role_status == "pass"
                    else "Unknown non-code synthesis has a deterministic scheduling scaffold, while the returned Researcher, ArtifactProducer, and Verifier role-session chain remains incomplete and candidate-only."
                )
            ),
            [
                *_capability_evidence(
                    capabilities,
                    "production_pack_synthesis",
                    "production_pack_synthesis_smoke",
                    "production_pack_synthesis_role_session",
                ),
                str(synthesis_path),
                str(pack_catalog_audit_path),
            ],
            None
            if synthesis_scaffold_pass and (not synthesis_role_required or synthesis_role_status == "pass")
            else "Needs a returned internal Researcher -> ArtifactProducer -> Verifier production-pack synthesis run and role-bound validation receipt.",
            details={
                "acceptance_mode": synthesis_scope,
                "role_session_required": synthesis_role_required,
                "deterministic_scaffold_pass": synthesis_scaffold_pass,
                "role_session_status": synthesis_role_status,
                "role_session_failed_checks": synthesis_role_failed_checks,
                "proposal_valid": synthesis_validation.get("valid"),
                "pack_id": synthesis_validation.get("pack_id"),
                "identity_boundary_status": synthesis_identity_boundary.get("status"),
                "synthesis_shell_pack_id": synthesis_identity_boundary.get("synthesis_shell_pack_id"),
                "validated_candidate_pack_id": synthesis_identity_boundary.get("validated_candidate_pack_id"),
                "validated_candidate_has_governance_contracts": synthesis_identity_boundary.get(
                    "validated_candidate_has_governance_contracts"
                ),
                "semantic_check_count": len(synthesis_semantic_checks),
                "semantic_failures": synthesis_semantic_failures,
                "promotion_attempted": synthesis.get("promotion", {}).get("attempted"),
            },
        ),
        _requirement(
            "test_long_running_code_project_with_agentlab_ui_app",
            "Test long-running code-project ability with AgentLab designing its own web UI/app as a real requirement.",
            "pass"
            if _capability_status(capabilities, "live_code_candidate_materialization") == "pass"
            and _capability_status(capabilities, "code_factory_orchestration") == "pass"
            and ui_api_report.get("status") == "pass"
            and ui_action_ledger_path.exists()
            else (
                "candidate"
                if _capability_status(capabilities, "live_code_candidate_materialization") == "candidate"
                and _capability_status(capabilities, "code_factory_orchestration") == "pass"
                and ui_api_report.get("status") == "pass"
                and ui_action_ledger_path.exists()
                else "fail"
            ),
            (
                "The AgentLab Web UI app was generated as a live run-local code task and promoted to project production with DOM/fetch, operator interaction, run-local API write, headless browser, screenshot, responsive viewport, and archive-governance evidence."
                if _capability_status(capabilities, "live_code_candidate_materialization") == "pass"
                else (
                    "A live run-local AgentLab Web UI candidate exists with DOM/fetch, operator interaction, run-local API write, headless browser, screenshot, and responsive viewport evidence."
                    if _capability_status(capabilities, "live_code_candidate_materialization")
                    == "candidate"
                    else "The legacy AgentLab Web UI probe is retired and supplies no current live candidate evidence."
                )
            ),
            [
                *_capability_evidence(capabilities, "live_code_candidate_materialization", "code_factory_orchestration"),
                *([str(ui_api_report_path)] if ui_api_report_path.is_file() else []),
                *([str(ui_action_ledger_path)] if ui_action_ledger_path.is_file() else []),
            ],
            None
            if _capability_status(capabilities, "live_code_candidate_materialization") == "pass"
            else (
                "Needs explicit promotion before production acceptance."
                if _capability_status(capabilities, "live_code_candidate_materialization")
                == "candidate"
                else "Run a new Runtime v2 code/UI task and collect current immutable acceptance evidence."
            ),
        ),
        _requirement(
            "test_crown_longform_1500_chapter_governance_and_live_generation",
            "Test longform fiction ability for Crown of Ash at roughly 1500-chapter/trilogy scale, including generation as a real requirement.",
            "pass"
            if _capability_status(capabilities, "crown_formal_live_narrative_eval") == "pass"
            and _capability_status(capabilities, "crown_heavy_audit_scale") == "pass"
            and writer_acceptance_complete
            else (
                "candidate"
                if _capability_status(capabilities, "crown_formal_live_narrative_eval") == "candidate"
                else ("blocked" if _capability_status(capabilities, "crown_formal_live_narrative_eval") == "blocked" else "warn")
            ),
            crown_live_conclusion,
            _capability_evidence(
                capabilities,
                "crown_chapter_batch_governance",
                "crown_live_writer_light_path",
                "crown_formal_live_narrative_eval",
                "crown_heavy_audit_scale",
                "trusted_live_runner_request",
                "trusted_live_runner_operator_handoff",
                "trusted_live_runner_preflight",
                "trusted_live_runner_status",
                "trusted_live_runner_collect",
            ),
            crown_live_gap,
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
        _requirement(
            "test_grok_media_series_generation_for_crown",
            "Test video/media generation ability with Grok by turning Crown of Ash into comics, short videos, and poster albums.",
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
            media_conclusion,
            _capability_evidence(
                capabilities,
                "media_series_scaffold",
                "grok_xai_media_backend",
                "trusted_live_runner_request",
                "trusted_live_runner_operator_handoff",
                "trusted_live_runner_preflight",
                "trusted_live_runner_status",
                "trusted_live_runner_collect",
            ),
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
        _requirement(
            "document_complete_logic_and_remaining_unblocks",
            "Once the positioning is clear, record the complete logic and acceptance state.",
            "pass"
            if _capability_status(capabilities, "internal_live_unblock_plan") == "pass"
            and _capability_status(capabilities, "internal_live_readiness") in {"pass", "candidate"}
            and _capability_status(capabilities, "trusted_live_runner_request") == "pass"
            and trusted_writer_request_route_current(trusted_request)
            and _capability_status(capabilities, "trusted_live_runner_operator_handoff") in {"candidate", "pass"}
            and _capability_status(capabilities, "trusted_live_runner_preflight") == "pass"
            and _capability_status(capabilities, "trusted_live_runner_status") in {"candidate", "pass"}
            and _capability_status(capabilities, "trusted_live_runner_collect") in {"candidate", "pass"}
            and goal_path.exists()
            and readiness_path.exists()
            and role_session_handoff_path.exists()
            and legacy_private_live_handoff_path.exists()
            and (root / "docs" / "AGENTLAB_CAPABILITY_ACCEPTANCE_MATRIX.md").exists()
            else "fail",
            "The operating overview, capability matrix, role-session acceptance plan, readiness report, trusted-runner request/preflight/status/collect, report-hygiene audit, and goal audit document the current logic and remaining internal acceptance actions.",
            [
                str(root / "docs" / "AGENTLAB_OPERATING_LOGIC.zh-CN.md"),
                str(root / "docs" / "AGENTLAB_CAPABILITY_ACCEPTANCE_MATRIX.md"),
                str(root / "acceptance_runs" / "agentlab_capability_acceptance" / "live_unblock_plan.yml"),
                str(internal_readiness_path),
                str(legacy_readiness_path),
                *_capability_evidence(
                    capabilities,
                    "trusted_live_runner_request",
                    "trusted_live_runner_operator_handoff",
                    "trusted_live_runner_preflight",
                    "trusted_live_runner_status",
                    "trusted_live_runner_collect",
                ),
                str(report_hygiene_path),
                str(role_session_handoff_path),
                str(legacy_private_live_handoff_path),
                str(goal_path),
            ],
            details={
                "acceptance_report_hygiene_status": report_hygiene.get("status"),
                "writer_request_route_current": trusted_writer_request_route_current(
                    trusted_request
                )
            },
        ),
        _requirement(
            "preserve_candidate_only_and_secret_safety",
            "Generated candidates and external credentials should not silently become production state.",
            "pass"
            if "sk-" not in yaml.safe_dump(acceptance, sort_keys=False, allow_unicode=True)
            and _capability_status(capabilities, "media_series_scaffold") == "pass"
            and _capability_status(capabilities, "crown_live_writer_light_path") == "candidate"
            else "fail",
            "Current reports avoid printing API secrets and candidate paths preserve promotion boundaries for narrative/media outputs.",
            [
                str(acceptance_path),
                str(media_audit_path),
                *_capability_evidence(capabilities, "crown_live_writer_light_path", "media_series_scaffold"),
            ],
        ),
    ]

    _normalize_requirement_evidence(requirements, root)

    for item in requirements:
        if item.get("evidence_health", {}).get("status") == "missing_evidence":
            item["status"] = "fail"
            item["conclusion"] = f"{item['conclusion']} Evidence is incomplete in the current workspace."

    counts: dict[str, int] = {}
    for item in requirements:
        counts[str(item["status"])] = counts.get(str(item["status"]), 0) + 1

    source_reports = {
        "capability_acceptance": str(acceptance_path),
        "production_chain_audit": str(chain_path),
        "agent_role_chain_audit": str(role_path),
        "production_pack_synthesis_smoke": str(synthesis_path),
        "production_pack_role_session_audit": str(synthesis_role_path),
        "pack_catalog_audit": str(pack_catalog_audit_path),
        "goal_completion_audit": str(goal_path),
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
    source_report_health = _evidence_health(list(source_reports.values()))
    if (
        not acceptance_scope.get("valid")
        or source_report_health["status"] != "pass"
        or any(item["status"] == "fail" for item in requirements)
    ):
        status = "fail"
    elif readiness_status == "blocked_external_policy":
        status = "blocked_external_policy"
    elif any(item["status"] == "blocked" for item in requirements):
        status = "blocked_external_input_required"
    elif any(item["status"] in {"candidate", "warn"} for item in requirements):
        status = "partial"
    else:
        status = "complete"

    return {
        "schema_version": 1,
        "report_type": "agentlab_objective_requirement_audit",
        "root": str(root),
        "status": status,
        "status_counts": counts,
        "source_report_health": source_report_health,
        "source_reports": source_reports,
        "objective_scope": "Current narrowed objective: complete code-project and Crown longform acceptance; prove media generation readiness only; defer black-box media artifact acceptance and provider-backed production-pack role-session acceptance.",
        "acceptance_scope": acceptance_scope,
        "requirements": requirements,
        "external_blockers": [],
        "frontdesk_runtime_boundary": frontdesk_runtime_boundary,
        "acceptance_report_hygiene_summary": acceptance_report_hygiene_summary(report_hygiene),
        "role_session_execution_boundary": role_session_execution_boundary(
            trusted_request,
            trusted_operator_handoff,
        ),
        "session_health_summary": _session_health_summary(readiness),
        "active_acceptance_blockers": active_acceptance_blockers(
            session_health=session_health,
            pending_internal_live_smokes=pending_internal_live_smokes,
            frontdesk_runtime_boundary=frontdesk_runtime_boundary,
            required_scopes={"writer"} if not media_live_acceptance_required else {"writer", "media"},
        ),
        "capability_candidate_issues": capability_candidate_issues,
        "pending_internal_live_smokes": pending_internal_live_smokes,
        "deferred_internal_live_smokes": deferred_internal_live_smokes,
        "conclusion": (
            "The architecture, routing, roles, memory/lifecycle reuse, deterministic production-pack scaffold, and local candidate evidence are proven. "
            + (
                "Production-pack synthesis satisfies the current deterministic-scaffold scope; provider-backed four-role acceptance is deferred. "
                if not synthesis_role_required
                else (
                    "Returned production-pack role-session synthesis is also accepted. "
                    if synthesis_role_status == "pass"
                    else "Returned production-pack role-session synthesis remains candidate until ArtifactProducer and Verifier outputs pass transactional materialization and verification. "
                )
            )
            + "Crown Writer acceptance still requires returned artifacts and QC. The Grok media path is accepted only for generation readiness; output quality and continuity are deferred to a visual workflow. "
            + f"{readiness_conclusion} "
            + (
                "The overall objective is complete against the current acceptance contract."
                if status == "complete"
                else "The narrowed objective is partial rather than blocked because refreshed Crown Writer artifacts have not yet been returned and accepted."
            )
        ),
    }


def write_objective_requirement_audit(root: Path, out: Path) -> dict[str, Any]:
    report = build_objective_requirement_audit(root)
    write_report_yaml(out, report, root)
    return report
