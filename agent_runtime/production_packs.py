"""Production pack resolution for AgentLab workflow plans.

Production packs are thin domain packages layered on top of the common
AgentLab runtime. They keep the code factory strong while allowing non-code
tasks to reuse state governance without inheriting code-specific task shells.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from atomic_io import safe_read_yaml
except ImportError:  # pragma: no cover - package import path
    from agent_runtime.atomic_io import safe_read_yaml


def load_production_pack_catalog(agentlab_root: Path) -> dict[str, Any]:
    path = agentlab_root / "config" / "production_packs.yml"
    data = safe_read_yaml(path, default={})
    return data if isinstance(data, dict) else {}


def build_production_pack(
    agentlab_root: Path,
    mission: dict[str, Any],
    route: Any,
    configs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve the production pack for a workflow route and mission contract."""
    catalog = (configs or {}).get("production_packs") or load_production_pack_catalog(agentlab_root)
    packs = catalog.get("packs", [])
    packs = packs if isinstance(packs, list) else []

    route_key = str(getattr(route, "route_key", "") or "")
    agents = list(getattr(route, "agents", []) or [])
    project_type = str(mission.get("project_type") or "")
    task_domain = str(mission.get("task_domain") or "")
    artifact_type = str(mission.get("artifact_type") or "")

    selected = _select_configured_pack(
        packs,
        route_key=route_key,
        project_type=project_type,
        task_domain=task_domain,
        artifact_type=artifact_type,
    )
    if (
        selected is not None
        and selected.get("pack_id") == "generic_artifact"
        and _should_synthesize_pack(catalog, route_key, project_type, task_domain, artifact_type)
    ):
        return _synthesis_candidate(catalog, route_key, project_type, task_domain, artifact_type)
    if selected is None:
        if _should_synthesize_pack(catalog, route_key, project_type, task_domain, artifact_type):
            return _synthesis_candidate(catalog, route_key, project_type, task_domain, artifact_type)
        selected = _fallback_pack(packs, route_key, agents, task_domain, artifact_type)
    if selected is None:
        return _synthesis_candidate(catalog, route_key, project_type, task_domain, artifact_type)

    return _pack_summary(
        catalog,
        selected,
        route_key=route_key,
        project_type=project_type,
        task_domain=task_domain,
        artifact_type=artifact_type,
        agents=agents,
        status="configured",
    )


def _select_configured_pack(
    packs: list[dict[str, Any]],
    *,
    route_key: str,
    project_type: str,
    task_domain: str,
    artifact_type: str,
) -> dict[str, Any] | None:
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for index, pack in enumerate(packs):
        if not isinstance(pack, dict):
            continue
        if not _matches(route_key, pack.get("routes")):
            continue
        if not _matches(project_type, pack.get("project_types")):
            continue
        if not _matches(task_domain, pack.get("task_domains")):
            continue
        if not _matches(artifact_type, pack.get("artifact_types")):
            continue
        score = 0
        score += 8 if pack.get("project_types") else 0
        score += 4 if pack.get("task_domains") else 0
        score += 2 if pack.get("artifact_types") else 0
        score += 1 if pack.get("routes") else 0
        ranked.append((score, -index, pack))
    if not ranked:
        return None
    ranked.sort(reverse=True)
    return ranked[0][2]


def _fallback_pack(
    packs: list[dict[str, Any]],
    route_key: str,
    agents: list[str],
    task_domain: str,
    artifact_type: str,
) -> dict[str, Any] | None:
    if "Coder" in agents or artifact_type == "code_patch" or task_domain == "coding":
        return _pack_by_id(packs, "code_factory")
    if route_key == "artifact_production_task":
        return _pack_by_id(packs, "generic_artifact")
    return None


def _should_synthesize_pack(
    catalog: dict[str, Any],
    route_key: str,
    project_type: str,
    task_domain: str,
    artifact_type: str,
) -> bool:
    policy = catalog.get("pack_synthesis_policy") if isinstance(catalog, dict) else {}
    if isinstance(policy, dict) and policy.get("enabled") is False:
        return False
    complex_domains = {
        "audio_dsp_experiment",
        "production_pack_synthesis",
        "research_reading",
        "multimodal_asset_generation",
    }
    complex_project_types = {
        "research_archive_project",
        "multimodal_content_project",
    }
    if task_domain in complex_domains:
        return True
    if project_type in complex_project_types:
        return True
    if route_key == "artifact_production_task" and artifact_type in {
        "audio_experiment_report",
        "media_generation_contract",
        "production_pack_candidate",
    }:
        return True
    return False


def _pack_by_id(packs: list[dict[str, Any]], pack_id: str) -> dict[str, Any] | None:
    for pack in packs:
        if isinstance(pack, dict) and pack.get("pack_id") == pack_id:
            return pack
    return None


def _matches(value: str, configured: Any) -> bool:
    if not configured:
        return True
    if isinstance(configured, str):
        return value == configured
    if isinstance(configured, list):
        return value in {str(item) for item in configured}
    return False


def _pack_summary(
    catalog: dict[str, Any],
    pack: dict[str, Any],
    *,
    route_key: str,
    project_type: str,
    task_domain: str,
    artifact_type: str,
    agents: list[str],
    status: str,
) -> dict[str, Any]:
    route_contracts = pack.get("route_contracts") or {}
    route_contract = (
        route_contracts.get(route_key) or {}
        if isinstance(route_contracts, dict)
        else {}
    )
    role_contracts = route_contract.get("roles") or {}
    role_contracts = role_contracts if isinstance(role_contracts, dict) else {}
    required_outputs = list(route_contract.get("required_outputs") or [])
    output_owners = dict(route_contract.get("output_owners") or {})
    if not required_outputs:
        for role, contract in role_contracts.items():
            if not isinstance(contract, dict):
                continue
            for output in contract.get("required_outputs") or []:
                output_name = str(output)
                if output_name not in required_outputs:
                    required_outputs.append(output_name)
                output_owners.setdefault(output_name, str(role))
    if not required_outputs:
        required_outputs = list(pack.get("required_outputs") or [])
    for output, owner in (pack.get("output_owners") or {}).items():
        output_owners.setdefault(str(output), str(owner))

    return {
        "schema_version": 1,
        "status": status,
        "pack_id": str(pack.get("pack_id") or "unknown"),
        "name": str(pack.get("name") or pack.get("pack_id") or "Unknown Production Pack"),
        "description": str(pack.get("description") or ""),
        "route_key": route_key,
        "project_type": project_type,
        "task_domain": task_domain,
        "artifact_type": artifact_type,
        "agents": agents,
        "core_runtime": list(catalog.get("core_runtime") or []),
        "lifecycle_nodes": list(pack.get("lifecycle_nodes") or []),
        "domain_phases": list(pack.get("domain_phases") or []),
        "required_outputs": required_outputs,
        "output_owners": output_owners,
        "role_contracts": role_contracts,
        "memory_records": list(route_contract.get("memory_records") or []),
        "memory_contract": list(pack.get("memory_contract") or []),
        "quality_gates": list(pack.get("quality_gates") or []),
        "synthesis_policy": dict(catalog.get("pack_synthesis_policy") or {}),
    }


def _synthesis_candidate(
    catalog: dict[str, Any],
    route_key: str,
    project_type: str,
    task_domain: str,
    artifact_type: str,
) -> dict[str, Any]:
    policy = dict(catalog.get("pack_synthesis_policy") or {})
    synthesis_agents = list(policy.get("agents") or [])
    return {
        "schema_version": 1,
        "status": "synthesis_candidate",
        "pack_id": "pack_synthesis_candidate",
        "name": "Production Pack Synthesis Candidate",
        "description": "No configured production pack matched this non-code domain; synthesize a reviewed pack before execution.",
        "route_key": route_key,
        "project_type": project_type,
        "task_domain": task_domain,
        "artifact_type": artifact_type,
        "agents": synthesis_agents,
        "core_runtime": list(catalog.get("core_runtime") or []),
        "lifecycle_nodes": [
            "INIT_TASK",
            "CONTEXT_PROFILE",
            "CONTEXT_BUDGET",
            "CONTEXT_PACK",
            "PREPARE_PLAN",
            "SUPERVISOR_PLAN",
            "RESEARCH_OPTIONAL",
            "ARTIFACT_PRODUCTION",
            "VERIFY",
            "SELF_CHECK",
            "FINALIZE",
        ],
        "domain_phases": ["discover_domain_requirements", "research_domain_capabilities", "propose_pack", "approve_pack"],
        "memory_contract": [
            "domain_research_brief",
            "production_pack_proposal",
            "domain_memory_contract",
            "lifecycle_profile",
        ],
        "quality_gates": ["domain_research_brief", "pack_proposal_reviewed", "approval_before_execution"],
        "synthesis_policy": policy,
        "required_outputs": list(policy.get("required_outputs") or []),
    }
