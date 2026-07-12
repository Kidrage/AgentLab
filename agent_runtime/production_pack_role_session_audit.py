"""Audit a production-pack synthesis run without invoking any provider."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

try:
    from outbound_context import PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME
    from production_pack_registry import validate_pack_candidate
    from report_sanitizer import write_report_yaml
except ImportError:  # pragma: no cover - package import path
    from agent_runtime.outbound_context import (
        PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME,
    )
    from agent_runtime.production_pack_registry import validate_pack_candidate
    from agent_runtime.report_sanitizer import write_report_yaml


DEFAULT_PROJECT = "AgentLab"
DEFAULT_TASK_ID = "task_production_pack_role_session_live_20260710"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _check(check_id: str, passed: bool, detail: Any) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "pass" if passed else "fail",
        "detail": detail,
    }


def _outbound_manifest_check(
    role: str,
    manifest: dict[str, Any],
    task_id: str,
) -> dict[str, Any]:
    boundary = manifest.get("context_boundary") or {}
    payload = manifest.get("payload") or {}
    authorization = manifest.get("authorization") or {}
    inventory = manifest.get("source_inventory") or {}
    source_files = inventory.get("files") or []
    sources_valid = bool(source_files) and all(
        isinstance(item, dict)
        and item.get("inside_agentlab_root") is True
        and item.get("exists") is True
        and item.get("is_symlink") is False
        and item.get("forbidden_name") is False
        for item in source_files
    )
    passed = (
        manifest.get("status") == "pass"
        and manifest.get("execution_allowed") is True
        and manifest.get("item_id") == task_id
        and manifest.get("role") == role
        and str(manifest.get("provider_surface") or "").startswith(
            ("cli_agent:", "direct_api:")
        )
        and payload.get("kind")
        in {
            "production_pack_cli_role_session_packet",
            "production_pack_direct_api_messages",
        }
        and payload.get("secret_pattern_hit_count") == 0
        and bool(payload.get("sha256"))
        and boundary.get("private_context") is True
        and boundary.get("sealed_context") is True
        and boundary.get("exact_payload_hashed") is True
        and boundary.get("execution_workspace_isolated") is True
        and boundary.get("provider_project_scan_requested") is False
        and authorization.get("approval_required") is True
        and authorization.get("approval_observed") is True
        and authorization.get("approval_env_name")
        == PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME
        and inventory.get("required") is True
        and sources_valid
        and not manifest.get("issues")
    )
    return _check(
        f"{role.lower()}_outbound_context_governed",
        passed,
        {
            "status": manifest.get("status"),
            "role": manifest.get("role"),
            "provider_surface": manifest.get("provider_surface"),
            "payload_kind": payload.get("kind"),
            "payload_sha256_present": bool(payload.get("sha256")),
            "secret_pattern_hit_count": payload.get("secret_pattern_hit_count"),
            "source_count": inventory.get("count"),
            "source_inventory_required": inventory.get("required"),
            "sources_valid": sources_valid,
            "approval_required": authorization.get("approval_required"),
            "approval_observed": authorization.get("approval_observed"),
            "approval_env_name": authorization.get("approval_env_name"),
            "issues": manifest.get("issues") or [],
        },
    )


def build_production_pack_role_session_audit(
    root: Path,
    *,
    project: str = DEFAULT_PROJECT,
    task_id: str = DEFAULT_TASK_ID,
) -> dict[str, Any]:
    """Require returned role artifacts rather than deterministic scaffold evidence."""
    root = root.resolve()
    run_dir = root / "projects" / project / "runs" / task_id
    paths = {
        "workflow_plan": run_dir / "workflow_plan.yml",
        "mission_contract": run_dir / "mission_contract.yml",
        "lifecycle": run_dir / "lifecycle.yml",
        "supervisor_report": run_dir / "01_supervisor_plan.md",
        "research_brief": run_dir / "domain_research_brief.md",
        "research_contract": run_dir / "production_pack_research_contract.yml",
        "proposal": run_dir / "production_pack_proposal.yml",
        "memory_contract": run_dir / "domain_memory_contract.yml",
        "lifecycle_profile": run_dir / "lifecycle_profile.yml",
        "output_contract": run_dir / "production_pack_output_contract.yml",
        "verifier_report": run_dir / "verification_report.md",
        "verification_receipt": run_dir / "production_pack_verification_receipt.yml",
        "supervisor_manifest": run_dir / "outbound_context_manifest_supervisor.yml",
        "researcher_manifest": run_dir / "outbound_context_manifest_researcher.yml",
        "artifact_producer_manifest": (
            run_dir / "outbound_context_manifest_artifactproducer.yml"
        ),
        "verifier_manifest": run_dir / "outbound_context_manifest_verifier.yml",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    workflow = _read_yaml(paths["workflow_plan"])
    mission = _read_yaml(paths["mission_contract"])
    lifecycle = _read_yaml(paths["lifecycle"])
    research = _read_yaml(paths["research_contract"])
    output = _read_yaml(paths["output_contract"])
    verification = _read_yaml(paths["verification_receipt"])
    manifests = {
        "Supervisor": _read_yaml(paths["supervisor_manifest"]),
        "Researcher": _read_yaml(paths["researcher_manifest"]),
        "ArtifactProducer": _read_yaml(paths["artifact_producer_manifest"]),
        "Verifier": _read_yaml(paths["verifier_manifest"]),
    }
    pack = workflow.get("production_pack") if isinstance(workflow, dict) else {}
    nodes = lifecycle.get("nodes") if isinstance(lifecycle, dict) else {}
    validation = validate_pack_candidate(
        paths["proposal"],
        root / "config" / "production_packs.yml",
    )
    role_nodes = {
        "SUPERVISOR_PLAN": "Supervisor",
        "RESEARCH_OPTIONAL": "Researcher",
        "ARTIFACT_PRODUCTION": "ArtifactProducer",
        "VERIFY": "Verifier",
    }
    role_node_status = (
        {
            role: (nodes.get(node_id) or {}).get("status")
            for node_id, role in role_nodes.items()
        }
        if isinstance(nodes, dict)
        else {}
    )
    output_source = (
        output.get("source") if isinstance(output.get("source"), dict) else {}
    )
    verifier_source = (
        verification.get("verifier")
        if isinstance(verification.get("verifier"), dict)
        else {}
    )
    checks = [
        _check(
            "mission_contract_persisted",
            mission.get("schema_version") == 2
            and mission.get("task_id") == task_id
            and mission.get("project_id") == project
            and mission.get("compiler_source") in {"rule_based", "llm_assisted"}
            and bool((mission.get("route_decision") or {}).get("selected_route")),
            {
                "schema_version": mission.get("schema_version"),
                "task_id": mission.get("task_id"),
                "project_id": mission.get("project_id"),
                "compiler_source": mission.get("compiler_source"),
                "selected_route": (mission.get("route_decision") or {}).get(
                    "selected_route"
                ),
            },
        ),
        _check(
            "synthesis_route_selected",
            isinstance(pack, dict)
            and pack.get("status") == "synthesis_candidate"
            and pack.get("pack_id") == "pack_synthesis_candidate",
            {
                "status": pack.get("status") if isinstance(pack, dict) else None,
                "pack_id": pack.get("pack_id") if isinstance(pack, dict) else None,
            },
        ),
        _check(
            "supervisor_role_session_returned",
            paths["supervisor_report"].is_file()
            and "TBD"
            not in paths["supervisor_report"].read_text(
                encoding="utf-8",
                errors="replace",
            )
            and role_node_status.get("Supervisor") == "completed",
            {
                "report_exists": paths["supervisor_report"].is_file(),
                "lifecycle_status": role_node_status.get("Supervisor"),
            },
        ),
        _check(
            "researcher_role_session_returned",
            research.get("status") == "pass"
            and research.get("execution_mode") == "execute"
            and research.get("provider_returned_research") is True
            and research.get("source_provider") != "fake_provider",
            {
                "status": research.get("status"),
                "execution_mode": research.get("execution_mode"),
                "source_provider": research.get("source_provider"),
            },
        ),
        _check(
            "artifact_producer_returned_exact_outputs",
            output.get("status") == "pass"
            and output.get("provider_returned_outputs") is True
            and output.get("harness_generated_pack_content") is False
            and output_source.get("execution_mode") == "execute"
            and output_source.get("provider") != "fake_provider",
            {
                "status": output.get("status"),
                "materialized_outputs": output.get("materialized_outputs"),
                "source": output_source,
            },
        ),
        _check(
            "pack_registry_validation",
            validation.valid,
            validation.as_dict(),
        ),
        _check(
            "verifier_role_session_returned",
            verification.get("status") == "pass"
            and verification.get("verifier_role_session_returned") is True
            and verifier_source.get("execution_mode") == "execute"
            and verifier_source.get("provider") != "fake_provider",
            {
                "status": verification.get("status"),
                "verifier": verifier_source,
                "issues": verification.get("issues") or [],
            },
        ),
        _check(
            "role_lifecycle_completed",
            bool(role_node_status)
            and all(status == "completed" for status in role_node_status.values()),
            role_node_status,
        ),
        _check(
            "candidate_only_no_promotion",
            output.get("candidate_only") is True
            and output.get("production_modified") is False
            and output.get("promotion_attempted") is False
            and verification.get("candidate_only") is True
            and verification.get("production_modified") is False
            and verification.get("promotion_attempted") is False,
            {
                "output_contract": {
                    "candidate_only": output.get("candidate_only"),
                    "production_modified": output.get("production_modified"),
                    "promotion_attempted": output.get("promotion_attempted"),
                },
                "verification_receipt": {
                    "candidate_only": verification.get("candidate_only"),
                    "production_modified": verification.get("production_modified"),
                    "promotion_attempted": verification.get("promotion_attempted"),
                },
            },
        ),
        *[
            _outbound_manifest_check(role, manifest, task_id)
            for role, manifest in manifests.items()
        ],
    ]
    failures = [item["id"] for item in checks if item["status"] != "pass"]
    run_exists = run_dir.exists()
    if not run_exists or missing:
        status = "candidate"
    elif failures:
        status = "fail"
    else:
        status = "pass"
    return {
        "schema_version": 1,
        "report_type": "agentlab_production_pack_role_session_audit",
        "root": str(root),
        "project": project,
        "task_id": task_id,
        "run_dir": str(run_dir),
        "status": status,
        "evidence_class": "returned_internal_role_session_artifacts",
        "provider_calls_executed_by_audit": False,
        "run_exists": run_exists,
        "required_files": [str(path) for path in paths.values()],
        "missing": missing,
        "checks": checks,
        "failed_checks": failures,
        "candidate_only": True,
        "production_modified": False,
        "promotion_attempted": False,
        "conclusion": (
            "Supervisor, Researcher, ArtifactProducer, and Verifier returned a registry-valid candidate pack."
            if status == "pass"
            else "Returned role-session evidence is not yet complete and accepted."
        ),
    }


def write_production_pack_role_session_audit(
    root: Path,
    out: Path,
    *,
    project: str = DEFAULT_PROJECT,
    task_id: str = DEFAULT_TASK_ID,
) -> dict[str, Any]:
    report = build_production_pack_role_session_audit(
        root,
        project=project,
        task_id=task_id,
    )
    write_report_yaml(out, report, root)
    return report
