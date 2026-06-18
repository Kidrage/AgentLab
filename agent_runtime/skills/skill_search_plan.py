"""S3 skill search plan builder.

Builds a deterministic `skill_search_plan.yml` from S1 MissionContract and S2
WorkflowPlan data. The output is a plan only: no network, install, promotion, or
skill execution occurs here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .discovery_policy import load_discovery_policy
from .source_registry import candidate_sources_for_plan, load_skill_source_registry, validate_skill_source_registry


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _capabilities_from_contract(contract: dict[str, Any]) -> list[str]:
    capabilities: list[str] = []
    for item in contract.get("required_capabilities") or []:
        if isinstance(item, dict):
            capabilities.append(str(item.get("capability") or ""))
        else:
            capabilities.append(str(item))
    return capabilities


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _workflow_capabilities(workflow_plan: dict[str, Any]) -> list[str]:
    capabilities = _strings(workflow_plan.get("required_capabilities"))
    for phase in workflow_plan.get("phases") or []:
        if isinstance(phase, dict):
            capabilities.extend(_strings(phase.get("required_capabilities")))
    return capabilities


def _workflow_skills(workflow_plan: dict[str, Any]) -> list[str]:
    skills = _strings(workflow_plan.get("recommended_skills"))
    for phase in workflow_plan.get("phases") or []:
        if isinstance(phase, dict):
            skills.extend(_strings(phase.get("recommended_skills")))
    return skills


def _search_terms(contract: dict[str, Any], workflow_plan: dict[str, Any], capabilities: list[str], skills: list[str]) -> list[str]:
    terms: list[str] = []
    terms.extend(capabilities)
    terms.extend(skills)
    for key in ("task_type", "domain", "intent_summary"):
        value = contract.get(key) or workflow_plan.get(key)
        if value:
            terms.append(str(value))
    if workflow_plan.get("template_id"):
        terms.append(str(workflow_plan["template_id"]))
    return _dedupe([term.replace("_", " ") for term in terms])


def build_skill_search_plan(
    mission_contract: dict[str, Any],
    workflow_plan: dict[str, Any],
    *,
    discovery_policy: dict[str, Any] | None = None,
    source_registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic S3 skill_search_plan data."""

    policy = discovery_policy or load_discovery_policy()
    registry = source_registry or load_skill_source_registry()
    registry_errors = validate_skill_source_registry(registry)
    required_capabilities = _dedupe(_capabilities_from_contract(mission_contract) + _workflow_capabilities(workflow_plan))
    recommended_skills = _dedupe(_workflow_skills(workflow_plan))
    route_controls = workflow_plan.get("route_controls") if isinstance(workflow_plan.get("route_controls"), dict) else {}
    approval_required = bool(
        policy.get("safety", {}).get("always_require_human_review", True)
        or registry.get("require_human_review", True)
        or route_controls.get("approval_first")
    )

    return {
        "schema_version": 1,
        "task_id": mission_contract.get("mission_id") or workflow_plan.get("task_id"),
        "template_id": workflow_plan.get("template_id"),
        "required_capabilities": required_capabilities,
        "recommended_skills": recommended_skills,
        "candidate_sources": candidate_sources_for_plan(registry),
        "search_terms": _search_terms(mission_contract, workflow_plan, required_capabilities, recommended_skills),
        "risk_policy": {
            "approval_required": approval_required,
            "allow_network": bool(policy.get("allow_network", False) and registry.get("network_enabled", False)),
            "auto_import": bool(policy.get("auto_import", False)),
            "auto_promote": bool(policy.get("auto_promote", False)),
            "never_execute_external_code": bool(policy.get("safety", {}).get("never_execute_external_code", True)),
            "never_copy_external_source": bool(policy.get("safety", {}).get("never_copy_external_source", True)),
        },
        "approval_required": approval_required,
        "route_controls": route_controls,
        "warnings": [
            {"warning_id": "source_registry_invalid", "message": error}
            for error in registry_errors
        ],
        "non_goals": [
            "Do not execute skills.",
            "Do not install or promote skills.",
            "Do not call network sources unless a later approved stage enables them.",
        ],
    }


def load_yaml_mapping(path: Path | str) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def write_skill_search_plan(plan: dict[str, Any], path: Path | str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(plan, sort_keys=False, allow_unicode=True), encoding="utf-8")
