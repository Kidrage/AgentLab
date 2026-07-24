from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml
from typer.testing import CliRunner

from agent_runtime.capability_acceptance import (
    _trusted_live_runner_collect,
    _trusted_live_runner_status,
    build_capability_acceptance_report,
)
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def _reason_set(values: list[str]) -> frozenset[str]:
    return frozenset(str(value) for value in values)


def _write_collect_report(root: Path, report: dict) -> None:
    path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_collect.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(report, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _write_status_report(root: Path, report: dict) -> None:
    path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_status.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(report, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _base_collect_report() -> dict:
    return {
        "status": "pass",
        "refreshed_reports": {
            "trusted_live_runner_status": "trusted_live_runner_status.yml",
            "trusted_live_runner_operator_handoff": "trusted_live_runner_operator_handoff.yml",
            "live_unblock_plan": "live_unblock_plan.yml",
            "capability_acceptance": "current.yml",
            "objective_requirement_audit": "objective_requirement_audit.yml",
            "goal_completion_audit": "goal_completion_audit.yml",
            "acceptance_report_hygiene": "acceptance_report_hygiene.yml",
        },
        "secret_values_rendered": False,
        "operator_handoff_status": "ready_for_trusted_runner",
        "trusted_live_runner_status": {"status": "pass", "pending_item_count": 0},
        "pending_items": [],
        "acceptance_blockers": [],
        "acceptance_blocker_reasons": [],
        "returned_candidate_artifacts_accepted_count": 2,
        "acceptance_summary": {
            "acceptance_report_hygiene_canonical_text_artifact_count": 0,
            "acceptance_report_hygiene_canonical_text_issue_count": 0,
            "acceptance_report_hygiene_stale_private_selected_command_hit_count": 0,
        },
    }


def test_trusted_live_runner_status_capability_rejects_pass_report_with_unaccepted_item(
    tmp_path: Path,
) -> None:
    _write_status_report(
        tmp_path,
        {
            "status": "pass",
            "missing_items": [],
            "stale_items": [],
            "artifact_qc_failures": [],
            "items": [
                {
                    "id": "run_crown_internal_writer_eval",
                    "status": "pass",
                    "returned_candidate_artifacts_accepted": True,
                },
                {
                    "id": "run_crown_internal_media_smoke",
                    "status": "pass",
                    "returned_candidate_artifacts_accepted": False,
                },
            ],
        },
    )

    capability = _trusted_live_runner_status(tmp_path)

    assert capability["status"] == "fail"
    assert capability["issues"] == [
        "trusted runner status reports pass, but returned-artifact acceptance invariants are inconsistent"
    ]
    assert capability["details"]["strict_status_pass"] is False
    assert capability["details"]["inconsistent_pass_report"] is True
    assert capability["details"]["accepted_item_count"] == 1
    assert capability["details"]["unaccepted_pass_items"] == [
        {
            "id": "run_crown_internal_media_smoke",
            "returned_candidate_artifacts_accepted": False,
            "acceptance_blocker": "returned_artifacts_not_accepted",
        }
    ]


def test_trusted_live_runner_status_capability_accepts_strict_pass_report(
    tmp_path: Path,
) -> None:
    _write_status_report(
        tmp_path,
        {
            "status": "pass",
            "missing_items": [],
            "stale_items": [],
            "artifact_qc_failures": [],
            "items": [
                {
                    "id": "run_crown_internal_writer_eval",
                    "status": "pass",
                    "returned_candidate_artifacts_accepted": True,
                },
                {
                    "id": "run_crown_internal_media_smoke",
                    "status": "pass",
                    "returned_candidate_artifacts_accepted": True,
                },
            ],
        },
    )

    capability = _trusted_live_runner_status(tmp_path)

    assert capability["status"] == "pass"
    assert capability["issues"] == []
    assert capability["details"]["strict_status_pass"] is True
    assert capability["details"]["inconsistent_pass_report"] is False
    assert capability["details"]["accepted_item_count"] == 2
    assert capability["details"]["unaccepted_pass_items"] == []


def test_trusted_live_runner_collect_capability_rejects_inconsistent_pass_report(
    tmp_path: Path,
) -> None:
    report = _base_collect_report()
    report["trusted_live_runner_status"] = {"status": "pending", "pending_item_count": 1}
    report["returned_candidate_artifacts_accepted_count"] = 1
    _write_collect_report(tmp_path, report)

    capability = _trusted_live_runner_collect(tmp_path)

    assert capability["status"] == "fail"
    assert capability["issues"] == [
        "collector reports pass, but returned-artifact acceptance invariants are inconsistent"
    ]
    assert capability["details"]["strict_acceptance_pass"] is False
    assert capability["details"]["inconsistent_pass_report"] is True


def test_trusted_live_runner_collect_capability_accepts_strict_pass_report(
    tmp_path: Path,
) -> None:
    _write_collect_report(tmp_path, _base_collect_report())

    capability = _trusted_live_runner_collect(tmp_path)

    assert capability["status"] == "pass"
    assert capability["issues"] == []
    assert capability["details"]["strict_acceptance_pass"] is True
    assert capability["details"]["inconsistent_pass_report"] is False


def test_capability_acceptance_report_aggregates_current_evidence(
    private_crown_project_root: Path,
    tmp_path: Path,
) -> None:
    report = build_capability_acceptance_report(private_crown_project_root)
    by_id = {item["id"]: item for item in report["capabilities"]}

    assert report["report_type"] == "agentlab_capability_acceptance"
    assert report["overall_status"] in {"candidate", "warn", "blocked", "fail", "pass"}
    assert by_id["code_factory_orchestration"]["status"] == "pass"
    assert by_id["non_code_code_shell_split"]["status"] == "pass"
    assert by_id["non_code_code_shell_split"]["summary"] == "media code-shell hits=0; code probe hits=3"
    assert by_id["production_pack_synthesis"]["status"] == "pass"
    assert by_id["production_pack_synthesis_smoke"]["status"] == "pass"
    role_session = by_id["production_pack_synthesis_role_session"]
    assert role_session["status"] == "candidate"
    assert role_session["details"]["fresh_run_request_status"] == (
        "ready_for_explicit_approval"
    )
    assert role_session["details"]["fresh_run_role_chain"] == [
        "Supervisor",
        "Researcher",
        "ArtifactProducer",
        "Verifier",
    ]
    assert role_session["details"]["fresh_run_provider_calls_executed"] is False
    assert role_session["details"]["fresh_run_silent_fallback_allowed"] is False
    assert "shell=pack_synthesis_candidate" in by_id["production_pack_synthesis_smoke"]["summary"]
    assert "candidate_pack=synth_" in by_id["production_pack_synthesis_smoke"]["summary"]
    assert "external_resource_boundary=True" in by_id["production_pack_synthesis_smoke"]["summary"]
    assert by_id["production_pack_synthesis_smoke"]["details"]["identity_boundary_status"] == "pass"
    assert by_id["production_pack_synthesis_smoke"]["details"]["synthesis_shell_pack_id"] == "pack_synthesis_candidate"
    assert by_id["production_pack_synthesis_smoke"]["details"]["validated_candidate_pack_id"].startswith("synth_")
    assert by_id["production_pack_synthesis_smoke"]["details"]["validated_candidate_has_governance_contracts"] is True
    assert by_id["production_pack_synthesis_smoke"]["details"]["semantic_check_count"] >= 14
    assert by_id["production_pack_synthesis_smoke"]["details"]["semantic_failures"] == []
    assert by_id["production_pack_synthesis_smoke"]["details"]["external_resource_boundary_pass"] is True
    assert by_id["production_pack_synthesis_smoke"]["details"]["required_resource_semantic_checks"] == [
        "proposal_external_resource_boundary",
        "proposal_resource_contract",
        "research_brief_external_resource_boundary",
    ]
    synthesis_resource_contract = by_id["production_pack_synthesis_smoke"]["details"]["resource_contract"]
    assert synthesis_resource_contract["external_research_requires_approval"] is True
    assert synthesis_resource_contract["external_research_may_not_write_project_memory"] is True
    assert synthesis_resource_contract["evidence_to_memory_promotion_requires_review"] is True
    assert "resource_evidence_ledger" in synthesis_resource_contract["external_research_outputs"]
    assert synthesis_resource_contract["prefer_internal_workers"] is True
    assert synthesis_resource_contract["new_provider_requires_approval"] is True
    assert by_id["core_package_import_stability"]["status"] == "pass"
    assert "package-mode workflow plan builds" in by_id["core_package_import_stability"]["summary"]
    assert by_id["core_package_import_stability"]["details"]["package_import_failures"] == []
    assert by_id["core_package_import_stability"]["details"]["workflow_plan_probe"]["route_key"] == "interface_sensitive_task"
    assert by_id["core_package_import_stability"]["details"]["workflow_plan_probe"]["production_pack_id"] == "code_factory"
    assert by_id["production_chain_visibility"]["status"] == "pass"
    assert "agent_lifecycle_coverage=pass" in by_id["production_chain_visibility"]["summary"]
    assert by_id["production_chain_visibility"]["details"]["agent_lifecycle_coverage_pass"] is True
    assert by_id["production_chain_visibility"]["details"]["lifecycle_coverage_failures"] == []
    assert by_id["agent_role_chain_consistency"]["status"] == "pass"
    assert "agent_lifecycle_coverage=pass" in by_id["agent_role_chain_consistency"]["summary"]
    assert by_id["agent_role_chain_consistency"]["details"]["agent_lifecycle_coverage_pass"] is True
    assert by_id["agent_role_chain_consistency"]["details"]["lifecycle_coverage_failures"] == []
    assert by_id["frontdesk_role_worker_boundary"]["status"] == "pass"
    assert "frontdesk boundary audit" in by_id["frontdesk_role_worker_boundary"]["summary"]
    assert "live_handoff=ready_for_agentlab_submission" in by_id["frontdesk_role_worker_boundary"]["summary"]
    assert "hermes_frontdesk=True" in by_id["frontdesk_role_worker_boundary"]["summary"]
    assert "direct_closed_loop=True" in by_id["frontdesk_role_worker_boundary"]["summary"]
    assert "codex_external_worker=True" in by_id["frontdesk_role_worker_boundary"]["summary"]
    assert by_id["frontdesk_role_worker_boundary"]["details"]["hermes_frontdesk_check"] == "pass"
    assert by_id["frontdesk_role_worker_boundary"]["details"]["direct_closed_loop_check"] == "pass"
    assert by_id["frontdesk_role_worker_boundary"]["details"]["codex_external_worker_check"] == "pass"
    assert by_id["frontdesk_role_worker_boundary"]["details"]["workflow_shell_registry_check"] == "pass"
    assert any(path.endswith("frontdesk_live_handoff.yml") for path in by_id["frontdesk_role_worker_boundary"]["evidence"])
    assert by_id["cli_workflow_shell_absorption"]["status"] == "pass"
    assert "Full CLI mode governs native CLI shell capability" in by_id[
        "cli_workflow_shell_absorption"
    ]["summary"]
    assert by_id["cli_workflow_shell_absorption"]["details"]["worker_capability_ok"] is True
    assert by_id["cli_workflow_shell_absorption"]["details"]["contract_shell_ok"] is True
    assert by_id["cli_workflow_shell_absorption"]["details"]["delivery_contracts_ok"] is True
    assert by_id["cli_workflow_shell_absorption"]["details"]["mode_policy_ok"] is True
    assert by_id["cli_workflow_shell_absorption"]["details"]["media_shell_ok"] is True
    assert by_id["cli_workflow_shell_absorption"]["details"]["boundary_ok"] is True
    assert set(by_id["cli_workflow_shell_absorption"]["details"]["full_cli_shells"]) == {
        "agy",
        "claude_code",
        "codex",
        "grok",
        "hermes",
        "qwen",
    }
    assert by_id["cli_native_command_surface_governance"]["status"] == "pass"
    assert "hermes_kanban_registered=True" in by_id["cli_native_command_surface_governance"]["summary"]
    assert "claude_subagents_registered=True" in by_id["cli_native_command_surface_governance"]["summary"]
    assert by_id["cli_native_command_surface_governance"]["details"]["inventory_policy_ok"] is True
    assert by_id["cli_native_command_surface_governance"]["details"]["lifecycle_boundary_ok"] is True
    assert by_id["cli_native_command_surface_governance"]["details"]["hermes_kanban_registered"] is True
    assert by_id["cli_native_command_surface_governance"]["details"]["claude_subagents_registered"] is True
    assert by_id["cli_native_command_surface_governance"]["details"][
        "cross_lifecycle_gate_coalescing"
    ] == "forbidden"
    assert by_id["cli_native_command_surface_governance"]["details"]["synthetic_runtime_removed"] is True
    assert "synthetic_runtime_removed=True" in by_id[
        "cli_native_command_surface_governance"
    ]["summary"]
    assert not {
        "cli_shell_coalesced_runner_implementation",
        "cli_shell_coalesced_runner_request",
        "cli_shell_coalesced_collect",
        "cli_shell_coalesced_session_returns",
    } & set(by_id)
    assert by_id["live_code_candidate_materialization"]["status"] in {"candidate", "pass"}
    assert (
        "responsive viewport evidence" in by_id["live_code_candidate_materialization"]["summary"]
        or "promoted to production" in by_id["live_code_candidate_materialization"]["summary"]
    )
    assert by_id["crown_live_writer_light_path"]["status"] == "candidate"
    assert "local candidate audit" in by_id["crown_live_writer_light_path"]["summary"]
    assert by_id["crown_live_writer_light_path"]["issues"] == [
        "run-local chapter candidate is not formal trusted-runner live acceptance or production promotion"
    ]
    assert by_id["crown_live_writer_light_path"]["details"]["candidate_only"] is True
    assert by_id["crown_live_writer_light_path"]["details"]["formal_trusted_runner_acceptance_required"] is True
    assert by_id["crown_formal_live_narrative_eval"]["status"] in {
        "candidate",
        "pass",
    }
    assert "internal Writer role-session" in by_id["crown_formal_live_narrative_eval"]["summary"]
    assert any(
        path.endswith("worker_invocation_contracts.yml")
        for path in by_id["crown_formal_live_narrative_eval"]["evidence"]
    )
    formal_eval = by_id["crown_formal_live_narrative_eval"]
    if formal_eval["status"] == "pass":
        assert "accepted trusted-runner Writer artifacts" in formal_eval["summary"]
        assert formal_eval["issues"] == []
        assert formal_eval["details"]["returned_artifacts_pending"] is False
        assert formal_eval["details"]["returned_artifacts_accepted"] is True
    else:
        assert formal_eval["details"]["returned_artifacts_pending"] is True
        assert formal_eval["details"]["returned_artifacts_accepted"] is False
    assert by_id["crown_formal_live_narrative_eval"]["details"]["trusted_runner_item"] == "run_crown_internal_writer_eval"
    writer_route = by_id["crown_formal_live_narrative_eval"]["details"][
        "internal_writer_route"
    ]
    assert writer_route["worker"] == "agy"
    assert writer_route["invocation_contract"] == "agy_writer"
    assert writer_route["model_key"] == "gemini_3_5_flash_high_agy_oauth"
    assert writer_route["model_provider"] == "agy_gemini_oauth"
    assert by_id["crown_heavy_audit_scale"]["status"] == "pass"
    assert "governance-scale audit passes" in by_id["crown_heavy_audit_scale"]["summary"]
    assert by_id["media_series_scaffold"]["status"] == "pass"
    assert "safe backend" in by_id["media_series_scaffold"]["summary"]
    assert by_id["grok_xai_media_backend"]["status"] == "candidate"
    assert "ArtifactProducer/grok" in by_id["grok_xai_media_backend"]["summary"]
    assert "historical non-private authenticated smoke pass" not in by_id["grok_xai_media_backend"]["summary"]
    assert "auth_status=" in by_id["grok_xai_media_backend"]["summary"]
    assert by_id["grok_xai_media_backend"]["details"]["worker_id"] == "grok"
    assert by_id["grok_xai_media_backend"]["details"]["role_owner"] == "ArtifactProducer"
    assert by_id["grok_xai_media_backend"]["details"]["internal_worker"] is True
    assert by_id["grok_xai_media_backend"]["details"]["researcher_grok_binding"] is True
    assert by_id["grok_xai_media_backend"]["details"]["artifact_producer_grok_binding"] is True
    assert by_id["grok_xai_media_backend"]["details"]["grok_invocation_contract_ready"] is True
    assert by_id["grok_xai_media_backend"]["details"]["grok_research_contract_ready"] is True
    assert by_id["grok_xai_media_backend"]["details"]["grok_media_contract_ready"] is True
    assert by_id["grok_xai_media_backend"]["details"]["grok_research_command"] == "hermes"
    assert by_id["grok_xai_media_backend"]["details"]["grok_media_command"] == "hermes"
    assert by_id["grok_xai_media_backend"]["details"]["grok_invocation_command"] == "hermes"
    assert by_id["grok_xai_media_backend"]["details"]["grok_backend_command"] == "hermes"
    assert by_id["grok_xai_media_backend"]["details"]["grok_research_invocation_style"] == "sourced_research_task_packet"
    assert by_id["grok_xai_media_backend"]["details"]["grok_invocation_style"] == "media_backend_task_packet"
    assert by_id["grok_xai_media_backend"]["details"]["execution_kernel"] == "hermes_workflow_shell"
    assert by_id["grok_xai_media_backend"]["details"]["orchestration_scope"] == "bounded_role_session_backend"
    assert by_id["grok_xai_media_backend"]["details"]["workflow_shell_registry"] == "config/cli_workflow_shells.yml"
    assert "structured_output_and_qc" in by_id["grok_xai_media_backend"]["details"][
        "workflow_shell_capability_families"
    ]
    assert by_id["grok_xai_media_backend"]["details"]["local_cli_entrypoint_available"] is True
    assert by_id["grok_xai_media_backend"]["details"]["local_cli_entrypoint_is_internal_worker"] is True
    assert by_id["grok_xai_media_backend"]["details"]["local_cli_requires_api_key"] is False
    assert by_id["grok_xai_media_backend"]["details"]["non_interactive_prompt_contract_status"] in {"pass", "blocked"}
    assert by_id["grok_xai_media_backend"]["details"]["session_auth_status"] in {
        "authenticated",
        "not_authenticated",
        "unknown",
    }
    assert by_id["grok_xai_media_backend"]["details"]["session_auth_evidence"] in {
        "authenticated_diagnostics",
        "pass_without_auth_diagnostics",
        "not_authenticated_marker",
        "diagnostics_not_healthy",
        "unknown",
    }
    assert isinstance(by_id["grok_xai_media_backend"]["details"]["session_auth_healthy"], bool)
    assert isinstance(by_id["grok_xai_media_backend"]["details"]["session_auth_diagnostic_reported"], bool)
    if by_id["grok_xai_media_backend"]["details"]["session_smoke_status"] == "pass":
        assert by_id["grok_xai_media_backend"]["details"]["session_auth_evidence"] in {
            "authenticated_diagnostics",
            "pass_without_auth_diagnostics",
        }
        assert by_id["grok_xai_media_backend"]["details"]["session_auth_healthy"] is True
    assert isinstance(by_id["grok_xai_media_backend"]["details"]["session_model_catalog_visible"], bool)
    assert isinstance(by_id["grok_xai_media_backend"]["details"]["session_not_authenticated_marker_present"], bool)
    if by_id["grok_xai_media_backend"]["details"]["non_interactive_prompt_contract_status"] == "blocked":
        assert by_id["grok_xai_media_backend"]["details"]["session_smoke_reason"]
    else:
        assert "session_smoke_reason" not in by_id["grok_xai_media_backend"]["details"]
    assert by_id["grok_xai_media_backend"]["details"]["session_smoke_status"] in {"pass", "blocked"}
    assert by_id["grok_xai_media_backend"]["details"]["text_handoff_counts_as_media_artifact"] is False
    assert by_id["grok_xai_media_backend"]["details"]["local_cli_asset_return_contract_ready"] is True
    assert by_id["grok_xai_media_backend"]["details"]["local_cli_asset_return_marker"] == "AGENTLAB_GENERATED_ASSET:"
    assert by_id["grok_xai_media_backend"]["details"]["local_cli_selection_requires_registered_backend_command"] is True
    assert by_id["grok_xai_media_backend"]["details"]["direct_api_key_path_is_fallback_only"] is True
    assert by_id["grok_xai_media_backend"]["details"]["media_acceptance_requires_generated_assets"] is True
    assert any("text handoff does not satisfy" in issue for issue in by_id["grok_xai_media_backend"]["issues"])
    assert by_id["internal_live_readiness"]["status"] in {"pass", "candidate"}
    assert by_id["internal_live_readiness"]["legacy_ids"] == ["external_acceptance_readiness"]
    assert any(
        path.endswith("internal_live_readiness.yml")
        for path in by_id["internal_live_readiness"]["evidence"]
    )
    assert "internal live readiness status=" in by_id["internal_live_readiness"]["summary"]
    assert "ready_items=2" in by_id["internal_live_readiness"]["summary"]
    assert "session_health_issues=" in by_id["internal_live_readiness"]["summary"]
    assert "policy_rejections=0" in by_id["internal_live_readiness"]["summary"]
    assert by_id["internal_live_unblock_plan"]["status"] == "pass"
    assert "acceptance_phase=in_acceptance_pending_returned_artifacts" in by_id["internal_live_unblock_plan"]["summary"]
    assert "final_acceptance_passed=False" in by_id["internal_live_unblock_plan"]["summary"]
    assert by_id["internal_live_unblock_plan"]["details"]["acceptance_phase"]["entered_acceptance"] is True
    assert by_id["internal_live_unblock_plan"]["details"]["acceptance_phase"]["final_acceptance_passed"] is False
    unblock_items = {
        item["id"]: item for item in by_id["internal_live_unblock_plan"]["details"]["items"]
    }
    writer_return = unblock_items["run_crown_internal_writer_eval"]["current_return"]
    assert writer_return["selected_item_collect_status"] == (
        "pass"
        if writer_return["returned_candidate_artifacts_accepted"]
        else "pending_selected_item"
    )
    assert unblock_items["run_crown_internal_writer_eval"]["trusted_runner_command"].endswith(
        "--only run_crown_internal_writer_eval"
    )
    assert "--item run_crown_internal_writer_eval" in unblock_items[
        "run_crown_internal_writer_eval"
    ]["selected_collect_command"]
    request_details = by_id["trusted_live_runner_request"]["details"]
    expected_request_status = (
        "pass"
        if request_details["writer_route_current"]
        and request_details["preflight_writer_route_current"]
        else "fail"
    )
    assert by_id["trusted_live_runner_request"]["status"] == expected_request_status
    assert "items=2" in by_id["trusted_live_runner_request"]["summary"]
    assert "local_runner_package=True" in by_id["trusted_live_runner_request"]["summary"]
    assert "session_health_gate=True" in by_id["trusted_live_runner_request"]["summary"]
    assert "approval_gate=True" in by_id["trusted_live_runner_request"]["summary"]
    assert "full_run_requires_trusted_status_pass=True" in by_id["trusted_live_runner_request"]["summary"]
    assert "post_run_collect=True" in by_id["trusted_live_runner_request"]["summary"]
    assert by_id["trusted_live_runner_request"]["details"]["full_run_requires_trusted_status_pass"] is True
    assert by_id["trusted_live_runner_request"]["details"]["full_run_executes_session_health_checks"] is True
    assert by_id["trusted_live_runner_request"]["details"]["refreshes_status_after_run"] is True
    assert by_id["trusted_live_runner_request"]["details"]["refreshes_acceptance_after_run"] is True
    assert by_id["trusted_live_runner_request"]["details"]["approval_gate_before_private_context"] is True
    assert (
        by_id["trusted_live_runner_request"]["details"]["role_session_acceptance_approval_env_required"]
        == "AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1"
    )
    operator_handoff = by_id["trusted_live_runner_operator_handoff"]
    if operator_handoff["details"]["writer_request_route_current"]:
        assert operator_handoff["status"] in {"pass", "candidate"}
    else:
        assert operator_handoff["status"] == "fail"
        assert operator_handoff["issues"] == [
            "trusted live runner operator handoff missing, unsafe, or incomplete"
        ]
    assert "operator handoff status=" in operator_handoff["summary"]
    assert "approval_gate=True" in operator_handoff["summary"]
    assert operator_handoff["details"]["trusted_agentlab_runner_required"] is True
    assert (
        by_id["trusted_live_runner_operator_handoff"]["details"]["acceptance_smoke_kind"]
        == "private_role_session_acceptance_smoke"
    )
    assert by_id["trusted_live_runner_operator_handoff"]["details"]["trusted_runner_or_user_terminal_required"] is True
    assert (
        by_id["trusted_live_runner_operator_handoff"]["details"]["approval_gate_before_private_context"]
        is True
    )
    assert (
        by_id["trusted_live_runner_operator_handoff"]["details"][
            "role_session_acceptance_approval_env_required"
        ]
        == "AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1"
    )
    assert isinstance(by_id["trusted_live_runner_operator_handoff"]["details"]["non_private_session_health_clean"], bool)
    assert "session_health_issues=" in by_id["trusted_live_runner_operator_handoff"]["summary"]
    selected_readiness = by_id["trusted_live_runner_operator_handoff"]["details"][
        "selected_item_readiness"
    ]
    if by_id["trusted_live_runner_operator_handoff"]["details"]["non_private_session_health_clean"] is False:
        assert by_id["trusted_live_runner_operator_handoff"]["details"]["session_health_status"] == "route_ready_session_blocked"
        assert by_id["trusted_live_runner_operator_handoff"]["details"]["session_health_issue_count"] >= 1
        assert by_id["trusted_live_runner_operator_handoff"]["details"]["session_health_issue_reasons"]
        assert by_id["trusted_live_runner_operator_handoff"]["details"]["session_health_next_action"] == (
            "rerun_session_health_from_trusted_runtime_before_role_session_acceptance_smoke"
        )
        assert "selected_ready=" in by_id["trusted_live_runner_operator_handoff"]["summary"]
        assert "selected_blocked=" in by_id["trusted_live_runner_operator_handoff"]["summary"]
        assert selected_readiness["blocked_item_ids"]
        for item_id in selected_readiness["blocked_item_ids"]:
            assert selected_readiness["items"][item_id]["can_run_now"] is False
            assert selected_readiness["items"][item_id]["blocked_by_session_health"] is True
    else:
        assert "selected_ready=run_crown_internal_writer_eval" in by_id[
            "trusted_live_runner_operator_handoff"
        ]["summary"]
        assert "run_crown_internal_media_smoke" in by_id[
            "trusted_live_runner_operator_handoff"
        ]["summary"]
        assert "selected_blocked=none" in by_id[
            "trusted_live_runner_operator_handoff"
        ]["summary"]
        assert selected_readiness["ready_item_ids"] == [
            "run_crown_internal_writer_eval",
            "run_crown_internal_media_smoke",
        ]
        assert selected_readiness["blocked_item_ids"] == []
        assert selected_readiness["items"]["run_crown_internal_writer_eval"]["can_run_now"] is True
        assert selected_readiness["items"]["run_crown_internal_media_smoke"]["can_run_now"] is True
    assert by_id["trusted_live_runner_preflight"]["status"] == "pass"
    assert "provider_calls=False" in by_id["trusted_live_runner_preflight"]["summary"]
    assert by_id["trusted_live_runner_status"]["status"] == "candidate"
    assert "missing_items=" in by_id["trusted_live_runner_status"]["summary"]
    assert "stale_items=" in by_id["trusted_live_runner_status"]["summary"]
    assert "artifact_qc_failures=" in by_id["trusted_live_runner_status"]["summary"]
    assert "acceptance_blockers=missing_required_files" in by_id["trusted_live_runner_status"]["summary"]
    assert by_id["trusted_live_runner_status"]["details"]["acceptance_blockers"] in (
        ["missing_required_files"],
        ["missing_required_files", "observed_execution_error_or_stale_ledger"],
    )
    trusted_status_pending = {
        item["id"]: item for item in by_id["trusted_live_runner_status"]["details"]["pending_items"]
    }
    if "run_crown_internal_writer_eval" not in trusted_status_pending:
        assert trusted_status_pending["run_crown_internal_media_smoke"][
            "returned_candidate_artifacts_accepted"
        ] is False
        collect_details = by_id["trusted_live_runner_collect"]["details"]
        assert collect_details["required_files_missing_count"] == 3
        assert collect_details["returned_candidate_artifacts_accepted_count"] == 1
        assert collect_details["next_action"] == (
            "scoped_acceptance_complete_deferred_media_pending"
        )
        writer_selected = collect_details["selected_item_summaries"][
            "run_crown_internal_writer_eval"
        ]
        assert writer_selected["selected_item_collect_status"] == "pass"
        assert writer_selected["selected_item_accepted"] is True
        return
    assert trusted_status_pending["run_crown_internal_writer_eval"]["required_files_exist"] is False
    assert trusted_status_pending["run_crown_internal_writer_eval"]["returned_candidate_artifacts_accepted"] is False
    assert trusted_status_pending["run_crown_internal_writer_eval"]["acceptance_blocker"] == "missing_required_files"
    assert trusted_status_pending["run_crown_internal_media_smoke"]["returned_candidate_artifacts_accepted"] is False
    if trusted_status_pending["run_crown_internal_media_smoke"]["required_files_exist"] is False:
        assert trusted_status_pending["run_crown_internal_media_smoke"]["acceptance_blocker"] == "missing_required_files"
    else:
        assert (
            trusted_status_pending["run_crown_internal_media_smoke"]["acceptance_blocker"]
            == "observed_execution_error_or_stale_ledger"
        )
    assert by_id["trusted_live_runner_collect"]["status"] == "candidate"
    assert "trusted runner collect status=pending_returned_artifacts" in by_id["trusted_live_runner_collect"]["summary"]
    assert "hygiene_text_artifacts=2" in by_id["trusted_live_runner_collect"]["summary"]
    assert "hygiene_text_issues=0" in by_id["trusted_live_runner_collect"]["summary"]
    assert tuple(by_id["trusted_live_runner_collect"]["issues"]) in {
        (
            "collector refreshed reports, but returned role-session acceptance artifacts are not accepted yet",
        ),
        (
            "collector refreshed reports, but non-private session health still needs attention",
        ),
    }
    assert "acceptance_blockers=missing_required_files" in by_id["trusted_live_runner_collect"]["summary"]
    assert (
        "acceptance_blocker_reasons=missing_candidate_artifacts"
        in by_id["trusted_live_runner_collect"]["summary"]
        or (
        "acceptance_blocker_reasons=claude_writer_session_health_blocked_before_private_writer_smoke,"
        "missing_candidate_artifacts"
        in by_id["trusted_live_runner_collect"]["summary"]
        )
        or (
        "acceptance_blocker_reasons=grok_cli_transport_or_proxy_failed_in_live_smoke,missing_candidate_artifacts"
        in by_id["trusted_live_runner_collect"]["summary"]
        )
        or (
            "acceptance_blocker_reasons=media_live_artifacts_not_rerun_after_grok_session_pass,"
            "missing_candidate_artifacts"
            in by_id["trusted_live_runner_collect"]["summary"]
        )
        or (
            "acceptance_blocker_reasons=claude_writer_session_health_blocked_before_private_writer_smoke,"
            "grok_cli_transport_or_proxy_failed_in_live_smoke"
            in by_id["trusted_live_runner_collect"]["summary"]
        )
    )
    assert by_id["trusted_live_runner_collect"]["details"]["acceptance_blockers"] in (
        ["missing_required_files"],
        ["missing_required_files", "observed_execution_error_or_stale_ledger"],
    )
    assert _reason_set(by_id["trusted_live_runner_collect"]["details"]["acceptance_blocker_reasons"]) in {
        frozenset({
            "missing_candidate_artifacts",
        }),
        frozenset({
            "claude_writer_session_health_blocked_before_private_writer_smoke",
            "missing_candidate_artifacts",
        }),
        frozenset({
            "grok_cli_transport_or_proxy_failed_in_live_smoke",
            "missing_candidate_artifacts",
        }),
        frozenset({
            "media_live_artifacts_not_rerun_after_grok_session_pass",
            "missing_candidate_artifacts",
        }),
        frozenset({
            "claude_writer_session_health_blocked_before_private_writer_smoke",
            "grok_cli_transport_or_proxy_failed_in_live_smoke",
        }),
    }
    assert by_id["trusted_live_runner_collect"]["details"]["required_files_missing_count"] >= 5
    assert by_id["trusted_live_runner_collect"]["details"]["returned_candidate_artifacts_accepted_count"] == 0
    assert (
        by_id["trusted_live_runner_collect"]["details"][
            "acceptance_report_hygiene_canonical_text_artifact_count"
        ]
        == 2
    )
    assert (
        by_id["trusted_live_runner_collect"]["details"][
            "acceptance_report_hygiene_canonical_text_issue_count"
        ]
        == 0
    )
    assert (
        by_id["trusted_live_runner_collect"]["details"][
            "acceptance_report_hygiene_stale_private_selected_command_hit_count"
        ]
        == 0
    )
    assert "hygiene_private_selected_command_hits=0" in by_id["trusted_live_runner_collect"][
        "summary"
    ]
    assert by_id["trusted_live_runner_collect"]["details"]["next_action"] == "run_writer_selected_item_only"
    assert "trusted_live_runner_status" in by_id["trusted_live_runner_collect"]["details"]["refreshed_reports"]
    assert "live_unblock_plan" in by_id["trusted_live_runner_collect"]["details"]["refreshed_reports"]
    assert by_id["trusted_live_runner_collect"]["details"]["selected_item_report_paths"] == {
        "run_crown_internal_writer_eval": (
            "acceptance_runs/agentlab_capability_acceptance/trusted_live_runner_collect_writer.yml"
        ),
        "run_crown_internal_media_smoke": (
            "acceptance_runs/agentlab_capability_acceptance/trusted_live_runner_collect_media.yml"
        ),
    }
    selected_summaries = by_id["trusted_live_runner_collect"]["details"]["selected_item_summaries"]
    assert selected_summaries["run_crown_internal_writer_eval"]["selected_item_collect_status"] == (
        "pending_selected_item"
    )
    assert selected_summaries["run_crown_internal_writer_eval"]["selected_item_accepted"] is False
    assert selected_summaries["run_crown_internal_media_smoke"]["selected_item_collect_status"] == (
        "pending_selected_item"
    )
    assert selected_summaries["run_crown_internal_media_smoke"]["selected_item_accepted"] is False
    assert by_id["provider_reachability"]["status"] in {"pass", "candidate", "blocked"}
    assert any(path.endswith("provider_smoke_current.yml") for path in by_id["provider_reachability"]["evidence"])
    assert "finish_reason" in by_id["provider_reachability"]["details"]
    assert "raw_usage_keys" in by_id["provider_reachability"]["details"]

    out = tmp_path / "capability_acceptance.yml"

    with patch(
        "capability_acceptance.build_capability_acceptance_report",
        return_value=report,
    ):
        result = runner.invoke(app, ["capability-acceptance", "--out", str(out)])

    assert out.exists()
    written = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert result.exit_code == (1 if report["overall_status"] == "fail" else 0)
    assert written["report_type"] == "agentlab_capability_acceptance"
    assert "code_factory_orchestration" in {item["id"] for item in written["capabilities"]}
