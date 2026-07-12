"""Actionable plan for internal AgentLab role-session acceptance smokes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

try:
    from audit_helpers import (
        normalize_trusted_pending_live_smoke_item,
        role_session_execution_boundary,
        selected_collect_metadata_by_item,
    )
except ModuleNotFoundError:
    from agent_runtime.audit_helpers import (
        normalize_trusted_pending_live_smoke_item,
        role_session_execution_boundary,
        selected_collect_metadata_by_item,
    )


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _acceptance_smoke_terminology() -> dict[str, Any]:
    return {
        "canonical_kind": "private_role_session_acceptance_smoke",
        "canonical_label": "private role-session acceptance smoke",
        "legacy_terms": ["private live smoke", "private live-smoke", "live-smoke"],
        "meaning": (
            "A minimal trusted-runner acceptance run that loads private project context "
            "through the configured AgentLab role-session worker and returns run-local "
            "candidate artifacts for structural QC."
        ),
        "not_a_default_production_workflow": True,
    }


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


def _writer_route_ready(root: Path) -> dict[str, Any]:
    profiles = _read_yaml(root / "config" / "agent_model_profiles.yml")
    catalog = _read_yaml(root / "config" / "model_catalog.yml")
    writer = (
        (((profiles.get("modes") or {}).get("full_cli") or {}).get("tiers") or {})
        .get("full", {})
        .get("writer", {})
    )
    model_key = str(writer.get("default") or "")
    model = ((catalog.get("models") or {}).get(model_key) or {})
    route_ready = (
        writer.get("cli_agent") == "agy"
        and writer.get("invocation_contract") == "agy_writer"
        and model_key == "gemini_3_5_flash_high_agy_oauth"
        and model.get("provider") == "agy_gemini_oauth"
        and _role_worker_binding_ok(root, "Writer", "agy")
    )
    auth = _probe_worker_auth("agy")
    return {
        "ready": route_ready,
        "auth_probe": auth,
        "worker": "agy",
        "model_key": model_key,
        "model_provider": model.get("provider"),
    }


def _current_return_status(
    trusted_items: dict[str, dict[str, Any]],
    item_id: str,
    selected_collect: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    item = trusted_items.get(item_id, {})
    if item:
        normalized = normalize_trusted_pending_live_smoke_item(item)
        required_files_exist = normalized["required_files_exist"]
        accepted = normalized["returned_candidate_artifacts_accepted"]
        blocker = normalized["acceptance_blocker"]
    else:
        required_files_exist = True
        accepted = False
        blocker = "trusted_status_item_missing"
    current = {
        "trusted_status_item_present": bool(item),
        "status": item.get("status", "missing"),
        "pending_reason": item.get("pending_reason"),
        "required_files_exist": required_files_exist,
        "returned_candidate_artifacts_accepted": accepted,
        "acceptance_blocker": blocker,
        "next_action": item.get("next_action"),
    }
    selected = (selected_collect or {}).get(item_id, {})
    if selected:
        current.update(selected)
    return current


def _selected_command(package: dict[str, Any], command_group: str, fallback: str) -> str:
    commands = package.get(command_group) if isinstance(package.get(command_group), dict) else {}
    command = commands.get("writer_only") if "writer" in fallback else commands.get("media_only")
    return str(command or fallback)


def build_live_unblock_plan(root: Path) -> dict[str, Any]:
    root = root.resolve()
    capability_report = _read_yaml(root / "acceptance_runs" / "agentlab_capability_acceptance" / "current.yml")
    trusted_status = _read_yaml(root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_status.yml")
    trusted_collect = _read_yaml(root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_collect.yml")
    trusted_request = _read_yaml(root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_request.yml")
    trusted_operator_handoff = _read_yaml(
        root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_operator_handoff.yml"
    )
    internal_readiness = _read_yaml(
        root / "acceptance_runs" / "agentlab_capability_acceptance" / "internal_live_readiness.yml"
    )
    local_runner_package = (
        trusted_request.get("local_runner_package")
        if isinstance(trusted_request.get("local_runner_package"), dict)
        else {}
    )
    selected_collect = selected_collect_metadata_by_item(trusted_collect)
    trusted_items = {
        str(item.get("id")): item
        for item in trusted_status.get("items", [])
        if isinstance(item, dict) and item.get("id")
    }
    capabilities = {
        item.get("id"): item
        for item in capability_report.get("capabilities", [])
        if isinstance(item, dict)
    }
    grok_preflight = _read_yaml(root / "acceptance_runs" / "agentlab_capability_acceptance" / "grok_media_preflight_current.yml")
    media_backend_config = _read_yaml(root / "config" / "media_generation_backends.yml")
    crown_error = _read_yaml(
        root
        / "projects"
        / "Crown_of_Ash"
        / "runs"
        / "task_narrative_eval_ch01_live_ch01_retry_20260707_1118"
        / "live_generation_error.yml"
    )
    crown_policy = _read_yaml(
        root
        / "acceptance_runs"
        / "narrative_eval"
        / "Crown_of_Ash"
        / "crown_live_single_chapter_probe_20260707"
        / "live_ch01_retry_20260707_1118"
        / "external_retry_policy_note.yml"
    )
    auth_check = next(
        (check for check in grok_preflight.get("checks", []) if check.get("id") == "auth_secret_present"),
        {},
    )
    local_cli_check = next(
        (
            check
            for check in grok_preflight.get("checks", [])
            if check.get("id") in {"local_cli_available", "oauth_cli_available"}
        ),
        {},
    )
    accepted_env = auth_check.get("accepted_env") or [
        grok_preflight.get("api_key_env"),
        *(grok_preflight.get("backend", {}).get("api_key_env_aliases") or []),
    ]
    accepted_env = [str(item) for item in accepted_env if item]
    writer_route = _writer_route_ready(root)
    media_backend = grok_preflight.get("backend", {}) if isinstance(grok_preflight.get("backend"), dict) else {}
    configured_media_backend = (
        ((media_backend_config.get("backends") or {}).get(str(grok_preflight.get("backend_id") or "")) or {})
        if isinstance(media_backend_config.get("backends"), dict)
        else {}
    )
    if isinstance(configured_media_backend, dict):
        media_backend = {**media_backend, **configured_media_backend}
    media_worker_id = str(media_backend.get("worker_id") or "")
    media_role_owner = str(media_backend.get("role_owner") or "")
    media_worker_binding_ok = (
        media_worker_id == "grok"
        and media_role_owner == "ArtifactProducer"
        and media_backend.get("internal_worker") is True
        and _role_worker_binding_ok(root, "ArtifactProducer", "grok")
    )
    media_route_ready = (
        grok_preflight.get("status") == "ready"
        and grok_preflight.get("backend_id") == "hermes_grok_oauth"
        and grok_preflight.get("adapter_kind") in {"local_grok_cli", "grok_cli_oauth"}
        and local_cli_check.get("status") == "pass"
        and media_backend.get("approval_required") is False
        and media_worker_binding_ok
    )

    items = [
        {
            "id": "run_crown_internal_writer_eval",
            "capability_id": "crown_formal_live_narrative_eval",
            "status": "ready" if writer_route.get("ready") else "needs_configuration",
            "current_return": _current_return_status(
                trusted_items,
                "run_crown_internal_writer_eval",
                selected_collect,
            ),
            "required_operator_action": "Submit the formal Crown single-chapter live eval as an AgentLab Writer role-session and monitor run-local artifacts.",
            "risk": "Private Crown context is used inside the configured AgentLab Writer workflow; generated prose remains candidate-only until promotion.",
            "route": writer_route,
            "historical_blocker": {
                "provider": crown_error.get("provider"),
                "model": crown_error.get("model"),
                "error": crown_error.get("error"),
                "policy_status": crown_policy.get("status"),
            },
            "agentlab_command": "./agentlab.sh narrative-eval run --project Crown_of_Ash --suite crown_live_single_chapter_probe_20260707 --mode live --chapters 1 --timestamp <internal_live_run_id> --writer-worker agy",
            "safe_command_after_approval": "./agentlab.sh narrative-eval run --project Crown_of_Ash --suite crown_live_single_chapter_probe_20260707 --mode live --chapters 1 --timestamp <internal_live_run_id> --writer-worker agy",
            "trusted_runner_command": _selected_command(
                local_runner_package,
                "selective_run_examples",
                "trusted_live_runner_request.sh --only run_crown_internal_writer_eval",
            ),
            "selected_collect_command": _selected_command(
                local_runner_package,
                "post_run_selected_collect_commands",
                "./agentlab.sh trusted-live-runner-collect --item run_crown_internal_writer_eval",
            ),
            "must_not_do": [
                "do not copy candidate chapters into production/manuscript automatically",
                "do not run live narrative eval without Writer role-session evidence",
                "do not run broad 1-20 or 1500-chapter live generation before one approved single-chapter pass",
            ],
            "evidence": capabilities.get("crown_formal_live_narrative_eval", {}).get("evidence", []),
        },
        {
            "id": "run_crown_internal_media_smoke",
            "capability_id": "grok_xai_media_backend",
            "status": "ready" if media_route_ready else "needs_configuration",
            "current_return": _current_return_status(
                trusted_items,
                "run_crown_internal_media_smoke",
                selected_collect,
            ),
            "required_operator_action": "Submit the Crown media role-session acceptance smoke through the AgentLab ArtifactProducer role-session and monitor run-local candidate artifacts.",
            "accepted_env": accepted_env,
            "route": {
                "backend_id": grok_preflight.get("backend_id"),
                "adapter_kind": grok_preflight.get("adapter_kind"),
                "worker_id": media_worker_id,
                "role_owner": media_role_owner,
                "role_worker_binding": media_worker_binding_ok,
                "internal_worker": media_backend.get("internal_worker"),
                "execution_mode": media_backend.get("execution_mode"),
                "approval_required": media_backend.get("approval_required"),
                "local_cli_available": local_cli_check.get("status"),
            },
            "agentlab_commands": [
                "./agentlab.sh media-backend-preflight --contract projects/Crown_of_Ash/runs/task_probe_crown_comic_video_poster_series_scaffold_20260707/media_generation_contract.yml --out acceptance_runs/agentlab_capability_acceptance/grok_media_preflight_current.yml",
                "./agentlab.sh media-backend-execute --contract projects/Crown_of_Ash/runs/task_probe_crown_comic_video_poster_series_scaffold_20260707/media_generation_contract.yml --out-dir projects/Crown_of_Ash/runs/task_probe_crown_comic_video_poster_series_scaffold_20260707/artifacts/media_backend_live_internal_<id> --live --role ArtifactProducer --worker grok --project Crown_of_Ash --run-id task_probe_crown_comic_video_poster_series_scaffold_20260707",
            ],
            "safe_commands_after_approval": [
                "./agentlab.sh media-backend-preflight --contract projects/Crown_of_Ash/runs/task_probe_crown_comic_video_poster_series_scaffold_20260707/media_generation_contract.yml --out acceptance_runs/agentlab_capability_acceptance/grok_media_preflight_current.yml",
                "./agentlab.sh media-backend-execute --contract projects/Crown_of_Ash/runs/task_probe_crown_comic_video_poster_series_scaffold_20260707/media_generation_contract.yml --out-dir projects/Crown_of_Ash/runs/task_probe_crown_comic_video_poster_series_scaffold_20260707/artifacts/media_backend_live_internal_<id> --live --role ArtifactProducer --worker grok --project Crown_of_Ash --run-id task_probe_crown_comic_video_poster_series_scaffold_20260707",
            ],
            "trusted_runner_command": _selected_command(
                local_runner_package,
                "selective_run_examples",
                "trusted_live_runner_request.sh --only run_crown_internal_media_smoke",
            ),
            "selected_collect_command": _selected_command(
                local_runner_package,
                "post_run_selected_collect_commands",
                "./agentlab.sh trusted-live-runner-collect --item run_crown_internal_media_smoke",
            ),
            "must_not_do": [
                "do not print or commit OAuth/session secret values",
                "do not run media-backend-execute --live without ArtifactProducer role-session evidence",
                "do not promote generated media without QC or human acceptance",
            ],
            "evidence": capabilities.get("grok_xai_media_backend", {}).get("evidence", []),
        },
    ]
    ready_items = [item for item in items if item["status"] == "ready"]
    pending_returns = [
        item
        for item in ready_items
        if item.get("current_return", {}).get("returned_candidate_artifacts_accepted") is not True
    ]
    session_health_issues = (
        internal_readiness.get("session_health_issues")
        if isinstance(internal_readiness.get("session_health_issues"), list)
        else []
    )
    session_health_issue_ids = [
        str(issue.get("id"))
        for issue in session_health_issues
        if isinstance(issue, dict) and issue.get("id")
    ]
    acceptance_phase_status = (
        "accepted"
        if ready_items and not pending_returns
        else "in_acceptance_pending_returned_artifacts"
        if ready_items
        else "pre_acceptance_configuration_needed"
    )
    return {
        "schema_version": 1,
        "report_type": "agentlab_live_unblock_plan",
        "root": str(root),
        "status": "ready_for_internal_live_smoke" if all(item["status"] == "ready" for item in items) else "needs_internal_configuration",
        "workflow_boundary": "internal_agentlab_role_sessions",
        "terminology": _acceptance_smoke_terminology(),
        "role_session_execution_boundary": role_session_execution_boundary(
            trusted_request,
            trusted_operator_handoff,
        ),
        "session_health_gate": {
            "status": internal_readiness.get("status") or "missing",
            "clean": not session_health_issue_ids,
            "issue_ids": session_health_issue_ids,
            "writer_selected_item_can_run": "current_agy_session_health" not in session_health_issue_ids,
            "media_selected_item_can_run": "current_grok_session_health" not in session_health_issue_ids,
            "interpretation": (
                "live_unblock_plan.status describes route/plan readiness; "
                "session_health_gate controls which selected private role-session item may run now."
            ),
        },
        "acceptance_phase": {
            "entered_acceptance": bool(ready_items),
            "status": acceptance_phase_status,
            "final_acceptance_passed": acceptance_phase_status == "accepted",
            "pending_item_ids": [str(item["id"]) for item in pending_returns],
            "next_action": (
                "run_selected_trusted_live_runner_items_then_collect_selected_reports"
                if pending_returns
                else "refresh_promotion_or_human_acceptance_gate"
            ),
            "selected_collect_reports_available": bool(selected_collect),
        },
        "items": items,
        "notes": [
            "This plan contains secret names only, never secret values.",
            "The chat/frontdesk agent submits AgentLab commands and observes artifacts; Writer and ArtifactProducer own the live work.",
            "Generated outputs remain run-local candidates until configured QC and promotion gates pass.",
        ],
    }
