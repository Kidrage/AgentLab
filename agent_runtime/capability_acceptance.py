"""Local capability acceptance aggregation for AgentLab.

This module deliberately reads existing evidence only. It does not call model
or media providers, so candidate/live-provider claims stay conservative.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import json
from pathlib import Path
import tempfile
from typing import Any

import yaml


STATUS_RANK = {
    "pass": 0,
    "candidate": 1,
    "warn": 2,
    "blocked": 3,
    "fail": 4,
}

LOCAL_GROK_CLI_ADAPTERS = {"local_grok_cli", "grok_cli_oauth"}


@dataclass(frozen=True)
class ArtifactProbe:
    capability_id: str
    title: str
    project: str
    task_id: str
    expected_status: str = "pass"


ARTIFACT_PROBES = [
    ArtifactProbe(
        capability_id="code_factory_orchestration",
        title="Code factory orchestration",
        project="AgentLab",
        task_id="task_init_shell_code_probe_20260707",
    ),
    ArtifactProbe(
        capability_id="non_code_media_route_contract",
        title="Non-code media route contract",
        project="Crown_of_Ash",
        task_id="task_init_shell_media_probe_20260707",
    ),
    ArtifactProbe(
        capability_id="crown_chapter_batch_governance",
        title="Crown chapter batch governance",
        project="Crown_of_Ash",
        task_id="task_probe_crown_batch_ch01_ch20_20260707",
    ),
]


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _probe_worker_auth(worker_id: str) -> str:
    try:
        from agent_runtime.workers.auth_probe import probe_auth
    except ModuleNotFoundError:
        from workers.auth_probe import probe_auth

    try:
        return probe_auth(worker_id)
    except Exception:
        return "unknown"


def _role_worker_binding_ok(root: Path, role_name: str, worker_id: str) -> bool:
    bindings = _read_yaml(root / "config" / "agent_role_bindings.yml")
    role = ((bindings.get("roles") or {}).get(role_name) or {})
    worker = ((bindings.get("workers") or {}).get(worker_id) or {})
    capabilities = set(worker.get("worker_capabilities") or [])
    has_execution_capability = (
        bool({"candidate_artifact_worker", "role_worker"} & capabilities)
        if role_name in {"ArtifactProducer", "Writer"}
        else "role_worker" in capabilities
    )
    return (
        worker_id in (role.get("allowed_workers") or [])
        and role_name in (worker.get("allowed_roles") or [])
        and has_execution_capability
        and bool(role.get("required_session"))
    )


def _full_cli_role_profile(root: Path, role_key: str) -> dict[str, Any]:
    profiles = _read_yaml(root / "config" / "agent_model_profiles.yml")
    return (
        (((profiles.get("modes") or {}).get("full_cli") or {}).get("tiers") or {})
        .get("full", {})
        .get(role_key, {})
    )


def _model_catalog_entry(root: Path, model_key: str) -> dict[str, Any]:
    catalog = _read_yaml(root / "config" / "model_catalog.yml")
    return ((catalog.get("models") or {}).get(model_key) or {})


def _internal_writer_route_readiness(root: Path) -> dict[str, Any]:
    profile = _full_cli_role_profile(root, "writer")
    model_key = str(profile.get("default") or "")
    model = _model_catalog_entry(root, model_key)
    invocation_contracts = _read_yaml(
        root / "config" / "worker_invocation_contracts.yml"
    )
    contract = (
        (invocation_contracts.get("contracts") or {}).get("claude_writer") or {}
    )
    capacity = _read_yaml(root / "config" / "model_capacity.yml")
    capacity_route = ((capacity.get("routes") or {}).get("Writer") or {})
    binding_ok = _role_worker_binding_ok(root, "Writer", "claude_code")
    profile_ok = (
        profile.get("executor_type") == "cli_agent"
        and profile.get("cli_agent") == "claude_code"
        and profile.get("invocation_contract") == "claude_writer"
        and model_key == "deepseek_v4_pro"
        and profile.get("capacity_route") == "Writer"
    )
    model_ok = (
        model.get("provider") == "deepseek_official"
        and model.get("model_id") == "deepseek-v4-pro"
    )
    contract_ok = (
        contract.get("worker_id") == "claude_code"
        and contract.get("command") == "claude"
        and contract.get("invocation_style") == "sealed_writer_task_packet"
        and {"task_packet_path", "model_id"}.issubset(
            set(contract.get("required_placeholders") or [])
        )
    )
    capacity_ok = (
        capacity_route.get("role") == "writer"
        and capacity_route.get("worker") == "claude_code"
        and capacity_route.get("invocation_contract") == "claude_writer"
        and capacity_route.get("model_key") == "deepseek_v4_pro"
    )
    auth = _probe_worker_auth("claude_code")
    config_ready = binding_ok and profile_ok and model_ok and contract_ok and capacity_ok
    return {
        "ready": config_ready,
        "status": "pass" if config_ready and auth == "yes" else ("candidate" if config_ready else "fail"),
        "role": "Writer",
        "worker": "claude_code",
        "invocation_contract": "claude_writer",
        "capacity_route": "Writer",
        "auth_probe": auth,
        "profile": profile,
        "model_key": model_key,
        "model_provider": model.get("provider"),
        "checks": {
            "role_worker_binding": binding_ok,
            "profile_selects_claude_deepseek_writer": profile_ok,
            "model_registered_as_deepseek": model_ok,
            "claude_writer_contract_is_model_bound": contract_ok,
            "capacity_route_matches_profile": capacity_ok,
        },
    }


def _run_dir(root: Path, project: str, task_id: str) -> Path:
    return root / "projects" / project / "runs" / task_id


def _artifact_probe(root: Path, probe: ArtifactProbe) -> dict[str, Any]:
    try:
        from artifact_contract import validate_artifacts
    except ModuleNotFoundError:
        from agent_runtime.artifact_contract import validate_artifacts

    run_dir = _run_dir(root, probe.project, probe.task_id)
    if not run_dir.exists():
        return {
            "id": probe.capability_id,
            "title": probe.title,
            "status": "fail",
            "evidence": [str(run_dir)],
            "summary": "run directory missing",
            "issues": ["run directory missing"],
        }
    validation = validate_artifacts(run_dir)
    return {
        "id": probe.capability_id,
        "title": probe.title,
        "status": probe.expected_status if validation.get("valid") else "fail",
        "evidence": [
            str(run_dir / "workflow_plan.yml"),
            str(run_dir / "lifecycle.yml"),
            str(run_dir / "artifact_manifest.yml"),
        ],
        "summary": (
            f"artifact pass rate {validation.get('pass_rate')} "
            f"({validation.get('artifacts_passed')}/{validation.get('artifacts_checked')})"
        ),
        "issues": validation.get("issues", []),
    }


def _media_series_scaffold(root: Path) -> dict[str, Any]:
    run_dir = _run_dir(root, "Crown_of_Ash", "task_probe_crown_comic_video_poster_series_scaffold_20260707")
    audit_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "media_series_scaffold_audit.yml"
    audit = _read_yaml(audit_path)
    manifest = _read_yaml(run_dir / "artifact_manifest.yml")
    required = [
        run_dir / "workflow_plan.yml",
        run_dir / "artifact_manifest.yml",
        run_dir / "media_generation_contract.yml",
        run_dir / "prompt_pack.yml",
        run_dir / "asset_registry.yml",
        run_dir / "shot_list.yml",
        run_dir / "generation_ledger.yml",
        run_dir / "media_continuity_ledger.yml",
        run_dir / "media_qc_report.yml",
        run_dir / "narrative_media_delivery_receipt.yml",
    ]
    missing = [str(path) for path in required if not path.exists()]
    audit_passed = audit.get("status") == "pass"
    manifest_passed = manifest.get("valid") is True and manifest.get("pass_rate") == 1.0
    valid = not missing and audit_passed and manifest_passed
    return {
        "id": "media_series_scaffold",
        "title": "Media series production scaffold",
        "status": "pass" if valid else "fail",
        "evidence": [str(path) for path in required] + ([str(audit_path)] if audit_path.exists() else []),
        "summary": (
            "media-series scaffold satisfies active route, production pack, candidate artifact, and safe backend-blocking audit"
            if valid
            else "media-series scaffold evidence missing or audit failing"
        ),
        "issues": missing or ([] if audit_passed and manifest_passed else (audit.get("issues") or ["media-series scaffold audit missing or failing"])),
    }


def _workflow_has_no_code_shell(root: Path) -> dict[str, Any]:
    media_plan = _run_dir(root, "Crown_of_Ash", "task_init_shell_media_probe_20260707") / "workflow_plan.yml"
    code_plan = _run_dir(root, "AgentLab", "task_init_shell_code_probe_20260707") / "workflow_plan.yml"
    media = _read_yaml(media_plan)
    code = _read_yaml(code_plan)
    forbidden = ["implementation_report", "interface_map", "05_coder_prompt", "01_REPO_MAP"]

    def active_contract_text(plan: dict[str, Any]) -> str:
        included_agents = plan.get("included_agents", {}) or {}
        io_items: list[str] = []
        for config in included_agents.values():
            io_items.extend(str(item) for item in config.get("required_inputs", []) or [])
            io_items.extend(str(item) for item in config.get("required_outputs", []) or [])
        task_state = plan.get("memory_policy", {}).get("records", {}).get("task_state", []) or []
        validation_gates = plan.get("validation_gates", []) or []
        return "\n".join(
            io_items
            + [str(item) for item in task_state]
            + [str(item) for item in validation_gates]
        )

    media_text = active_contract_text(media)
    code_text = active_contract_text(code)
    media_hits = [item for item in forbidden if item in media_text]
    code_hits = [item for item in forbidden if item in code_text]
    valid = bool(media and code and not media_hits and code_hits)
    return {
        "id": "non_code_code_shell_split",
        "title": "Non-code tasks do not inherit code shell",
        "status": "pass" if valid else "fail",
        "evidence": [str(media_plan), str(code_plan)],
        "summary": f"media code-shell hits={len(media_hits)}; code probe hits={len(code_hits)}",
        "issues": media_hits or ([] if code_hits else ["code probe did not retain code-shell contract"]),
    }


def _production_pack_synthesis(root: Path) -> dict[str, Any]:
    required = [
        root / "agent_runtime" / "production_packs.py",
        root / "agent_runtime" / "production_pack_registry.py",
        root / "config" / "production_packs.yml",
    ]
    missing = [str(path) for path in required if not path.exists()]
    return {
        "id": "production_pack_synthesis",
        "title": "Production-pack synthesis and promotion gate",
        "status": "pass" if not missing else "fail",
        "evidence": [str(path) for path in required],
        "summary": "synthesis modules and catalog present" if not missing else "required synthesis files missing",
        "issues": missing,
    }


def _production_pack_synthesis_smoke(root: Path) -> dict[str, Any]:
    report_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "production_pack_synthesis_smoke.yml"
    report = _read_yaml(report_path)
    validation = report.get("proposal_validation", {}) if isinstance(report.get("proposal_validation"), dict) else {}
    generated = report.get("generated_artifacts", {}) if isinstance(report.get("generated_artifacts"), dict) else {}
    candidate_pack = (
        report.get("validated_candidate_pack", {})
        if isinstance(report.get("validated_candidate_pack"), dict)
        else {}
    )
    resource_contract = (
        candidate_pack.get("resource_contract", {})
        if isinstance(candidate_pack.get("resource_contract"), dict)
        else {}
    )
    semantic_checks = [
        item for item in report.get("semantic_checks", []) if isinstance(item, dict)
    ]
    semantic_status_by_id = {
        str(item.get("id")): item.get("status")
        for item in semantic_checks
        if item.get("id")
    }
    semantic_failures = [
        str(item.get("id") or "unknown")
        for item in semantic_checks
        if item.get("status") != "pass"
    ]
    required_resource_checks = {
        "research_brief_external_resource_boundary",
        "proposal_resource_contract",
        "proposal_external_resource_boundary",
    }
    resource_boundary_pass = (
        all(semantic_status_by_id.get(check_id) == "pass" for check_id in required_resource_checks)
        and resource_contract.get("external_research_requires_approval") is True
        and resource_contract.get("external_research_may_not_write_project_memory") is True
        and resource_contract.get("evidence_to_memory_promotion_requires_review") is True
        and "resource_evidence_ledger" in set(resource_contract.get("external_research_outputs") or [])
    )
    identity_boundary = (
        report.get("pack_identity_boundary", {})
        if isinstance(report.get("pack_identity_boundary"), dict)
        else {}
    )
    missing = list(generated.get("missing") or [])
    valid = (
        report.get("status") == "pass"
        and validation.get("valid") is True
        and identity_boundary.get("status") == "pass"
        and not semantic_failures
        and resource_boundary_pass
        and not missing
    )
    return {
        "id": "production_pack_synthesis_smoke",
        "title": "Production-pack synthesis candidate artifact smoke",
        "status": "pass" if valid else "fail",
        "evidence": [
            str(report_path),
            str(root / "projects" / "AgentLab" / "runs" / "task_production_pack_synthesis_smoke_20260707" / "production_pack_proposal.yml"),
            str(root / "projects" / "AgentLab" / "runs" / "task_production_pack_synthesis_smoke_20260707" / "domain_memory_contract.yml"),
            str(root / "projects" / "AgentLab" / "runs" / "task_production_pack_synthesis_smoke_20260707" / "lifecycle_profile.yml"),
            str(root / "projects" / "AgentLab" / "runs" / "task_production_pack_synthesis_smoke_20260707" / "domain_research_brief.md"),
        ],
        "summary": (
            f"synthesis smoke status={report.get('status')}; "
            f"proposal_valid={validation.get('valid')}; "
            f"shell={identity_boundary.get('synthesis_shell_pack_id')}; "
            f"candidate_pack={validation.get('pack_id')}; "
            f"external_resource_boundary={resource_boundary_pass}"
        ),
        "details": {
            "evidence_class": "deterministic_scaffold",
            "provider_role_sessions_proven": False,
            "identity_boundary_status": identity_boundary.get("status"),
            "synthesis_shell_pack_id": identity_boundary.get("synthesis_shell_pack_id"),
            "validated_candidate_pack_id": identity_boundary.get("validated_candidate_pack_id"),
            "validated_candidate_has_governance_contracts": identity_boundary.get(
                "validated_candidate_has_governance_contracts"
            ),
            "semantic_check_count": len(semantic_checks),
            "semantic_failures": semantic_failures,
            "external_resource_boundary_pass": resource_boundary_pass,
            "required_resource_semantic_checks": sorted(required_resource_checks),
            "resource_contract": {
                "external_research_requires_approval": resource_contract.get(
                    "external_research_requires_approval"
                ),
                "external_research_may_not_write_project_memory": resource_contract.get(
                    "external_research_may_not_write_project_memory"
                ),
                "evidence_to_memory_promotion_requires_review": resource_contract.get(
                    "evidence_to_memory_promotion_requires_review"
                ),
                "external_research_outputs": resource_contract.get("external_research_outputs") or [],
                "prefer_internal_workers": resource_contract.get("prefer_internal_workers"),
                "new_provider_requires_approval": resource_contract.get("new_provider_requires_approval"),
            },
        },
        "issues": (
            []
            if valid
            else (
                missing
                or semantic_failures
                or validation.get("issues")
                or ["production-pack synthesis smoke missing or failing"]
            )
        ),
    }


def _production_pack_role_session(root: Path) -> dict[str, Any]:
    report_path = (
        root
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / "production_pack_role_session_audit.yml"
    )
    request_path = (
        root
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / "production_pack_role_session_request.yml"
    )
    report = _read_yaml(report_path)
    request = _read_yaml(request_path)
    source_status = str(report.get("status") or "candidate")
    status = source_status if source_status in {"pass", "candidate"} else "fail"
    checks = [item for item in report.get("checks", []) if isinstance(item, dict)]
    failed_checks = [
        str(item.get("id") or "unknown")
        for item in checks
        if item.get("status") != "pass"
    ]
    evidence = [str(report_path), str(request_path)]
    evidence.extend(
        str(path)
        for path in report.get("required_files", []) or []
        if (
            Path(path).exists()
            if Path(path).is_absolute()
            else (root / Path(path)).exists()
        )
    )
    return {
        "id": "production_pack_synthesis_role_session",
        "title": "Production-pack synthesis returned role-session closure",
        "status": status,
        "evidence": evidence,
        "summary": (
            f"role-session audit status={source_status}; "
            f"fresh_run_request={request.get('status')}; "
            f"failed_checks={len(failed_checks)}; "
            f"missing={len(report.get('missing', []) or [])}"
        ),
        "details": {
            "evidence_class": report.get("evidence_class"),
            "provider_calls_executed_by_audit": report.get(
                "provider_calls_executed_by_audit"
            ),
            "failed_checks": failed_checks,
            "missing": list(report.get("missing", []) or []),
            "candidate_only": report.get("candidate_only"),
            "production_modified": report.get("production_modified"),
            "promotion_attempted": report.get("promotion_attempted"),
            "fresh_run_request_status": request.get("status"),
            "fresh_run_target_task_id": request.get("target_task_id"),
            "fresh_run_role_chain": request.get("role_chain") or [],
            "fresh_run_provider_calls_executed": request.get(
                "provider_calls_executed"
            ),
            "fresh_run_silent_fallback_allowed": (
                request.get("context_boundary") or {}
            ).get("silent_provider_fallback_allowed"),
        },
        "issues": (
            []
            if status == "pass"
            else (
                list(report.get("missing", []) or [])
                or failed_checks
                or ["production-pack role-session audit has not returned"]
            )
        ),
    }


def _core_package_import_stability(root: Path) -> dict[str, Any]:
    modules = [
        "agent_runtime.budget_planner",
        "agent_runtime.cli_executor",
        "agent_runtime.model_resolver",
        "agent_runtime.skill_injector",
        "agent_runtime.skill_usage",
        "agent_runtime.state_store",
        "agent_runtime.task_router",
        "agent_runtime.workflow_plan",
    ]
    import_failures: list[str] = []
    for module_name in modules:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            import_failures.append(f"{module_name}: {type(exc).__name__}: {exc}")

    plan_details: dict[str, Any] = {}
    plan_issues: list[str] = []
    if not import_failures:
        try:
            from agent_runtime.workflow_plan import build_workflow_plan

            with tempfile.TemporaryDirectory(prefix="agentlab-core-import-") as tmp:
                request_path = Path(tmp) / "user_request.md"
                request_path.write_text("设计一个 AgentLab 状态总览网页端 UI。", encoding="utf-8")
                plan = build_workflow_plan(
                    root,
                    "AgentLab",
                    "task_core_package_import_acceptance",
                    user_request_path=request_path,
                )
            skills_error = plan.skills.get("error") if isinstance(plan.skills, dict) else "skills not a dict"
            artifact_intent_error = (
                plan.artifact_intent.get("error")
                if isinstance(plan.artifact_intent, dict)
                else "artifact_intent not a dict"
            )
            plan_details = {
                "route_key": plan.route.route_key,
                "agents": list(plan.route.agents),
                "production_pack_id": plan.production_pack.get("pack_id"),
                "skills_error": skills_error,
                "artifact_intent_error": artifact_intent_error,
            }
            if plan.route.route_key != "interface_sensitive_task":
                plan_issues.append(f"unexpected package-mode route: {plan.route.route_key}")
            if plan.production_pack.get("pack_id") != "code_factory":
                plan_issues.append(f"unexpected package-mode production pack: {plan.production_pack.get('pack_id')}")
            if skills_error:
                plan_issues.append(f"skill plan degraded: {skills_error}")
            if artifact_intent_error:
                plan_issues.append(f"artifact intent degraded: {artifact_intent_error}")
        except Exception as exc:
            plan_issues.append(f"workflow_plan package-mode build failed: {type(exc).__name__}: {exc}")

    issues = import_failures + plan_issues
    valid = not issues
    return {
        "id": "core_package_import_stability",
        "title": "Core package import and workflow-plan stability",
        "status": "pass" if valid else "fail",
        "evidence": [
            str(root / "agent_runtime" / "workflow_plan.py"),
            str(root / "agent_runtime" / "task_router.py"),
            str(root / "agent_runtime" / "model_resolver.py"),
            str(root / "agent_runtime" / "skill_injector.py"),
            str(root / "agent_runtime" / "state_store.py"),
            str(root / "tests" / "test_core_package_imports.py"),
            str(root / "tests" / "test_root_import_shims.py"),
        ],
        "summary": (
            "core brain modules import as packages and package-mode workflow plan builds without skill/artifact-intent degradation"
            if valid
            else "core package import or workflow-plan build stability failed"
        ),
        "details": {
            "modules_checked": modules,
            "package_import_failures": import_failures,
            "workflow_plan_probe": plan_details,
        },
        "issues": issues,
    }


def _production_chain_visibility(root: Path) -> dict[str, Any]:
    report_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "production_chain_audit.yml"
    report = _read_yaml(report_path)
    scenarios = report.get("scenarios", []) if isinstance(report.get("scenarios"), list) else []
    status = report.get("status")
    lifecycle_coverage_failures = [
        str(item.get("scenario_id"))
        for item in scenarios
        if isinstance(item, dict)
        and isinstance(item.get("agent_lifecycle_coverage"), dict)
        and item["agent_lifecycle_coverage"].get("status") != "pass"
    ]
    lifecycle_coverage_pass = bool(scenarios) and not lifecycle_coverage_failures
    valid = status == "pass" and len(scenarios) >= 5 and lifecycle_coverage_pass
    return {
        "id": "production_chain_visibility",
        "title": "Production-chain routing and agent-role visibility",
        "status": "pass" if valid else "fail",
        "evidence": [str(report_path)],
        "summary": (
            f"production-chain audit status={status}; scenarios={len(scenarios)}; "
            f"agent_lifecycle_coverage={'pass' if lifecycle_coverage_pass else 'fail'}"
        ),
        "details": {
            "scenario_count": len(scenarios),
            "agent_lifecycle_coverage_pass": lifecycle_coverage_pass,
            "lifecycle_coverage_failures": lifecycle_coverage_failures,
        },
        "issues": [] if valid else (
            lifecycle_coverage_failures or ["production-chain audit missing or failing"]
        ),
    }


def _agent_role_chain_consistency(root: Path) -> dict[str, Any]:
    report_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "agent_role_chain_audit.yml"
    report = _read_yaml(report_path)
    roles = report.get("roles", []) if isinstance(report.get("roles"), list) else []
    chains = report.get("production_chains", []) if isinstance(report.get("production_chains"), list) else []
    workers = report.get("workers", []) if isinstance(report.get("workers"), list) else []
    lifecycle_coverage_failures = [
        str(item.get("scenario_id"))
        for item in chains
        if isinstance(item, dict)
        and isinstance(item.get("agent_lifecycle_coverage"), dict)
        and item["agent_lifecycle_coverage"].get("status") != "pass"
    ]
    lifecycle_coverage_pass = bool(chains) and not lifecycle_coverage_failures
    valid = (
        report.get("status") == "pass"
        and len(roles) >= 13
        and len(chains) >= 6
        and lifecycle_coverage_pass
    )
    return {
        "id": "agent_role_chain_consistency",
        "title": "Agent role responsibilities and chain binding consistency",
        "status": "pass" if valid else "fail",
        "evidence": [str(report_path)],
        "summary": (
            f"role-chain audit status={report.get('status')}; roles={len(roles)}; "
            f"workers={len(workers)}; chains={len(chains)}; "
            f"agent_lifecycle_coverage={'pass' if lifecycle_coverage_pass else 'fail'}"
        ),
        "details": {
            "role_count": len(roles),
            "worker_count": len(workers),
            "production_chain_count": len(chains),
            "agent_lifecycle_coverage_pass": lifecycle_coverage_pass,
            "lifecycle_coverage_failures": lifecycle_coverage_failures,
        },
        "issues": [] if valid else (
            lifecycle_coverage_failures or report.get("issues") or ["agent-role-chain audit missing or failing"]
        ),
    }


def _frontdesk_boundary(root: Path) -> dict[str, Any]:
    report_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "frontdesk_boundary_audit.yml"
    handoff_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "frontdesk_live_handoff.yml"
    report = _read_yaml(report_path)
    handoff = _read_yaml(handoff_path)
    checks = report.get("checks", []) if isinstance(report.get("checks"), list) else []
    check_by_id = {
        str(check.get("id")): check
        for check in checks
        if isinstance(check, dict) and check.get("id")
    }
    status = report.get("status")
    handoff_status = handoff.get("status")
    handoff_valid = handoff_status == "ready_for_agentlab_submission"
    hermes_frontdesk_check = check_by_id.get("hermes_deepseek_v4_pro_is_default_frontdesk", {})
    direct_closed_loop_check = check_by_id.get("direct_closed_loop_does_not_require_frontdesk", {})
    codex_worker_check = check_by_id.get("codex_is_external_worker_not_frontdesk", {})
    workflow_shell_check = check_by_id.get("cli_workflow_shell_registry_covers_hermes_and_claude", {})
    valid = status in {"pass", "warn"} and len(checks) >= 8 and handoff_valid
    return {
        "id": "frontdesk_role_worker_boundary",
        "title": "Frontdesk versus role-worker boundary",
        "status": "warn" if status == "warn" and valid else ("pass" if status == "pass" and valid else "fail"),
        "evidence": [str(report_path), str(handoff_path)],
        "summary": (
            f"frontdesk boundary audit status={status}; checks={len(checks)}; "
            f"live_handoff={handoff_status}; "
            f"hermes_frontdesk={hermes_frontdesk_check.get('status') == 'pass'}; "
            f"direct_closed_loop={direct_closed_loop_check.get('status') == 'pass'}; "
            f"codex_external_worker={codex_worker_check.get('status') == 'pass'}"
        ),
        "details": {
            "hermes_frontdesk_check": hermes_frontdesk_check.get("status"),
            "direct_closed_loop_check": direct_closed_loop_check.get("status"),
            "codex_external_worker_check": codex_worker_check.get("status"),
            "workflow_shell_registry_check": workflow_shell_check.get("status"),
        },
        "issues": []
        if status == "pass" and valid
        else (report.get("issues") or handoff.get("issues") or ["frontdesk boundary audit or live handoff missing/failing"]),
    }


def _cli_workflow_shell_absorption(root: Path) -> dict[str, Any]:
    shell_config_path = root / "config" / "cli_workflow_shells.yml"
    role_bindings_path = root / "config" / "agent_role_bindings.yml"
    invocation_contracts_path = root / "config" / "worker_invocation_contracts.yml"
    media_backends_path = root / "config" / "media_generation_backends.yml"
    profiles_path = root / "config" / "agent_model_profiles.yml"
    shell_config = _read_yaml(shell_config_path)
    role_bindings = _read_yaml(role_bindings_path)
    invocation_contracts = _read_yaml(invocation_contracts_path)
    media_backends = _read_yaml(media_backends_path)
    profiles = _read_yaml(profiles_path)
    boundary = shell_config.get("boundary") if isinstance(shell_config.get("boundary"), dict) else {}
    mode_policy = shell_config.get("mode_policy") if isinstance(shell_config.get("mode_policy"), dict) else {}
    shells = shell_config.get("shells") if isinstance(shell_config.get("shells"), dict) else {}
    families = shell_config.get("capability_families") if isinstance(shell_config.get("capability_families"), dict) else {}
    workers = role_bindings.get("workers") if isinstance(role_bindings.get("workers"), dict) else {}
    contracts = invocation_contracts.get("contracts") if isinstance(invocation_contracts.get("contracts"), dict) else {}
    hermes_grok = ((media_backends.get("backends") or {}).get("hermes_grok_oauth") or {})
    full_cli = (((profiles.get("modes") or {}).get("full_cli") or {}).get("tiers") or {})

    def collect_full_cli_shells(node: Any) -> set[str]:
        found: set[str] = set()
        if isinstance(node, dict):
            cli_agent = node.get("cli_agent")
            if cli_agent:
                found.add(str(cli_agent))
            if node.get("artifact_backend") == "hermes_grok_oauth":
                found.add("grok")
            if node.get("fallback_artifact_backend") == "hermes_grok_oauth":
                found.add("grok")
            for value in node.values():
                found.update(collect_full_cli_shells(value))
        elif isinstance(node, list):
            for value in node:
                found.update(collect_full_cli_shells(value))
        return found

    required_shells = collect_full_cli_shells(full_cli)
    required_families = {
        "one_shot_role_execution",
        "session_and_checkpoint_reuse",
        "tool_and_mcp_governance",
        "skills_plugins_and_bundles",
        "worktree_or_background_execution",
        "structured_output_and_qc",
        "model_auth_and_fallback_governance",
        "permission_and_sandbox_control",
        "workspace_context_control",
    }
    worker_capability_ok = all(
        "workflow_shell" in (((workers.get(worker_id) or {}).get("worker_capabilities")) or [])
        for worker_id in required_shells
    )
    contract_shell_ok = all(
        any(
            isinstance(contract, dict)
            and contract.get("worker_id") == worker_id
            and contract.get("workflow_shell") is True
            for contract in contracts.values()
        )
        for worker_id in required_shells
    )
    media_shell_ok = (
        hermes_grok.get("execution_kernel") == "hermes_workflow_shell"
        and hermes_grok.get("orchestration_scope") == "bounded_role_session_backend"
        and hermes_grok.get("worker_id") == "grok"
        and hermes_grok.get("role_owner") == "ArtifactProducer"
    )
    delivery_contracts_ok = all(
        isinstance(shells.get(worker_id), dict)
        and bool((shells.get(worker_id) or {}).get("common_capabilities"))
        and bool((shells.get(worker_id) or {}).get("unique_capabilities"))
        and bool((shells.get(worker_id) or {}).get("efficiency_gains"))
        and bool((shells.get(worker_id) or {}).get("delivery_contract"))
        and bool((shells.get(worker_id) or {}).get("risk_controls"))
        for worker_id in required_shells
    )
    mode_policy_ok = (
        ((mode_policy.get("full_cli") or {}).get("primary_governance_object") == "cli_shell_capability_and_delivery")
        and ((mode_policy.get("full_cli") or {}).get("own_workflow_shell_scaffold") is False)
        and ((mode_policy.get("full_api") or {}).get("primary_governance_object") == "agentlab_internal_work_shell")
        and ((mode_policy.get("full_api") or {}).get("own_workflow_shell_scaffold") is True)
    )
    boundary_ok = (
        boundary.get("shells_do_not_create_agentlab_roles") is True
        and boundary.get("shell_state_is_not_project_memory") is True
        and boundary.get("shells_must_return_agentlab_receipts") is True
    )
    missing: list[str] = []
    for path in [shell_config_path, role_bindings_path, invocation_contracts_path, media_backends_path, profiles_path]:
        if not path.exists():
            missing.append(str(path))
    if not required_shells:
        missing.append("full_cli mode has no discoverable CLI shells")
    if not required_shells.issubset(set(shells)):
        missing.append("cli_workflow_shells missing one or more full_cli shells")
    if not required_families.issubset(set(families)):
        missing.append("cli_workflow_shells missing required capability families")
    if not worker_capability_ok:
        missing.append("one or more full_cli shell workers do not expose workflow_shell capability")
    if not contract_shell_ok:
        missing.append("one or more full_cli shell invocation contracts do not expose workflow_shell metadata")
    if not delivery_contracts_ok:
        missing.append("one or more full_cli shells lack common/unique/efficiency/delivery/risk governance fields")
    if not mode_policy_ok:
        missing.append("cli workflow shell mode policy does not separate full_cli shell governance from api work-shell construction")
    if not media_shell_ok:
        missing.append("hermes_grok_oauth backend is not bound to hermes_workflow_shell")
    if not boundary_ok:
        missing.append("workflow shell boundary does not preserve AgentLab authority")
    status = "pass" if not missing else "fail"
    return {
        "id": "cli_workflow_shell_absorption",
        "title": "CLI workflow shell capability absorption",
        "status": status,
        "evidence": [
            str(shell_config_path),
            str(role_bindings_path),
            str(invocation_contracts_path),
            str(media_backends_path),
            str(profiles_path),
        ],
        "summary": (
            "Full CLI mode governs native CLI shell capability and delivery contracts instead of rebuilding shell scaffolds; "
            f"families={len(families)}; full_cli_shells={','.join(sorted(required_shells))}; "
            f"media_kernel={hermes_grok.get('execution_kernel') or 'missing'}"
        ),
        "details": {
            "registered_shells": sorted(shells),
            "full_cli_shells": sorted(required_shells),
            "registered_capability_families": sorted(families),
            "agentlab_owns": boundary.get("agentlab_owns") or [],
            "workflow_shell_owns": boundary.get("workflow_shell_owns") or [],
            "worker_capability_ok": worker_capability_ok,
            "contract_shell_ok": contract_shell_ok,
            "delivery_contracts_ok": delivery_contracts_ok,
            "mode_policy_ok": mode_policy_ok,
            "media_shell_ok": media_shell_ok,
            "boundary_ok": boundary_ok,
        },
        "issues": missing,
    }


def _cli_native_command_surface_governance(root: Path) -> dict[str, Any]:
    shell_config_path = root / "config" / "cli_workflow_shells.yml"
    coalescing_plan_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "cli_shell_coalescing_plan.yml"
    shell_config = _read_yaml(shell_config_path)
    coalescing_plan = _read_yaml(coalescing_plan_path)
    policy = (
        shell_config.get("native_command_surface_policy")
        if isinstance(shell_config.get("native_command_surface_policy"), dict)
        else {}
    )
    shells = shell_config.get("shells", {}) if isinstance(shell_config.get("shells"), dict) else {}
    families = (
        shell_config.get("capability_families")
        if isinstance(shell_config.get("capability_families"), dict)
        else {}
    )
    required_families = {
        "native_command_surface_inventory",
        "native_subagent_orchestration",
        "collaboration_board_governance",
    }
    required_surfaces = set(policy.get("required_surfaces") or [])
    native_surface_by_shell = {
        shell_id: shell.get("native_command_surface")
        for shell_id, shell in shells.items()
        if isinstance(shell, dict)
    }
    shells_without_surface = [
        shell_id
        for shell_id, surface in native_surface_by_shell.items()
        if not isinstance(surface, dict) or not surface.get("registered_surfaces")
    ]
    hermes_families = (
        shells.get("hermes", {}).get("command_families", {})
        if isinstance(shells.get("hermes"), dict)
        else {}
    )
    claude_families = (
        shells.get("claude_code", {}).get("command_families", {})
        if isinstance(shells.get("claude_code"), dict)
        else {}
    )
    hermes_kanban_registered = (
        "native_collaboration_surface" in hermes_families
        and any(
            "hermes kanban" in str(example)
            for example in hermes_families.get("native_collaboration_surface", {}).get("examples", [])
        )
    )
    claude_subagents_registered = (
        "agents_and_background" in claude_families
        and any(
            "claude agents" in str(example) or "--agents" in str(example) or "--background" in str(example)
            for example in claude_families.get("agents_and_background", {}).get("examples", [])
        )
    )
    inventory_policy_ok = (
        policy.get("command_inventory_required_before_full_use") is True
        and policy.get("unregistered_native_commands_are_not_available_to_agentlab") is True
        and policy.get("agentlab_memory_remains_authoritative") is True
        and required_surfaces.issuperset(
            {
                "native_subagents_or_background_agents",
                "task_board_or_kanban",
                "sessions_or_checkpoints",
                "tools_mcp_skills_plugins",
                "structured_output_or_receipts",
                "diagnostics_logs_status",
            }
        )
    )
    same_backend_policy_recorded = bool(policy.get("same_backend_multi_role_policy"))
    command_surface_registry_ok = (
        shell_config_path.exists()
        and required_families.issubset(set(families))
        and not shells_without_surface
        and inventory_policy_ok
        and same_backend_policy_recorded
        and hermes_kanban_registered
        and claude_subagents_registered
    )
    materialized_session_packets = (
        coalescing_plan.get("materialized_session_packets")
        if isinstance(coalescing_plan.get("materialized_session_packets"), list)
        else []
    )
    missing_session_packets = (
        coalescing_plan.get("missing_session_packets")
        if isinstance(coalescing_plan.get("missing_session_packets"), list)
        else []
    )
    materialized_packets_exist = bool(materialized_session_packets) and all(
        (root / str(path)).exists() for path in materialized_session_packets
    )
    runtime_coalescing_implemented = (
        coalescing_plan.get("status") == "pass"
        and isinstance(coalescing_plan.get("eligible_group_count"), int)
        and coalescing_plan.get("eligible_group_count") >= 1
        and len(materialized_session_packets) == coalescing_plan.get("eligible_group_count")
        and not missing_session_packets
        and materialized_packets_exist
        and (coalescing_plan.get("policy") or {}).get("per_role_receipts_required") is True
        and (coalescing_plan.get("policy") or {}).get("provider_calls_executed") is False
    )
    issues: list[str] = []
    if not command_surface_registry_ok:
        issues.append("CLI native command-surface registry is incomplete")
    if not runtime_coalescing_implemented:
        issues.append(
            "same-backend multi-role coalescing through one shell session is a governance target, not an implemented scheduler"
        )
    return {
        "id": "cli_native_command_surface_governance",
        "title": "CLI native command surface and subagent governance",
        "status": "pass" if command_surface_registry_ok and runtime_coalescing_implemented else "candidate",
        "evidence": [str(shell_config_path), str(coalescing_plan_path)],
        "summary": (
            "CLI shells have native command-surface inventory policy and registered Hermes/Claude surfaces; "
            f"hermes_kanban_registered={hermes_kanban_registered}; "
            f"claude_subagents_registered={claude_subagents_registered}; "
            f"runtime_coalescing_implemented={runtime_coalescing_implemented}; "
            f"eligible_groups={coalescing_plan.get('eligible_group_count', 0)}"
        ),
        "issues": issues,
        "details": {
            "registered_shells": sorted(shells),
            "required_native_families": sorted(required_families),
            "required_surfaces": sorted(required_surfaces),
            "shells_without_native_surface": sorted(shells_without_surface),
            "inventory_policy_ok": inventory_policy_ok,
            "same_backend_policy_recorded": same_backend_policy_recorded,
            "hermes_kanban_registered": hermes_kanban_registered,
            "claude_subagents_registered": claude_subagents_registered,
            "runtime_coalescing_implemented": runtime_coalescing_implemented,
            "coalescing_plan_status": coalescing_plan.get("status", "missing"),
            "eligible_group_count": coalescing_plan.get("eligible_group_count", 0),
            "materialized_session_packets": materialized_session_packets,
            "missing_session_packets": missing_session_packets,
            "materialized_packets_exist": materialized_packets_exist,
            "provider_calls_executed": (coalescing_plan.get("policy") or {}).get("provider_calls_executed"),
            "target_runtime_shape": (
                "one bounded shell role-session may delegate to shell-native subagents/boards only when each "
                "AgentLab role returns its own receipt and validation evidence"
            ),
        },
    }


def _cli_shell_coalesced_session_returns(root: Path) -> dict[str, Any]:
    status_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "cli_shell_coalescing_status.yml"
    report = _read_yaml(status_path)
    status = report.get("status")
    valid = (
        status == "pass"
        and report.get("secret_values_rendered") is False
        and report.get("provider_calls_executed") is False
        and report.get("missing_returned_files_count") == 0
        and report.get("stale_returned_files_count") == 0
        and report.get("failure_count") == 0
        and report.get("accepted_packet_count") == report.get("expected_packet_count")
        and report.get("accepted_role_count") == report.get("delegated_role_count")
        and report.get("acceptance_scope") == "synthetic_native_surface_smoke"
        and report.get("private_project_context_loaded") is False
        and report.get("returned_shell_sessions_provider_calls_executed") is True
        and (report.get("acceptance_contract") or {}).get("synthetic_input_only") is True
        and (report.get("acceptance_contract") or {}).get("isolated_execution_workspace_required") is True
        and (report.get("acceptance_contract") or {}).get("project_read_tools_allowed") is False
    )
    pending = (
        status == "pending_returned_artifacts"
        and report.get("secret_values_rendered") is False
        and report.get("provider_calls_executed") is False
        and report.get("acceptance_scope") == "synthetic_native_surface_smoke"
        and report.get("private_project_context_loaded") is False
        and isinstance(report.get("missing_returned_files"), list)
    )
    capability_status = "pass" if valid else ("candidate" if pending else "fail")
    return {
        "id": "cli_shell_coalesced_session_returns",
        "title": "CLI coalesced shell session returned artifacts",
        "status": capability_status,
        "evidence": [str(status_path)],
        "summary": (
            f"coalesced shell status={status}; "
            f"accepted_packets={report.get('accepted_packet_count', 0)}/{report.get('expected_packet_count', 0)}; "
            f"accepted_roles={report.get('accepted_role_count', 0)}/{report.get('delegated_role_count', 0)}; "
            f"missing_returned_files={report.get('missing_returned_files_count', 0)}; "
            f"stale_returned_files={report.get('stale_returned_files_count', 0)}; "
            f"failure_count={report.get('failure_count', 0)}"
        ),
        "issues": []
        if valid
        else (
            ["coalesced CLI shell session packets are waiting for returned shell/role receipts and validation evidence"]
            if pending
            else ["coalesced CLI shell returned-artifact status is missing or failing"]
        ),
        "details": {
            "plan_path": report.get("plan_path"),
            "plan_status": report.get("plan_status"),
            "expected_packet_count": report.get("expected_packet_count", 0),
            "accepted_packet_count": report.get("accepted_packet_count", 0),
            "delegated_role_count": report.get("delegated_role_count", 0),
            "accepted_role_count": report.get("accepted_role_count", 0),
            "missing_returned_files_count": report.get("missing_returned_files_count", 0),
            "missing_returned_files": report.get("missing_returned_files", []),
            "stale_returned_files_count": report.get("stale_returned_files_count", 0),
            "stale_returned_files": report.get("stale_returned_files", []),
            "failure_count": report.get("failure_count", 0),
            "next_action": report.get("next_action"),
            "acceptance_scope": report.get("acceptance_scope"),
            "private_project_context_loaded": report.get("private_project_context_loaded"),
            "returned_shell_sessions_provider_calls_executed": report.get(
                "returned_shell_sessions_provider_calls_executed"
            ),
        },
    }


def _cli_shell_coalesced_runner_request(root: Path) -> dict[str, Any]:
    request_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "cli_shell_coalescing_runner_request.yml"
    report = _read_yaml(request_path)
    package = report.get("local_runner_package") if isinstance(report.get("local_runner_package"), dict) else {}
    boundary = report.get("runner_boundary") if isinstance(report.get("runner_boundary"), dict) else {}
    status_summary = report.get("status_summary") if isinstance(report.get("status_summary"), dict) else {}
    packets = report.get("packets") if isinstance(report.get("packets"), list) else []
    valid = (
        report.get("status") in {"ready_for_trusted_runner", "accepted"}
        and request_path.exists()
        and boundary.get("frontdesk_agent_executes_shell_sessions") is False
        and boundary.get("trusted_shell_runner_required") is True
        and boundary.get("provider_calls_executed_by_request_generation") is False
        and boundary.get("shell_state_counts_as_project_memory") is False
        and boundary.get("production_promotion_allowed") is False
        and boundary.get("acceptance_scope") == "synthetic_native_surface_smoke"
        and boundary.get("private_project_context_loaded") is False
        and boundary.get("isolated_execution_workspace_required") is True
        and boundary.get("project_read_tools_allowed") is False
        and package.get("must_return_one_shell_receipt_per_packet") is True
        and package.get("must_return_one_role_receipt_per_delegated_role") is True
        and package.get("must_return_validation_evidence_per_delegated_role") is True
        and package.get("full_run_requires_coalescing_status_pass") is True
        and "cli-shell-coalescing-runner" in str(package.get("dry_run_command") or "")
        and "AGENTLAB_TRUSTED_CLI_SHELL_RUNNER=1" in str(package.get("execute_command") or "")
        and "--execute" in str(package.get("execute_command") or "")
        and "cli-shell-coalescing-collect" in str(package.get("post_run_collect_command") or "")
        and "cli-shell-coalescing-status" in str(package.get("status_command") or "")
        and len(packets) == status_summary.get("packet_count")
        and report.get("secret_values_rendered") is False
    )
    return {
        "id": "cli_shell_coalesced_runner_request",
        "title": "CLI coalesced shell trusted-runner request",
        "status": "pass" if valid else "fail",
        "evidence": [str(request_path)],
        "summary": (
            f"coalesced shell runner request status={report.get('status')}; "
            f"packets={len(packets)}; "
            f"missing_returned_files={status_summary.get('missing_returned_files_count', 0)}; "
            f"frontdesk_executes={boundary.get('frontdesk_agent_executes_shell_sessions')}"
        ),
        "issues": [] if valid else ["coalesced CLI shell runner request missing, unsafe, or incomplete"],
        "details": {
            "packet_count": len(packets),
            "expected_packet_count": status_summary.get("expected_packet_count", 0),
            "missing_returned_files_count": status_summary.get("missing_returned_files_count", 0),
            "status_command": package.get("status_command"),
            "dry_run_command": package.get("dry_run_command"),
            "execute_command": package.get("execute_command"),
            "post_run_collect_command": package.get("post_run_collect_command"),
            "next_action": report.get("next_action"),
            "acceptance_scope": boundary.get("acceptance_scope"),
            "private_project_context_loaded": boundary.get("private_project_context_loaded"),
        },
    }


def _cli_shell_coalesced_runner_implementation(root: Path) -> dict[str, Any]:
    runner_path = root / "agent_runtime" / "cli_shell_coalescing_runner.py"
    result_path = (
        root / "acceptance_runs" / "agentlab_capability_acceptance" / "cli_shell_coalescing_runner_result.yml"
    )
    report = _read_yaml(result_path)
    backend_results = report.get("backend_results") if isinstance(report.get("backend_results"), list) else []
    by_backend = {
        str(item.get("backend")): item
        for item in backend_results
        if isinstance(item, dict) and item.get("backend")
    }
    expected_surfaces = {
        "claude_code": "claude_inline_agents",
        "hermes": "hermes_kanban",
    }
    valid = (
        runner_path.is_file()
        and result_path.is_file()
        and report.get("status") == "ready_for_trusted_runner"
        and report.get("execute_requested") is False
        and report.get("provider_calls_executed") is False
        and report.get("secret_values_rendered") is False
        and report.get("acceptance_scope") == "synthetic_native_surface_smoke"
        and report.get("private_project_context_loaded") is False
        and report.get("isolated_execution_workspace_required") is True
        and report.get("project_read_tools_allowed") is False
        and set(by_backend) == set(expected_surfaces)
        and all(by_backend[key].get("status") == "planned" for key in expected_surfaces)
        and all(
            by_backend[key].get("native_surface_used") == surface
            for key, surface in expected_surfaces.items()
        )
        and all(isinstance(by_backend[key].get("command_preview"), dict) for key in expected_surfaces)
    )
    return {
        "id": "cli_shell_coalesced_runner_implementation",
        "title": "CLI coalesced shell trusted-runner implementation",
        "status": "pass" if valid else "fail",
        "evidence": [str(runner_path), str(result_path)],
        "summary": (
            f"runner dry-run status={report.get('status')}; "
            f"execute_requested={report.get('execute_requested')}; "
            f"provider_calls_executed={report.get('provider_calls_executed')}; "
            f"backends={','.join(sorted(by_backend))}"
        ),
        "issues": [] if valid else ["coalesced CLI shell trusted runner is missing or its dry-run contract failed"],
        "details": {
            "runner_path": str(runner_path),
            "result_path": str(result_path),
            "backend_statuses": {key: item.get("status") for key, item in by_backend.items()},
            "native_surfaces": {key: item.get("native_surface_used") for key, item in by_backend.items()},
            "execute_requested": report.get("execute_requested"),
            "provider_calls_executed": report.get("provider_calls_executed"),
            "next_action": report.get("next_action"),
            "acceptance_scope": report.get("acceptance_scope"),
            "private_project_context_loaded": report.get("private_project_context_loaded"),
        },
    }


def _cli_shell_coalesced_collect(root: Path) -> dict[str, Any]:
    collect_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "cli_shell_coalescing_collect.yml"
    report = _read_yaml(collect_path)
    refreshed = report.get("refreshed_reports") if isinstance(report.get("refreshed_reports"), dict) else {}
    coalescing_status = (
        report.get("coalescing_status") if isinstance(report.get("coalescing_status"), dict) else {}
    )
    acceptance_refresh = (
        report.get("acceptance_refresh") if isinstance(report.get("acceptance_refresh"), dict) else {}
    )
    source_hashes = report.get("source_report_sha256") if isinstance(report.get("source_report_sha256"), dict) else {}
    required_refreshed = {
        "cli_shell_coalescing_status",
        "cli_shell_coalescing_runner_request",
        "capability_acceptance",
        "objective_requirement_audit",
        "goal_completion_audit",
        "acceptance_report_hygiene",
    }
    source_reports = {
        "cli_shell_coalescing_status": root / str(refreshed.get("cli_shell_coalescing_status") or ""),
        "cli_shell_coalescing_runner_request": root
        / str(refreshed.get("cli_shell_coalescing_runner_request") or ""),
    }
    expected_source_types = {
        "cli_shell_coalescing_status": "agentlab_cli_shell_coalescing_status",
        "cli_shell_coalescing_runner_request": "agentlab_cli_shell_coalescing_runner_request",
    }
    source_report_types = {
        key: (_read_yaml(path).get("report_type") if path.is_file() else None)
        for key, path in source_reports.items()
    }
    source_hash_matches = {}
    for key, path in source_reports.items():
        if not path.is_file():
            source_hash_matches[key] = False
            continue
        import hashlib

        source_hash_matches[key] = hashlib.sha256(path.read_bytes()).hexdigest() == source_hashes.get(key)
    valid = (
        report.get("status") in {"pending_returned_artifacts", "pass"}
        and collect_path.exists()
        and report.get("provider_calls_executed") is False
        and report.get("secret_values_rendered") is False
        and required_refreshed.issubset(refreshed)
        and acceptance_refresh.get("performed") is True
        and coalescing_status.get("status") in {"pending_returned_artifacts", "pass"}
        and report.get("runner_request_status") in {"ready_for_trusted_runner", "accepted"}
        and source_report_types == expected_source_types
        and all(source_hash_matches.values())
    )
    return {
        "id": "cli_shell_coalesced_collect",
        "title": "CLI coalesced shell returned-artifact collector",
        "status": "pass" if valid else "fail",
        "evidence": [str(collect_path)],
        "summary": (
            f"coalesced shell collect status={report.get('status')}; "
            f"receipt_status={coalescing_status.get('status')}; "
            f"refreshed_reports={len(refreshed)}; "
            f"provider_calls_executed={report.get('provider_calls_executed')}"
        ),
        "issues": [] if valid else ["coalesced CLI shell collector is missing, unsafe, or incomplete"],
        "details": {
            "collect_status": report.get("status"),
            "coalescing_status": coalescing_status.get("status"),
            "runner_request_status": report.get("runner_request_status"),
            "refreshed_reports": refreshed,
            "acceptance_refresh": acceptance_refresh,
            "source_report_types": source_report_types,
            "source_hash_matches": source_hash_matches,
            "missing_returned_files_count": coalescing_status.get("missing_returned_files_count", 0),
            "failure_count": coalescing_status.get("failure_count", 0),
            "provider_calls_executed": report.get("provider_calls_executed"),
            "next_action": report.get("next_action"),
        },
    }


def _live_code_promotion(root: Path, run_dir: Path) -> dict[str, Any]:
    project = "AgentLab"
    task_id = "task_live_code_ui_app_json_binding_20260707"
    project_root = root / "projects" / project
    production_required = [
        project_root / "artifacts" / "web_ui" / "index.html",
        project_root / "artifacts" / "web_ui" / "styles.css",
        project_root / "artifacts" / "web_ui" / "app.js",
        project_root / "artifacts" / "web_ui" / "status.sample.json",
    ]
    receipt_path = run_dir / "archive_receipt.yml"
    plan_path = run_dir / "artifact_promotion_plan.yml"
    index_path = project_root / "project_artifact_index.yml"
    receipt = _read_yaml(receipt_path)
    missing_production = [str(path) for path in production_required if not path.exists()]
    governance_issues: list[str] = []
    try:
        from agent_runtime.project_artifact_steward import validate_project_artifact_governance
    except ModuleNotFoundError:
        from project_artifact_steward import validate_project_artifact_governance

    try:
        governance_issues = validate_project_artifact_governance(root, project, task_id)
    except Exception as exc:
        governance_issues = [f"artifact governance validation failed: {exc}"]

    receipt_completed = (
        receipt_path.exists()
        and receipt.get("status") == "completed"
        and not receipt.get("errors")
        and bool(receipt.get("promotions_applied"))
    )
    passed = receipt_completed and not missing_production and not governance_issues
    evidence = [str(path) for path in production_required]
    for path in (plan_path, receipt_path, index_path):
        if path.exists():
            evidence.append(str(path))
    issues = []
    if not receipt_completed:
        issues.append("production promotion receipt missing, incomplete, or empty")
    issues.extend(missing_production)
    issues.extend(governance_issues)
    return {
        "passed": passed,
        "evidence": evidence,
        "issues": issues,
    }


def _live_code_candidate(root: Path) -> dict[str, Any]:
    run_dir = _run_dir(root, "AgentLab", "task_live_code_ui_app_json_binding_20260707")
    required = [
        run_dir / "artifacts" / "web_ui" / "index.html",
        run_dir / "artifacts" / "web_ui" / "styles.css",
        run_dir / "artifacts" / "web_ui" / "app.js",
        run_dir / "artifacts" / "web_ui" / "status.sample.json",
    ]
    smoke_report = run_dir / "ui_candidate_smoke_report.json"
    browser_report = run_dir / "ui_browser_smoke_report.json"
    interaction_report = run_dir / "ui_interaction_smoke_report.json"
    api_report = run_dir / "ui_api_smoke_report.json"
    action_ledger = run_dir / "ui_action_ledger.json"
    visual_report = run_dir / "ui_visual_smoke_report.json"
    visual_screenshot = run_dir / "ui_visual_smoke.png"
    responsive_report = run_dir / "ui_responsive_smoke_report.json"
    responsive_desktop = run_dir / "ui_responsive_desktop.png"
    responsive_mobile = run_dir / "ui_responsive_mobile.png"
    missing = [str(path) for path in required if not path.exists()]
    smoke = {}
    if smoke_report.exists():
        try:
            smoke = json.loads(smoke_report.read_text(encoding="utf-8"))
        except Exception:
            smoke = {"status": "fail", "error": "unreadable smoke report"}
    browser = {}
    if browser_report.exists():
        try:
            browser = json.loads(browser_report.read_text(encoding="utf-8"))
        except Exception:
            browser = {"status": "fail", "error": "unreadable browser smoke report"}
    interaction = {}
    if interaction_report.exists():
        try:
            interaction = json.loads(interaction_report.read_text(encoding="utf-8"))
        except Exception:
            interaction = {"status": "fail", "error": "unreadable interaction smoke report"}
    api = {}
    if api_report.exists():
        try:
            api = json.loads(api_report.read_text(encoding="utf-8"))
        except Exception:
            api = {"status": "fail", "error": "unreadable api smoke report"}
    visual = {}
    if visual_report.exists():
        try:
            visual = json.loads(visual_report.read_text(encoding="utf-8"))
        except Exception:
            visual = {"status": "fail", "error": "unreadable visual smoke report"}
    responsive = {}
    if responsive_report.exists():
        try:
            responsive = json.loads(responsive_report.read_text(encoding="utf-8"))
        except Exception:
            responsive = {"status": "fail", "error": "unreadable responsive smoke report"}
    smoke_passed = smoke.get("status") == "pass"
    browser_passed = browser.get("status") == "pass"
    interaction_passed = interaction.get("status") == "pass"
    api_passed = api.get("status") == "pass" and action_ledger.exists()
    visual_passed = visual.get("status") == "pass" and visual_screenshot.exists()
    responsive_passed = (
        responsive.get("status") == "pass"
        and responsive_desktop.exists()
        and responsive_mobile.exists()
    )
    run_local_passed = (
        smoke_passed
        and browser_passed
        and interaction_passed
        and api_passed
        and visual_passed
        and responsive_passed
    )
    promotion = _live_code_promotion(root, run_dir)
    status = "pass" if not missing and run_local_passed and promotion["passed"] else ("candidate" if not missing else "fail")
    evidence = [str(path) for path in required]
    if smoke_report.exists():
        evidence.append(str(smoke_report))
    if browser_report.exists():
        evidence.append(str(browser_report))
    if interaction_report.exists():
        evidence.append(str(interaction_report))
    if api_report.exists():
        evidence.append(str(api_report))
    if action_ledger.exists():
        evidence.append(str(action_ledger))
    if visual_report.exists():
        evidence.append(str(visual_report))
    if visual_screenshot.exists():
        evidence.append(str(visual_screenshot))
    if responsive_report.exists():
        evidence.append(str(responsive_report))
    if responsive_desktop.exists():
        evidence.append(str(responsive_desktop))
    if responsive_mobile.exists():
        evidence.append(str(responsive_mobile))
    evidence.extend(promotion["evidence"])
    return {
        "id": "live_code_candidate_materialization",
        "title": "Live code candidate materialization",
        "status": status,
        "evidence": evidence,
        "summary": (
            "web UI artifacts promoted to production with DOM/fetch, headless-browser, operator interaction, run-local API write, screenshot pixel, responsive viewport, and archive-governance evidence"
            if status == "pass"
            else
            "run-local web UI candidate artifacts present with DOM/fetch, headless-browser, screenshot pixel, and responsive viewport evidence"
            if not missing and smoke_passed and browser_passed and visual_passed and responsive_passed and not interaction_passed
            else "run-local web UI candidate artifacts present with DOM/fetch, headless-browser, operator interaction, run-local API write, screenshot pixel, and responsive viewport evidence"
            if not missing and smoke_passed and browser_passed and interaction_passed and api_passed and visual_passed and responsive_passed
            else "run-local web UI candidate artifacts present with DOM/fetch, headless-browser, operator interaction, screenshot pixel, and responsive viewport evidence"
            if not missing and smoke_passed and browser_passed and interaction_passed and visual_passed and responsive_passed
            else "run-local web UI candidate artifacts present with DOM/fetch, headless-browser, and screenshot pixel evidence"
            if not missing and smoke_passed and browser_passed and visual_passed
            else "run-local web UI candidate artifacts present with DOM/fetch and headless-browser evidence"
            if not missing and smoke_passed and browser_passed
            else "run-local web UI candidate artifacts present with DOM/fetch smoke evidence"
            if not missing and smoke_passed
            else ("run-local web UI candidate artifacts present" if not missing else "candidate artifacts missing")
        ),
        "issues": (
            missing
            if missing
            else (
                []
                if run_local_passed and promotion["passed"]
                else [
                    issue
                    for issue, passed in [
                        ("DOM/fetch smoke report missing or not passing", smoke_passed),
                        ("headless browser smoke report missing or not passing", browser_passed),
                        ("operator interaction smoke report missing or not passing", interaction_passed),
                        ("run-local API write smoke report missing or not passing", api_passed),
                        ("visual screenshot smoke report missing or not passing", visual_passed),
                        ("responsive viewport smoke report missing or not passing", responsive_passed),
                    ]
                    if not passed
                ] + ([] if promotion["passed"] else promotion["issues"])
            )
        ),
    }


def _crown_live_writer(root: Path) -> dict[str, Any]:
    run_dir = _run_dir(root, "Crown_of_Ash", "task_narrative_eval_ch01_live_ch01_20260707_cli_fallback")
    audit_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "crown_live_candidate_audit.yml"
    required = [
        run_dir / "fiction_draft.md",
        run_dir / "continuity_ledger.yml",
        run_dir / "state_transition_proposal.yml",
        run_dir / "narrative_delivery_receipt.yml",
    ]
    missing = [str(path) for path in required if not path.exists()]
    audit = _read_yaml(audit_path)
    audit_passed = audit.get("status") == "pass"
    candidate_ready = not missing and audit_passed
    return {
        "id": "crown_live_writer_light_path",
        "title": "Crown live Writer light path",
        "status": "candidate" if candidate_ready else "fail",
        "evidence": [str(path) for path in required] + ([str(audit_path)] if audit_path.exists() else []),
        "summary": (
            "one live chapter candidate satisfies delivery contract and local candidate audit"
            if candidate_ready
            else "live writer evidence missing or local candidate audit failing"
        ),
        "issues": (
            ["run-local chapter candidate is not formal trusted-runner live acceptance or production promotion"]
            if candidate_ready
            else missing or (audit.get("issues") or ["crown live candidate audit missing or failing"])
        ),
        "details": {
            "candidate_only": candidate_ready,
            "local_candidate_audit_passed": audit_passed,
            "formal_trusted_runner_acceptance_required": candidate_ready,
            "production_promotion_attempted": False,
        },
    }


def _trusted_runner_item(root: Path, item_id: str) -> tuple[dict[str, Any], Path]:
    status_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_status.yml"
    report = _read_yaml(status_path)
    items = report.get("items", []) if isinstance(report.get("items"), list) else []
    item = next(
        (candidate for candidate in items if isinstance(candidate, dict) and candidate.get("id") == item_id),
        {},
    )
    return item, status_path


def _trusted_runner_item_accepted(root: Path, item_id: str) -> tuple[bool, dict[str, Any], Path]:
    item, status_path = _trusted_runner_item(root, item_id)
    accepted = item.get("status") == "pass" and item.get("returned_candidate_artifacts_accepted") is True
    return accepted, item, status_path


def _crown_formal_live_eval(root: Path) -> dict[str, Any]:
    eval_dir = (
        root
        / "acceptance_runs"
        / "narrative_eval"
        / "Crown_of_Ash"
        / "crown_live_single_chapter_probe_20260707"
        / "live_ch01_retry_20260707_1118"
    )
    run_dir = _run_dir(root, "Crown_of_Ash", "task_narrative_eval_ch01_live_ch01_retry_20260707_1118")
    report_path = eval_dir / "longform_eval_report.yml"
    policy_note = eval_dir / "external_retry_policy_note.yml"
    error_path = run_dir / "live_generation_error.yml"
    report = _read_yaml(report_path)
    error = _read_yaml(error_path)
    missing = [str(path) for path in [report_path, error_path] if not path.exists()]
    blocked = report.get("status") == "fail" and error.get("status") == "blocked"
    writer_route = _internal_writer_route_readiness(root)
    provider = error.get("provider", "unknown")
    model = error.get("model", "unknown")
    error_text = error.get("error", "unknown")
    internal_ready = bool(writer_route.get("ready"))
    trusted_accepted, trusted_item, trusted_status_path = _trusted_runner_item_accepted(
        root,
        "run_crown_internal_writer_eval",
    )
    status = "pass" if internal_ready and trusted_accepted else ("candidate" if internal_ready else ("blocked" if blocked and not missing else "fail"))
    if internal_ready and trusted_accepted:
        summary = (
            "formal live one-chapter eval returned accepted trusted-runner Writer artifacts "
            "through the internal Writer role-session: Claude shell + DeepSeek V4 Pro"
        )
        issues: list[str] = []
    elif internal_ready:
        summary = (
            "formal live one-chapter eval is routed through the internal Writer role-session: "
            "Claude shell + DeepSeek V4 Pro; route auth probe status="
            f"{writer_route.get('auth_probe') or 'unknown'}; previous blocked provider "
            "evidence is historical"
        )
        issues = ["refreshed internal Writer role-session acceptance artifacts have not been returned or accepted yet"]
    elif not missing:
        summary = f"formal live one-chapter eval blocked at Writer provider call: {provider}/{model}: {error_text}"
        issues = ["Writer internal route is not fully configured or authenticated"]
    else:
        summary = "formal live eval evidence missing"
        issues = missing
    return {
        "id": "crown_formal_live_narrative_eval",
        "title": "Crown formal live narrative-eval harness",
        "status": status,
        "evidence": [
            str(report_path),
            str(error_path),
            str(policy_note),
            str(run_dir / "provider_incidents.yml"),
            str(run_dir / "USER_DECISION_REQUIRED.md"),
            str(root / "config" / "agent_model_profiles.yml"),
            str(root / "config" / "agent_role_bindings.yml"),
            str(root / "config" / "model_catalog.yml"),
            str(root / "config" / "worker_invocation_contracts.yml"),
            str(root / "config" / "model_capacity.yml"),
            str(trusted_status_path),
        ],
        "summary": summary,
        "issues": issues,
        "details": {
            "internal_writer_route": writer_route,
            "returned_artifacts_pending": internal_ready and not trusted_accepted,
            "returned_artifacts_accepted": trusted_accepted,
            "trusted_runner_item": "run_crown_internal_writer_eval" if internal_ready else None,
            "trusted_runner_item_status": trusted_item.get("status"),
            "trusted_runner_item_acceptance_blocker": trusted_item.get("acceptance_blocker"),
            "historical_provider_block": {
                "blocked": blocked,
                "provider": provider,
                "model": model,
                "error": error_text,
            },
            "writer_route_health": {
                "status": writer_route.get("status"),
                "auth_probe": writer_route.get("auth_probe"),
                "worker": writer_route.get("worker"),
                "invocation_contract": writer_route.get("invocation_contract"),
                "model_key": writer_route.get("model_key"),
            },
        },
    }


def _narrative_heavy_scale(root: Path) -> dict[str, Any]:
    mock_dir = (
        root
        / "acceptance_runs"
        / "narrative_eval"
        / "Crown_of_Ash"
        / "crown_mock_chain_receipt_contract_20260707"
        / "mock_chain_receipt_contract_ch01_ch03_20260707"
    )
    scale_dir = (
        root
        / "acceptance_runs"
        / "narrative_eval"
        / "Crown_of_Ash"
        / "crown_scale_probe_20260707"
        / "crown_scale_1500_20260707"
    )
    required = [
        mock_dir / "longform_eval_report.yml",
        mock_dir / "continuity_failure_report.yml",
        scale_dir / "series_scale_simulation.yml",
        root / "acceptance_runs" / "agentlab_capability_acceptance" / "crown_scale_governance_audit.yml",
    ]
    missing = [str(path) for path in required if not path.exists()]
    scale_audit = _read_yaml(required[-1])
    scale_passed = scale_audit.get("status") == "pass"
    valid = not missing and scale_passed
    return {
        "id": "crown_heavy_audit_scale",
        "title": "Crown heavy audit and 1500-chapter scale governance",
        "status": "pass" if valid else "fail",
        "evidence": [str(path) for path in required],
        "summary": (
            "1500-chapter governance-scale audit passes; scope is governance ledgers, not generated prose quality"
            if valid
            else "scale-governance evidence missing or audit failing"
        ),
        "issues": missing or ([] if scale_passed else (scale_audit.get("missing") or ["crown scale governance audit missing or failing"])),
    }


def _grok_media_backend(root: Path) -> dict[str, Any]:
    adapter = root / "agent_runtime" / "media_backend_adapter.py"
    media_backend_config_path = root / "config" / "media_generation_backends.yml"
    role_bindings = root / "config" / "agent_role_bindings.yml"
    invocation_contracts_path = root / "config" / "worker_invocation_contracts.yml"
    current_preflight = root / "acceptance_runs" / "agentlab_capability_acceptance" / "grok_media_preflight_current.yml"
    historical_cli_smoke = root / "acceptance_runs" / "agentlab_capability_acceptance" / "grok_oauth_cli_smoke.yml"
    session_smoke_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "grok_cli_session_smoke.yml"
    preflight = (
        _run_dir(root, "Crown_of_Ash", "task_probe_crown_comic_video_poster_series_scaffold_20260707")
        / "artifacts"
        / "media_backend_live_smoke_20260707"
        / "media_backend_preflight.yml"
    )
    report = _read_yaml(current_preflight) or _read_yaml(preflight)
    media_backend_config = _read_yaml(media_backend_config_path)
    invocation_contracts = _read_yaml(invocation_contracts_path)
    smoke = _read_yaml(historical_cli_smoke)
    session_smoke = _read_yaml(session_smoke_path)
    missing = [
        str(path)
        for path in [
            adapter,
            media_backend_config_path,
            role_bindings,
            invocation_contracts_path,
            current_preflight,
            historical_cli_smoke,
            session_smoke_path,
        ]
        if not path.exists()
    ]
    block_reason = report.get("block_reason") or report.get("execution_blocker", {}).get("reason")
    backend = report.get("backend") if isinstance(report.get("backend"), dict) else {}
    configured_backend = (
        ((media_backend_config.get("backends") or {}).get(str(report.get("backend_id") or "")) or {})
        if isinstance(media_backend_config.get("backends"), dict)
        else {}
    )
    if isinstance(configured_backend, dict):
        backend = {**backend, **configured_backend}
    worker_id = str(backend.get("worker_id") or "")
    role_owner = str(backend.get("role_owner") or "")
    artifact_worker_binding_ready = (
        worker_id == "grok"
        and role_owner == "ArtifactProducer"
        and backend.get("internal_worker") is True
        and _role_worker_binding_ok(root, "ArtifactProducer", "grok")
    )
    researcher_worker_binding_ready = _role_worker_binding_ok(
        root,
        "Researcher",
        "grok",
    )
    contracts = invocation_contracts.get("contracts") or {}
    grok_research_contract = contracts.get("grok_research") or {}
    grok_media_contract = contracts.get("grok_media") or {}
    backend_command = str(backend.get("command") or "")
    research_contract_command = str(grok_research_contract.get("command") or "")
    media_contract_command = str(grok_media_contract.get("command") or "")
    grok_research_contract_ready = (
        grok_research_contract.get("worker_id") == "grok"
        and research_contract_command == "hermes"
        and grok_research_contract.get("invocation_style") == "sourced_research_task_packet"
    )
    grok_media_contract_ready = (
        grok_media_contract.get("worker_id") == "grok"
        and media_contract_command == backend_command == "hermes"
        and grok_media_contract.get("invocation_style") == "media_backend_task_packet"
    )
    invocation_contract_ready = (
        grok_research_contract_ready and grok_media_contract_ready
    )
    local_cli_ready = (
        report.get("status") == "ready"
        and report.get("backend_id") == "hermes_grok_oauth"
        and report.get("adapter_kind") in LOCAL_GROK_CLI_ADAPTERS
        and smoke.get("status") == "pass"
    )
    approval_required = bool((report.get("backend") or {}).get("approval_required", report.get("approval_required", False)))
    internal_worker_ready = (
        local_cli_ready
        and not approval_required
        and researcher_worker_binding_ready
        and artifact_worker_binding_ready
        and invocation_contract_ready
    )
    session_status = session_smoke.get("status")
    session_reason = session_smoke.get("reason")
    local_cli_entrypoint_available = session_smoke.get(
        "local_cli_entrypoint_available",
        session_smoke.get("cli_entrypoint_available"),
    )
    local_cli_entrypoint_is_internal_worker = session_smoke.get(
        "local_cli_entrypoint_is_internal_worker",
        session_smoke.get("execution_scope") == "internal_local_cli_worker",
    )
    non_interactive_prompt_contract_status = session_smoke.get(
        "non_interactive_prompt_contract_status",
        "pass" if session_status == "pass" else ("blocked" if session_status == "blocked" else session_status),
    )
    session_diagnostics = session_smoke.get("diagnostics") if isinstance(session_smoke.get("diagnostics"), dict) else {}
    session_auth_status = str(session_diagnostics.get("auth_status") or "unknown")
    session_model_catalog_visible = bool(session_diagnostics.get("model_catalog_visible"))
    session_not_authenticated = bool(session_diagnostics.get("not_authenticated_marker_present"))
    session_auth_failure_marker = bool(session_smoke.get("auth_failure_marker_present"))
    raw_session_auth_healthy = session_diagnostics.get("auth_session_healthy")
    if session_auth_status == "not_authenticated" or session_not_authenticated or session_auth_failure_marker:
        session_auth_evidence = "not_authenticated_marker"
    elif session_auth_status == "authenticated" or raw_session_auth_healthy is True:
        session_auth_evidence = "authenticated_diagnostics"
    elif session_status == "pass":
        session_auth_evidence = "pass_without_auth_diagnostics"
    elif raw_session_auth_healthy is False:
        session_auth_evidence = "diagnostics_not_healthy"
    else:
        session_auth_evidence = "unknown"
    session_auth_healthy = session_auth_evidence in {
        "authenticated_diagnostics",
        "pass_without_auth_diagnostics",
    }
    legacy_missing_key = report.get("status") in {"blocked", "missing_auth"}
    trusted_media_accepted, trusted_media_item, trusted_status_path = _trusted_runner_item_accepted(
        root,
        "run_crown_internal_media_smoke",
    )
    if missing:
        status = "fail"
    elif internal_worker_ready and trusted_media_accepted:
        status = "pass"
    elif internal_worker_ready:
        status = "candidate"
    elif legacy_missing_key:
        status = "blocked"
    else:
        status = "fail"
    auth_check = next(
        (check for check in report.get("checks", []) if check.get("id") == "auth_secret_present"),
        {},
    )
    accepted_env = auth_check.get("accepted_env") or [report.get("api_key_env"), *(report.get("backend", {}).get("api_key_env_aliases") or [])]
    details = {
        "backend_id": report.get("backend_id"),
        "adapter_kind": report.get("adapter_kind"),
        "worker_id": worker_id,
        "role_owner": role_owner,
        "internal_worker": backend.get("internal_worker"),
        "researcher_grok_binding": researcher_worker_binding_ready,
        "artifact_producer_grok_binding": artifact_worker_binding_ready,
        "grok_invocation_contract_ready": invocation_contract_ready,
        "grok_research_contract_ready": grok_research_contract_ready,
        "grok_media_contract_ready": grok_media_contract_ready,
        "grok_research_command": research_contract_command,
        "grok_media_command": media_contract_command,
        "grok_invocation_command": media_contract_command,
        "grok_backend_command": backend_command,
        "grok_research_invocation_style": grok_research_contract.get("invocation_style"),
        "grok_invocation_style": grok_media_contract.get("invocation_style"),
        "local_cli_entrypoint_available": local_cli_entrypoint_available,
        "local_cli_entrypoint_is_internal_worker": local_cli_entrypoint_is_internal_worker,
        "local_cli_auth_mode": session_smoke.get("local_cli_auth_mode", "oauth_cli_session"),
        "local_cli_requires_api_key": False,
        "non_interactive_prompt_contract_status": non_interactive_prompt_contract_status,
        "approval_required": approval_required,
        "execution_kernel": backend.get("execution_kernel"),
        "orchestration_scope": backend.get("orchestration_scope"),
        "workflow_shell_registry": backend.get("workflow_shell_registry"),
        "workflow_shell_capability_families": backend.get("workflow_shell_capability_families") or [],
        "execution_mode": (report.get("backend") or {}).get("execution_mode"),
        "historical_cli_smoke_status": smoke.get("status"),
        "session_smoke_status": session_status,
        "session_auth_status": session_auth_status,
        "session_auth_evidence": session_auth_evidence,
        "session_auth_healthy": session_auth_healthy,
        "session_auth_diagnostic_reported": raw_session_auth_healthy is not None,
        "session_model_catalog_visible": session_model_catalog_visible,
        "session_not_authenticated_marker_present": session_not_authenticated,
        "text_handoff_counts_as_media_artifact": False,
        "local_cli_asset_return_contract_ready": True,
        "local_cli_asset_return_marker": "AGENTLAB_GENERATED_ASSET:",
        "local_cli_selection_requires_registered_backend_command": True,
        "direct_api_key_path_is_fallback_only": True,
        "media_acceptance_requires_generated_assets": True,
        "media_acceptance_requires_artifact_generation_verified": True,
        "trusted_runner_item": "run_crown_internal_media_smoke",
        "trusted_runner_item_status": trusted_media_item.get("status"),
        "trusted_runner_item_acceptance_blocker": trusted_media_item.get("acceptance_blocker"),
        "trusted_runner_returned_artifacts_accepted": trusted_media_accepted,
    }
    if session_reason:
        details["session_smoke_reason"] = session_reason
    if internal_worker_ready and trusted_media_accepted:
        summary = (
            "Local Grok CLI media backend returned accepted trusted-runner media artifacts "
            "through ArtifactProducer/grok hermes_grok_oauth; the same Hermes executable "
            "has separate bounded grok_research and grok_media contracts"
        )
        issues = []
    elif internal_worker_ready:
        summary = (
            "Local Grok CLI preflight is ready and historical Grok smoke is retained as evidence; "
            f"current non-private session smoke status={session_status or 'missing'}"
            + (f" reason={session_reason}" if session_reason else "")
            + f" auth_status={session_auth_status}"
            + "; Researcher/grok and ArtifactProducer/grok use separate contracts on the configured Hermes executable"
        )
        issues = [
            *(
                [f"current non-private Grok session smoke status={session_status} reason={session_reason}"]
                if session_status == "blocked"
                else []
            ),
            "media artifact generation not verified yet; run-local candidates still require QC and promotion gates",
            "Grok text handoff does not satisfy media artifact acceptance without generated_assets and artifact_generation_verified",
            "local Grok CLI media acceptance uses AGENTLAB_GENERATED_ASSET lines for verified asset return under the trusted out_dir",
        ]
    else:
        summary = (
            f"adapter configured; local Grok CLI task execution blocked safely: {block_reason or report.get('status')}; "
            f"accepted env: {', '.join(str(item) for item in accepted_env if item)}"
        )
        issues = [
            "local Grok CLI backend is missing, blocked, or lacks the bounded Researcher/grok and ArtifactProducer/grok Hermes contracts; direct xAI API keys are fallback-only"
        ]
    if missing:
        issues = missing
    return {
        "id": "grok_xai_media_backend",
        "title": "Local Grok CLI media backend adapter",
        "status": status,
        "evidence": [
            str(adapter),
            str(media_backend_config_path),
            str(role_bindings),
            str(invocation_contracts_path),
            str(current_preflight),
            str(historical_cli_smoke),
            str(session_smoke_path),
            str(preflight),
            str(trusted_status_path),
        ],
        "summary": summary,
        "issues": issues,
        "details": details,
    }


def _live_unblock_plan(root: Path) -> dict[str, Any]:
    path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "live_unblock_plan.yml"
    report = _read_yaml(path)
    items = report.get("items", []) if isinstance(report.get("items"), list) else []
    acceptance_phase = (
        report.get("acceptance_phase")
        if isinstance(report.get("acceptance_phase"), dict)
        else {}
    )
    session_health_gate = (
        report.get("session_health_gate")
        if isinstance(report.get("session_health_gate"), dict)
        else {}
    )
    valid = report.get("status") in {"ready_for_internal_live_smoke", "ready_or_not_blocked"} and len(items) >= 2
    return {
        "id": "internal_live_unblock_plan",
        "legacy_ids": ["live_external_unblock_plan"],
        "title": "Internal live-smoke execution plan",
        "status": "pass" if valid else "fail",
        "evidence": [str(path)],
        "summary": (
            f"live unblock plan status={report.get('status')}; "
            f"session_gate={session_health_gate.get('status', 'missing')}; "
            f"items={len(items)}; "
            f"acceptance_phase={acceptance_phase.get('status', 'missing')}; "
            f"final_acceptance_passed={acceptance_phase.get('final_acceptance_passed')}"
        ),
        "issues": [] if valid else ["internal live-smoke plan missing or incomplete"],
        "details": {
            "workflow_boundary": report.get("workflow_boundary"),
            "session_health_gate": session_health_gate,
            "acceptance_phase": acceptance_phase,
            "items": [
                {
                    "id": item.get("id"),
                    "status": item.get("status"),
                    "current_return": item.get("current_return"),
                    "trusted_runner_command": item.get("trusted_runner_command"),
                    "selected_collect_command": item.get("selected_collect_command"),
                }
                for item in items
                if isinstance(item, dict)
            ],
        },
    }


def _external_acceptance_readiness(root: Path) -> dict[str, Any]:
    internal_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "internal_live_readiness.yml"
    legacy_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "external_acceptance_readiness.yml"
    path = internal_path if internal_path.exists() else legacy_path
    report = _read_yaml(path)
    report_status = report.get("status")
    ready_items = report.get("ready_items", []) if isinstance(report.get("ready_items"), list) else []
    session_health_issues = (
        report.get("session_health_issues", [])
        if isinstance(report.get("session_health_issues"), list)
        else []
    )
    valid = (
        report_status in {"ready_for_internal_live_smoke", "ready_for_user_input"}
        and report.get("source_report_health", {}).get("status") == "pass"
        and len(ready_items) == 2
    )
    route_ready_session_blocked = (
        report_status == "route_ready_session_blocked"
        and report.get("source_report_health", {}).get("status") == "pass"
        and len(ready_items) == 2
        and bool(session_health_issues)
    )
    policy_blocked = (
        report_status == "blocked_external_policy"
        and report.get("source_report_health", {}).get("status") == "pass"
        and report.get("policy_rejections")
    )
    return {
        "id": "internal_live_readiness",
        "legacy_ids": ["external_acceptance_readiness"],
        "title": "Internal live-smoke readiness",
        "status": "pass" if valid else ("candidate" if route_ready_session_blocked else ("blocked" if policy_blocked else "fail")),
        "evidence": [
            str(path),
            *([str(legacy_path)] if path != legacy_path and legacy_path.exists() else []),
            *[str(item.get("_path")) for item in report.get("policy_rejections", []) if item.get("_path")],
        ],
        "summary": (
            f"internal live readiness status={report_status}; "
            f"ready_items={len(ready_items)}; "
            f"session_health_issues={len(session_health_issues)}; "
            f"policy_rejections={len(report.get('policy_rejections', []) if isinstance(report.get('policy_rejections'), list) else [])}"
        ),
        "issues": []
        if valid
        else (
            [
                f"current session health blocked: {', '.join(str(item.get('id')) for item in session_health_issues)}"
            ]
            if route_ready_session_blocked
            else (
            ["external private-context egress blocked by host/tenant policy"]
            if policy_blocked
            else ["internal live-smoke readiness missing or failing"]
            )
        ),
    }


def _trusted_live_runner_request(root: Path) -> dict[str, Any]:
    request_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_request.yml"
    script_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_request.sh"
    report = _read_yaml(request_path)
    items = report.get("items", []) if isinstance(report.get("items"), list) else []
    writer_item = next(
        (
            item
            for item in items
            if isinstance(item, dict) and item.get("id") == "run_crown_internal_writer_eval"
        ),
        {},
    )
    runner_package = report.get("local_runner_package") if isinstance(report.get("local_runner_package"), dict) else {}
    preflight_commands = runner_package.get("preflight_commands", [])
    writer_route_current = (
        writer_item.get("assigned_worker") == "claude_code"
        and "--writer-worker claude_code" in str(writer_item.get("command") or "")
        and "--writer-worker agy" not in str(writer_item.get("command") or "")
    )
    preflight_writer_route_current = (
        "command -v claude" in preflight_commands
        and "command -v agy" not in preflight_commands
    )
    package_entrypoint = Path(str(runner_package.get("entrypoint") or ""))
    if package_entrypoint and not package_entrypoint.is_absolute():
        package_entrypoint = root / package_entrypoint
    valid = (
        report.get("status") == "ready_for_trusted_runner"
        and len(items) >= 2
        and script_path.exists()
        and package_entrypoint.resolve() == script_path.resolve()
        and runner_package.get("refreshes_status_after_run") is True
        and runner_package.get("refreshes_acceptance_after_run") is True
        and runner_package.get("full_run_executes_session_health_checks") is True
        and runner_package.get("session_health_gate_before_private_context") is True
        and runner_package.get("approval_gate_before_private_context") is True
        and runner_package.get("exact_outbound_context_manifest_required") is True
        and runner_package.get("writer_sealed_context_required") is True
        and runner_package.get("media_prompt_digest_required") is True
        and runner_package.get("secret_pattern_gate_before_provider_call") is True
        and runner_package.get("full_run_requires_trusted_status_pass") is True
        and "trusted-live-runner-collect" in str(runner_package.get("post_run_collect_command") or "")
        and writer_route_current
        and preflight_writer_route_current
        and "command -v hermes" in preflight_commands
        and report.get("secret_values_rendered") is False
    )
    return {
        "id": "trusted_live_runner_request",
        "title": "Trusted live runner request",
        "status": "pass" if valid else "fail",
        "evidence": [str(request_path), str(script_path)],
        "summary": (
            f"trusted runner request status={report.get('status')}; "
            f"items={len(items)}; "
            f"script_exists={script_path.exists()}; "
            f"local_runner_package={bool(runner_package)}; "
            f"session_health_gate={runner_package.get('session_health_gate_before_private_context') is True}; "
            f"approval_gate={runner_package.get('approval_gate_before_private_context') is True}; "
            f"outbound_context_gate={runner_package.get('exact_outbound_context_manifest_required') is True}; "
            f"full_run_requires_trusted_status_pass={runner_package.get('full_run_requires_trusted_status_pass') is True}; "
            f"post_run_collect={bool(runner_package.get('post_run_collect_command'))}"
        ),
        "details": {
            "full_run_requires_trusted_status_pass": runner_package.get("full_run_requires_trusted_status_pass") is True,
            "full_run_executes_session_health_checks": runner_package.get("full_run_executes_session_health_checks") is True,
            "session_health_gate_before_private_context": runner_package.get("session_health_gate_before_private_context") is True,
            "approval_gate_before_private_context": runner_package.get("approval_gate_before_private_context") is True,
            "exact_outbound_context_manifest_required": (
                runner_package.get("exact_outbound_context_manifest_required") is True
            ),
            "writer_sealed_context_required": runner_package.get("writer_sealed_context_required") is True,
            "media_prompt_digest_required": runner_package.get("media_prompt_digest_required") is True,
            "secret_pattern_gate_before_provider_call": (
                runner_package.get("secret_pattern_gate_before_provider_call") is True
            ),
            "role_session_acceptance_approval_env_required": runner_package.get(
                "role_session_acceptance_approval_env_required"
            ),
            "refreshes_status_after_run": runner_package.get("refreshes_status_after_run") is True,
            "refreshes_acceptance_after_run": runner_package.get("refreshes_acceptance_after_run") is True,
            "writer_route_current": writer_route_current,
            "writer_assigned_worker": writer_item.get("assigned_worker"),
            "preflight_writer_route_current": preflight_writer_route_current,
        },
        "issues": [] if valid else ["trusted live runner request missing, unsafe, or incomplete"],
    }


def _trusted_live_runner_operator_handoff(root: Path) -> dict[str, Any]:
    path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_operator_handoff.yml"
    report = _read_yaml(path)
    steps = report.get("operator_steps", []) if isinstance(report.get("operator_steps"), list) else []
    step_by_id: dict[str, dict[str, Any]] = {}
    for item in steps:
        if not isinstance(item, dict):
            continue
        step_by_id[str(item.get("step"))] = item
    candidate_items = report.get("candidate_items", []) if isinstance(report.get("candidate_items"), list) else []
    boundary = report.get("execution_boundary") if isinstance(report.get("execution_boundary"), dict) else {}
    session_health = report.get("session_health") if isinstance(report.get("session_health"), dict) else {}
    selected_item_readiness = (
        report.get("selected_item_readiness")
        if isinstance(report.get("selected_item_readiness"), dict)
        else {}
    )
    selected_ready_item_ids = [
        str(item)
        for item in selected_item_readiness.get("ready_item_ids", [])
        if item
    ]
    selected_blocked_item_ids = [
        str(item)
        for item in selected_item_readiness.get("blocked_item_ids", [])
        if item
    ]
    session_health_issues = (
        session_health.get("issues")
        if isinstance(session_health.get("issues"), list)
        else []
    )
    session_health_issue_reasons = [
        str(item.get("reason"))
        for item in session_health_issues
        if isinstance(item, dict) and item.get("reason")
    ]
    acceptance_step = step_by_id.get("role_session_acceptance_smoke", {})
    handoff_ready = report.get("status") in {"ready_for_trusted_runner", "ready_for_user_terminal"}
    valid = (
        handoff_ready
        and boundary.get("codex_frontdesk_executes_private_live_commands") is False
        and boundary.get("codex_frontdesk_executes_role_session_acceptance_commands", False) is False
        and boundary.get("trusted_agentlab_runner_required", True) is True
        and boundary.get("trusted_runner_or_user_terminal_required") is True
        and boundary.get("non_private_session_health_clean") is True
        and boundary.get("agentlab_internal_route_blocked") is False
        and boundary.get("approval_gate_before_private_context") is True
        and step_by_id.get("preflight", {}).get("loads_private_project_context") is False
        and step_by_id.get("session_health", {}).get("loads_private_project_context") is False
        and acceptance_step.get("loads_private_project_context") is True
        and bool(acceptance_step.get("approval_env_required"))
        and any(
            item.get("assigned_worker") == "claude_code"
            for item in candidate_items
            if isinstance(item, dict)
        )
        and any(item.get("assigned_worker") == "grok" for item in candidate_items if isinstance(item, dict))
        and report.get("secret_values_rendered") is False
    )
    session_health_attention = (
        report.get("status") == "needs_attention"
        and boundary.get("codex_frontdesk_executes_private_live_commands") is False
        and boundary.get("codex_frontdesk_executes_role_session_acceptance_commands", False) is False
        and boundary.get("trusted_runner_or_user_terminal_required") is True
        and boundary.get("agentlab_internal_route_blocked") is False
        and boundary.get("non_private_session_health_clean") is False
        and (
            "internal_live_readiness_not_clean" in (report.get("issues") or [])
            or "external_acceptance_readiness_not_clean" in (report.get("issues") or [])
        )
        and report.get("secret_values_rendered") is False
    )
    return {
        "id": "trusted_live_runner_operator_handoff",
        "title": "Trusted live runner operator handoff",
        "status": "pass" if valid else ("candidate" if session_health_attention else "fail"),
        "evidence": [str(path)],
        "summary": (
            f"operator handoff status={report.get('status')}; "
            f"steps={len(steps)}; "
            f"candidate_items={len(candidate_items)}; "
            f"session_health_issues={len(session_health_issues)}; "
            f"selected_ready={','.join(selected_ready_item_ids) or 'none'}; "
            f"selected_blocked={','.join(selected_blocked_item_ids) or 'none'}; "
            f"approval_gate={boundary.get('approval_gate_before_private_context') is True}; "
            f"frontdesk_private_exec={boundary.get('codex_frontdesk_executes_private_live_commands')}"
        ),
        "issues": []
        if valid
        else (
            ["non-private session health is not clean; role-session acceptance smoke remains gated"]
            if session_health_attention
            else ["trusted live runner operator handoff missing, unsafe, or incomplete"]
        ),
        "details": {
            "acceptance_smoke_kind": (report.get("terminology") or {}).get("canonical_kind"),
            "writer_request_route_current": (
                boundary.get("writer_request_route_current") is True
            ),
            "trusted_agentlab_runner_required": boundary.get("trusted_agentlab_runner_required", True),
            "user_terminal_fallback_allowed": boundary.get("user_terminal_fallback_allowed"),
            "trusted_runner_or_user_terminal_required": boundary.get("trusted_runner_or_user_terminal_required"),
            "approval_gate_before_private_context": boundary.get("approval_gate_before_private_context"),
            "role_session_acceptance_approval_env_required": boundary.get(
                "role_session_acceptance_approval_env_required"
            ),
            "non_private_session_health_clean": boundary.get("non_private_session_health_clean"),
            "session_health_status": session_health.get("status"),
            "session_health_issue_count": len(session_health_issues),
            "session_health_issue_reasons": session_health_issue_reasons,
            "session_health_next_action": session_health.get("next_action"),
            "selected_item_readiness": selected_item_readiness,
            "current_return_status": report.get("current_return_status"),
        },
    }


def _trusted_live_runner_preflight(root: Path) -> dict[str, Any]:
    preflight_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_preflight.yml"
    report = _read_yaml(preflight_path)
    status = report.get("status")
    checks = report.get("checks", []) if isinstance(report.get("checks"), list) else []
    passed = len([check for check in checks if isinstance(check, dict) and check.get("status") == "pass"])
    valid = (
        status == "pass"
        and report.get("executes_provider_calls") is False
        and report.get("loads_private_project_context") is False
        and passed >= 5
    )
    return {
        "id": "trusted_live_runner_preflight",
        "title": "Trusted live runner local preflight",
        "status": "pass" if valid else "fail",
        "evidence": [str(preflight_path)],
        "summary": (
            f"trusted runner preflight status={status}; "
            f"checks_passed={passed}; "
            f"provider_calls={report.get('executes_provider_calls')}"
        ),
        "issues": [] if valid else ["trusted live runner local preflight missing, unsafe, or failing"],
    }


def _trusted_live_runner_status(root: Path) -> dict[str, Any]:
    status_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_status.yml"
    report = _read_yaml(status_path)
    status = report.get("status")
    items = report.get("items", []) if isinstance(report.get("items"), list) else []
    pending_items = [item for item in items if isinstance(item, dict) and item.get("status") != "pass"]
    accepted_items = [
        item
        for item in items
        if isinstance(item, dict)
        and item.get("status") == "pass"
        and item.get("returned_candidate_artifacts_accepted") is True
    ]
    unaccepted_pass_items = [
        item
        for item in items
        if isinstance(item, dict)
        and item.get("status") == "pass"
        and item.get("returned_candidate_artifacts_accepted") is not True
    ]
    acceptance_blockers = [
        str(item.get("acceptance_blocker"))
        for item in pending_items
        if item.get("acceptance_blocker")
    ]
    missing_count = len(report.get("missing_items", []) if isinstance(report.get("missing_items"), list) else [])
    stale_count = len(report.get("stale_items", []) if isinstance(report.get("stale_items"), list) else [])
    qc_failure_count = len(report.get("artifact_qc_failures", []) if isinstance(report.get("artifact_qc_failures"), list) else [])
    strict_status_pass = (
        status == "pass"
        and len(items) >= 2
        and len(accepted_items) >= 2
        and not pending_items
        and not unaccepted_pass_items
        and missing_count == 0
        and stale_count == 0
        and qc_failure_count == 0
    )
    inconsistent_pass_report = status == "pass" and not strict_status_pass
    if strict_status_pass:
        capability_status = "pass"
        issues = []
    elif inconsistent_pass_report:
        capability_status = "fail"
        issues = ["trusted runner status reports pass, but returned-artifact acceptance invariants are inconsistent"]
    elif status == "pending":
        capability_status = "candidate"
        issues = ["trusted runner has not returned all expected role-session acceptance artifacts"]
        if stale_count:
            issues.append("one or more role-session acceptance failures are stale after backend contract update and require rerun")
        if qc_failure_count:
            issues.append("one or more returned role-session acceptance artifacts failed local structural QC")
    else:
        capability_status = "fail"
        issues = ["trusted live runner status report missing or failing"]
    return {
        "id": "trusted_live_runner_status",
        "title": "Trusted live runner returned artifacts",
        "status": capability_status,
        "evidence": [str(status_path)],
        "summary": (
            f"trusted runner status={status}; "
            f"missing_items={missing_count}; "
            f"stale_items={stale_count}; "
            f"artifact_qc_failures={qc_failure_count}; "
            f"acceptance_blockers={','.join(sorted(set(acceptance_blockers))) or 'none'}"
        ),
        "issues": issues,
            "details": {
                "pending_items": [
                    {
                        "id": item.get("id"),
                        "required_files_exist": item.get("required_files_exist"),
                    "returned_candidate_artifacts_accepted": item.get("returned_candidate_artifacts_accepted"),
                    "acceptance_blocker": item.get("acceptance_blocker"),
                }
                    for item in pending_items
                ],
                "acceptance_blockers": sorted(set(acceptance_blockers)),
                "strict_status_pass": strict_status_pass,
                "inconsistent_pass_report": inconsistent_pass_report,
                "accepted_item_count": len(accepted_items),
                "unaccepted_pass_items": [
                    {
                        "id": item.get("id"),
                        "returned_candidate_artifacts_accepted": item.get(
                            "returned_candidate_artifacts_accepted"
                        ),
                        "acceptance_blocker": "returned_artifacts_not_accepted",
                    }
                    for item in unaccepted_pass_items
                ],
            },
        }


def _trusted_live_runner_collect(root: Path) -> dict[str, Any]:
    collect_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_collect.yml"
    report = _read_yaml(collect_path)
    refreshed = report.get("refreshed_reports") if isinstance(report.get("refreshed_reports"), dict) else {}
    status = report.get("status")
    allowed_status = status in {"pending_returned_artifacts", "pass", "artifact_qc_failed"}
    required_reports = {
        "trusted_live_runner_status",
        "trusted_live_runner_operator_handoff",
        "live_unblock_plan",
        "capability_acceptance",
        "objective_requirement_audit",
        "goal_completion_audit",
        "acceptance_report_hygiene",
    }
    refreshed_keys = set(refreshed)
    handoff_status = report.get("operator_handoff_status")
    pending_items = report.get("pending_items", []) if isinstance(report.get("pending_items"), list) else []
    reported_acceptance_blockers = (
        report.get("acceptance_blockers") if isinstance(report.get("acceptance_blockers"), list) else None
    )
    acceptance_blockers = (
        [str(item) for item in reported_acceptance_blockers if item]
        if reported_acceptance_blockers is not None
        else [
            str(item.get("acceptance_blocker"))
            for item in pending_items
            if isinstance(item, dict) and item.get("acceptance_blocker")
        ]
    )
    reported_acceptance_blocker_reasons = (
        report.get("acceptance_blocker_reasons")
        if isinstance(report.get("acceptance_blocker_reasons"), list)
        else None
    )
    acceptance_blocker_reasons = (
        [str(item) for item in reported_acceptance_blocker_reasons if item]
        if reported_acceptance_blocker_reasons is not None
        else [
            str(item.get("pending_reason"))
            for item in pending_items
            if isinstance(item, dict) and item.get("pending_reason")
        ]
    )
    acceptance_summary = (
        report.get("acceptance_summary") if isinstance(report.get("acceptance_summary"), dict) else {}
    )
    hygiene_text_artifact_count = acceptance_summary.get(
        "acceptance_report_hygiene_canonical_text_artifact_count"
    )
    hygiene_text_issue_count = acceptance_summary.get(
        "acceptance_report_hygiene_canonical_text_issue_count"
    )
    hygiene_stale_private_selected_command_hit_count = acceptance_summary.get(
        "acceptance_report_hygiene_stale_private_selected_command_hit_count"
    )
    trusted_status_summary = (
        report.get("trusted_live_runner_status")
        if isinstance(report.get("trusted_live_runner_status"), dict)
        else {}
    )
    returned_accepted_count = report.get("returned_candidate_artifacts_accepted_count")
    if not isinstance(returned_accepted_count, int):
        returned_accepted_count = 0
    strict_acceptance_pass = (
        status == "pass"
        and trusted_status_summary.get("status") == "pass"
        and not pending_items
        and not acceptance_blockers
        and returned_accepted_count >= 2
    )
    valid = (
        strict_acceptance_pass
        and required_reports.issubset(refreshed_keys)
        and report.get("secret_values_rendered") is False
        and handoff_status in {"ready_for_trusted_runner", "ready_for_user_terminal"}
    )
    inconsistent_pass_report = (
        status == "pass"
        and required_reports.issubset(refreshed_keys)
        and report.get("secret_values_rendered") is False
        and not strict_acceptance_pass
    )
    returned_artifacts_pending = (
        allowed_status
        and required_reports.issubset(refreshed_keys)
        and report.get("secret_values_rendered") is False
        and handoff_status in {"ready_for_trusted_runner", "ready_for_user_terminal"}
        and (report.get("trusted_live_runner_status") or {}).get("status") == "pending"
    )
    session_health_attention = (
        allowed_status
        and required_reports.issubset(refreshed_keys)
        and report.get("secret_values_rendered") is False
        and handoff_status == "needs_attention"
        and (report.get("trusted_live_runner_status") or {}).get("status") == "pending"
    )
    return {
        "id": "trusted_live_runner_collect",
        "title": "Trusted live runner post-run collector",
        "status": "pass"
        if valid
        else (
            "fail"
            if inconsistent_pass_report
            else ("candidate" if returned_artifacts_pending or session_health_attention else "fail")
        ),
        "evidence": [str(collect_path)],
        "summary": (
            f"trusted runner collect status={status}; "
            f"refreshed_reports={len(refreshed_keys)}; "
            f"operator_handoff={report.get('operator_handoff_status')}; "
            f"secret_values_rendered={report.get('secret_values_rendered')}; "
            f"hygiene_text_artifacts={hygiene_text_artifact_count}; "
            f"hygiene_text_issues={hygiene_text_issue_count}; "
            f"hygiene_private_selected_command_hits={hygiene_stale_private_selected_command_hit_count}; "
            f"acceptance_blockers={','.join(sorted(set(acceptance_blockers))) or 'none'}; "
            f"acceptance_blocker_reasons={','.join(sorted(set(acceptance_blocker_reasons))) or 'none'}"
        ),
        "issues": []
        if valid
        else (
            ["collector reports pass, but returned-artifact acceptance invariants are inconsistent"]
            if inconsistent_pass_report
            else
            ["collector refreshed reports, but returned role-session acceptance artifacts are not accepted yet"]
            if returned_artifacts_pending
            else ["collector refreshed reports, but non-private session health still needs attention"]
            if session_health_attention
            else ["trusted live runner collector missing, unsafe, or incomplete"]
        ),
        "details": {
            "refreshed_reports": sorted(refreshed_keys),
            "acceptance_summary": acceptance_summary,
            "acceptance_report_hygiene_canonical_text_artifact_count": hygiene_text_artifact_count,
            "acceptance_report_hygiene_canonical_text_issue_count": hygiene_text_issue_count,
            "acceptance_report_hygiene_stale_private_selected_command_hit_count": (
                hygiene_stale_private_selected_command_hit_count
            ),
            "trusted_live_runner_status": report.get("trusted_live_runner_status"),
            "strict_acceptance_pass": strict_acceptance_pass,
            "inconsistent_pass_report": inconsistent_pass_report,
            "pending_items": pending_items,
            "acceptance_blockers": sorted(set(acceptance_blockers)),
            "acceptance_blocker_reasons": sorted(set(acceptance_blocker_reasons)),
            "required_files_missing_count": report.get("required_files_missing_count"),
            "returned_candidate_artifacts_accepted_count": returned_accepted_count,
            "selected_item_summaries": report.get("selected_item_summaries")
            if isinstance(report.get("selected_item_summaries"), dict)
            else {},
            "selected_item_report_paths": report.get("selected_item_report_paths")
            if isinstance(report.get("selected_item_report_paths"), dict)
            else {},
            "next_action": report.get("next_action"),
        },
    }


def _provider_reachability_candidate(root: Path) -> dict[str, Any]:
    smoke_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "provider_smoke_current.yml"
    smoke = _read_yaml(smoke_path)
    evidence = [
        smoke_path,
        _run_dir(root, "AgentLab", "task_live_code_ui_app_json_binding_20260707") / "cost_ledger.yml",
        _run_dir(root, "Crown_of_Ash", "task_narrative_eval_ch01_live_ch01_20260707_cli_fallback") / "cost_ledger.yml",
    ]
    ledger_missing = [str(path) for path in evidence[1:] if not path.exists()]
    smoke_status = smoke.get("status")
    if smoke_status == "pass":
        status = "pass"
        issues = []
        summary = f"current provider smoke passed for {smoke.get('provider')}; prior usage ledgers present"
    elif smoke_status == "warn":
        status = "candidate"
        issues = [smoke.get("reason") or "provider smoke warning"]
        summary = (
            f"current provider smoke connected with warning for {smoke.get('provider')}: {smoke.get('reason')}; "
            f"finish_reason={smoke.get('finish_reason')}; output_tokens={smoke.get('output_tokens')}"
        )
    elif smoke_status == "configured":
        status = "candidate"
        issues = ["provider smoke is dry-run only; run provider-smoke --live before expensive live work"]
        summary = f"provider config smoke present for {smoke.get('provider')}; live reachability not proven"
    elif smoke_status == "blocked":
        status = "blocked"
        issues = [smoke.get("reason") or "provider smoke blocked"]
        summary = f"current provider smoke blocked for {smoke.get('provider')}: {smoke.get('reason')}"
    else:
        status = "candidate" if not ledger_missing else "fail"
        issues = ledger_missing or ["run provider-smoke --live before expensive live work"]
        summary = "prior live text/code usage ledgers present; provider health is temporal"
    if ledger_missing and status == "pass":
        status = "candidate"
        issues = ledger_missing
    return {
        "id": "provider_reachability",
        "title": "Text/code provider reachability",
        "status": status,
        "evidence": [str(path) for path in evidence],
        "summary": summary,
        "issues": issues,
        "details": {
            "result_status": smoke.get("result_status"),
            "content_present": smoke.get("content_present"),
            "finish_reason": smoke.get("finish_reason"),
            "input_tokens": smoke.get("input_tokens"),
            "output_tokens": smoke.get("output_tokens"),
            "total_tokens": smoke.get("total_tokens"),
            "raw_usage_keys": smoke.get("raw_usage_keys", []),
        },
    }


def _budget_prepare(root: Path) -> dict[str, Any]:
    plan_path = _run_dir(root, "AgentLab", "task_prepare_frugal_real_smoke_20260707") / "workflow_plan.yml"
    plan = _read_yaml(plan_path)
    budget = plan.get("budget_mode")
    profile = plan.get("budget_profile")
    valid = budget == "frugal" and profile == "frugal_L2"
    return {
        "id": "budget_aware_prepare",
        "title": "Budget-aware prepare behavior",
        "status": "pass" if valid else "fail",
        "evidence": [str(plan_path)],
        "summary": f"budget_mode={budget}; budget_profile={profile}",
        "issues": [] if valid else ["frugal prepare smoke no longer records expected budget fields"],
    }


def build_capability_acceptance_report(root: Path) -> dict[str, Any]:
    """Build a conservative local acceptance report for core AgentLab goals."""
    root = root.resolve()
    capabilities: list[dict[str, Any]] = []
    capabilities.extend(_artifact_probe(root, probe) for probe in ARTIFACT_PROBES)
    capabilities.extend(
        [
            _workflow_has_no_code_shell(root),
            _media_series_scaffold(root),
            _production_pack_synthesis(root),
            _production_pack_synthesis_smoke(root),
            _production_pack_role_session(root),
            _core_package_import_stability(root),
            _production_chain_visibility(root),
            _agent_role_chain_consistency(root),
            _frontdesk_boundary(root),
            _cli_workflow_shell_absorption(root),
            _cli_native_command_surface_governance(root),
            _cli_shell_coalesced_runner_implementation(root),
            _cli_shell_coalesced_runner_request(root),
            _cli_shell_coalesced_collect(root),
            _cli_shell_coalesced_session_returns(root),
            _live_code_candidate(root),
            _crown_live_writer(root),
            _crown_formal_live_eval(root),
            _narrative_heavy_scale(root),
            _grok_media_backend(root),
            _live_unblock_plan(root),
            _external_acceptance_readiness(root),
            _trusted_live_runner_request(root),
            _trusted_live_runner_operator_handoff(root),
            _trusted_live_runner_preflight(root),
            _trusted_live_runner_status(root),
            _trusted_live_runner_collect(root),
            _provider_reachability_candidate(root),
            _budget_prepare(root),
        ]
    )
    counts: dict[str, int] = {}
    for item in capabilities:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    worst = max((item["status"] for item in capabilities), key=lambda status: STATUS_RANK.get(status, 99))
    overall = "fail" if worst == "fail" else ("warn" if worst in {"warn", "blocked"} else "candidate")
    if all(item["status"] == "pass" for item in capabilities):
        overall = "pass"
    return {
        "schema_version": 1,
        "report_type": "agentlab_capability_acceptance",
        "root": str(root),
        "overall_status": overall,
        "status_counts": counts,
        "capabilities": capabilities,
        "notes": [
            "This report reads existing evidence only; it does not call live providers.",
            "candidate means candidate evidence exists but production acceptance is not proven.",
            "blocked means the adapter/contract exists but execution is waiting on credentials or provider stability.",
        ],
    }
