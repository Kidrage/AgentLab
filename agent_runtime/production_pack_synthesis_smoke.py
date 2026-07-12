"""Offline smoke test for production-pack synthesis artifacts."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import yaml

_RUNTIME_ROOT = Path(__file__).resolve().parent
if str(_RUNTIME_ROOT) not in sys.path:
    sys.path.insert(1, str(_RUNTIME_ROOT))

try:
    from atomic_io import atomic_write_yaml
    from pipeline_runner import _write_pack_candidate_outputs, _write_synthesis_domain_research_brief
    from production_pack_registry import validate_pack_candidate
    from report_sanitizer import write_report_yaml
    from workflow_plan import build_workflow_plan
except ImportError:  # pragma: no cover - package import path
    from agent_runtime.atomic_io import atomic_write_yaml
    from agent_runtime.pipeline_runner import _write_pack_candidate_outputs, _write_synthesis_domain_research_brief
    from agent_runtime.production_pack_registry import validate_pack_candidate
    from agent_runtime.report_sanitizer import write_report_yaml
    from agent_runtime.workflow_plan import build_workflow_plan


DEFAULT_TASK_ID = "task_production_pack_synthesis_smoke_20260707"
DEFAULT_REQUEST = (
    "设计一个沉浸式气味剧场装置生产流程，需要长期维护观众动线、气味提示、"
    "安全验收、场次状态和多轮生成产物。"
)


def _write_plan(run_dir: Path, plan: Any) -> None:
    data = plan.model_dump(mode="json") if hasattr(plan, "model_dump") else dict(plan)
    atomic_write_yaml(run_dir / "workflow_plan.yml", data, sort_keys=False, allow_unicode=True)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _check(condition: bool, check_id: str, detail: str) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "pass" if condition else "fail",
        "detail": detail,
    }


def _semantic_checks(run_dir: Path, validation: Any, missing: list[str]) -> list[dict[str, Any]]:
    brief_text = (run_dir / "domain_research_brief.md").read_text(encoding="utf-8") if (
        run_dir / "domain_research_brief.md"
    ).exists() else ""
    proposal = _read_yaml(run_dir / "production_pack_proposal.yml")
    memory = _read_yaml(run_dir / "domain_memory_contract.yml")
    lifecycle = _read_yaml(run_dir / "lifecycle_profile.yml")
    pack = validation.pack if getattr(validation, "pack", None) else {}
    resource_contract = pack.get("resource_contract") if isinstance(pack, dict) else {}
    promotion_policy = pack.get("promotion_policy") if isinstance(pack, dict) else {}

    required_memory = {
        "domain_state_snapshot",
        "artifact_index",
        "generation_or_revision_ledger",
        "delivery_receipt",
    }
    required_lifecycle = {
        "INIT_TASK",
        "CONTEXT_PROFILE",
        "CONTEXT_PACK",
        "SUPERVISOR_PLAN",
        "RESEARCH_OPTIONAL",
        "ARTIFACT_PRODUCTION",
        "VERIFY",
        "FINALIZE",
    }
    quality_gates = set(pack.get("quality_gates") or []) if isinstance(pack, dict) else set()
    checks = [
        _check(not missing, "required_files_present", f"missing={missing}"),
        _check(bool(getattr(validation, "valid", False)), "proposal_shape_valid", "candidate proposal validates"),
        _check(
            "## Resource Discovery Contract" in brief_text
            and "registered_role_workers" in brief_text
            and "evidence_ledger_required" in brief_text
            and "memory_promotion_boundary" in brief_text
            and "authority_boundary" in brief_text,
            "research_brief_resource_contract",
            "brief records resource discovery, evidence ledger, and authority boundary",
        ),
        _check(
            "optional_external_research: evidence gathering only after approval" in brief_text
            and "external research may inform a proposal but does not become project memory" in brief_text,
            "research_brief_external_resource_boundary",
            "brief records approved external research as informative evidence only",
        ),
        _check(
            "## Promotion Boundary" in brief_text
            and "candidate_only: true" in brief_text
            and "production_modified: false" in brief_text,
            "research_brief_promotion_boundary",
            "brief records candidate-only promotion boundary",
        ),
        _check(
            isinstance(resource_contract, dict)
            and resource_contract.get("resource_discovery_required") is True
            and resource_contract.get("prefer_internal_workers") is True
            and resource_contract.get("new_provider_requires_approval") is True,
            "proposal_resource_contract",
            "pack proposal requires resource discovery and prefers internal workers",
        ),
        _check(
            isinstance(resource_contract, dict)
            and "approved_external_research" in set(resource_contract.get("allowed_sources") or [])
            and resource_contract.get("external_research_requires_approval") is True
            and resource_contract.get("external_research_may_not_write_project_memory") is True
            and resource_contract.get("evidence_to_memory_promotion_requires_review") is True
            and "resource_evidence_ledger" in set(resource_contract.get("external_research_outputs") or []),
            "proposal_external_resource_boundary",
            "external research is allowed only as approved run-local evidence before memory review",
        ),
        _check(
            isinstance(promotion_policy, dict)
            and promotion_policy.get("auto_promote") is False
            and promotion_policy.get("candidate_only") is True
            and promotion_policy.get("production_modified") is False,
            "proposal_promotion_policy",
            "pack proposal forbids automatic promotion",
        ),
        _check(
            required_memory.issubset(set(pack.get("memory_contract") or []))
            and required_memory.issubset(set(memory.get("memory_contract") or [])),
            "memory_contract_closed_loop",
            "proposal and memory contract include the reusable state records",
        ),
        _check(
            "run-local" in str(memory.get("candidate_fact_policy", ""))
            and memory.get("promotion_policy", {}).get("candidate_facts_remain_run_local") is True,
            "candidate_fact_boundary",
            "new facts remain run-local until promotion",
        ),
        _check(
            required_lifecycle.issubset(set(pack.get("lifecycle_nodes") or []))
            and "CODER_IMPLEMENTATION" in set(lifecycle.get("forbidden_nodes") or []),
            "lifecycle_excludes_code_shell",
            "non-code synthesis lifecycle includes production nodes and forbids coder implementation",
        ),
        _check(
            {
                "resource_discovery_reviewed",
                "candidate_fact_boundary_enforced",
                "approval_before_promotion",
            }.issubset(quality_gates),
            "quality_gates_cover_governance",
            "quality gates cover resource discovery, fact boundary, and promotion",
        ),
        _check(
            proposal.get("candidate_only") is True and proposal.get("production_modified") is False,
            "proposal_candidate_only",
            "proposal is candidate-only and does not modify production",
        ),
    ]
    return checks


def _pack_identity_boundary(shell_pack: dict[str, Any], validation: Any) -> dict[str, Any]:
    validation_pack = validation.pack if getattr(validation, "pack", None) else {}
    shell_pack_id = shell_pack.get("pack_id") if isinstance(shell_pack, dict) else None
    candidate_pack_id = validation_pack.get("pack_id") if isinstance(validation_pack, dict) else None
    shell_status = shell_pack.get("status") if isinstance(shell_pack, dict) else None
    candidate_has_governance_contracts = (
        isinstance(validation_pack, dict)
        and isinstance(validation_pack.get("resource_contract"), dict)
        and isinstance(validation_pack.get("promotion_policy"), dict)
        and bool(validation_pack.get("memory_contract"))
    )
    return {
        "status": "pass"
        if shell_status == "synthesis_candidate"
        and shell_pack_id == "pack_synthesis_candidate"
        and bool(candidate_pack_id)
        and candidate_pack_id != shell_pack_id
        and candidate_has_governance_contracts
        else "fail",
        "synthesis_shell_pack_id": shell_pack_id,
        "synthesis_shell_status": shell_status,
        "validated_candidate_pack_id": candidate_pack_id,
        "validated_candidate_has_governance_contracts": candidate_has_governance_contracts,
        "interpretation": (
            "production_pack is the generic synthesis shell; validated_candidate_pack "
            "is the generated pack proposal that proves resource, memory, and promotion governance."
        ),
    }


def run_production_pack_synthesis_smoke(
    root: Path,
    *,
    project: str = "AgentLab",
    task_id: str = DEFAULT_TASK_ID,
    request: str = DEFAULT_REQUEST,
    out: Path | None = None,
) -> dict[str, Any]:
    """Generate and validate synthesis candidate artifacts without promotion."""
    root = root.resolve()
    run_dir = root / "projects" / project / "runs" / task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    request_path = run_dir / "user_request.md"
    request_path.write_text(request, encoding="utf-8")

    plan = build_workflow_plan(root, project, task_id, user_request_path=request_path)
    _write_plan(run_dir, plan)

    brief = _write_synthesis_domain_research_brief(
        run_dir,
        source_report=None,
        execution_mode="smoke",
    )
    written_outputs = _write_pack_candidate_outputs(
        run_dir,
        project,
        task_id,
        execution_mode="smoke",
    )

    proposal_path = run_dir / "production_pack_proposal.yml"
    validation = validate_pack_candidate(
        proposal_path,
        root / "config" / "production_packs.yml",
    )
    required = [
        "domain_research_brief.md",
        "production_pack_proposal.yml",
        "domain_memory_contract.yml",
        "lifecycle_profile.yml",
    ]
    missing = [item for item in required if not (run_dir / item).exists()]
    semantic_checks = _semantic_checks(run_dir, validation, missing)
    identity_boundary = _pack_identity_boundary(plan.production_pack, validation)
    semantic_checks.append(
        _check(
            identity_boundary.get("status") == "pass",
            "pack_identity_boundary",
            "report distinguishes the generic synthesis shell from the validated candidate pack",
        )
    )
    semantic_failures = [check for check in semantic_checks if check.get("status") != "pass"]
    validation_dict = validation.as_dict()
    report = {
        "schema_version": 1,
        "report_type": "agentlab_production_pack_synthesis_smoke",
        "root": str(root),
        "project": project,
        "task_id": task_id,
        "run_dir": str(run_dir),
        "status": "pass" if not semantic_failures else "fail",
        "request": request,
        "route_key": plan.route.route_key,
        "agents": list(plan.route.agents),
        "synthesis_shell": plan.production_pack,
        "production_pack": plan.production_pack,
        "validated_candidate_pack": validation_dict.get("pack") or {},
        "pack_identity_boundary": identity_boundary,
        "generated_artifacts": {
            "domain_research_brief": brief,
            "pack_outputs": written_outputs,
            "required": required,
            "missing": missing,
        },
        "semantic_checks": semantic_checks,
        "proposal_validation": validation_dict,
        "promotion": {
            "attempted": False,
            "reason": "smoke validates candidate artifacts only; promotion requires explicit approval",
        },
    }
    if out:
        write_report_yaml(out, report, root)
    return report
