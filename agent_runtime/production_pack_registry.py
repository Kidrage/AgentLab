"""Validate and promote synthesized production-pack proposals.

The synthesis route may create a candidate pack for an unconfigured domain.
This module is the deterministic closure step: it refuses empty or ambiguous
proposals and appends an approved pack to ``config/production_packs.yml``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

import yaml

try:
    from atomic_io import atomic_write_yaml, safe_read_yaml
    from lifecycle_graph import LIFECYCLE_NODES
except ImportError:  # pragma: no cover - package import path
    from agent_runtime.atomic_io import atomic_write_yaml, safe_read_yaml
    from agent_runtime.lifecycle_graph import LIFECYCLE_NODES


PACK_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,80}$")
RESERVED_PACK_IDS = {"pack_synthesis_candidate"}
CORE_LIFECYCLE_NODES = {"INIT_TASK", "PREPARE_PLAN", "SUPERVISOR_PLAN", "FINALIZE"}
LIST_FIELDS = (
    "routes",
    "project_types",
    "task_domains",
    "artifact_types",
    "lifecycle_nodes",
    "domain_phases",
    "required_outputs",
    "memory_contract",
    "quality_gates",
)
SELECTOR_FIELDS = ("routes", "project_types", "task_domains", "artifact_types")
CODE_ROUTE_KEYS = {
    "small_task",
    "medium_task",
    "interface_sensitive_task",
    "research_sensitive_task",
    "large_or_risky_task",
    "evaluation_task",
}
CODE_PROJECT_TYPES = {"codebase_build_project"}
CODE_TASK_DOMAINS = {"coding", "software_engineering", "code_generation", "code_review"}
CODE_ARTIFACT_TYPES = {"code_patch", "source_patch", "repository_change"}
CODE_SHELL_LIFECYCLE_NODES = {"CODER_IMPLEMENTATION"}
CODE_SHELL_OUTPUT_TERMS = (
    "implementation_report",
    "06_implementation_report",
    "coder_prompt",
    "05_coder_prompt",
    "interface_map",
    "04_interface_map",
    "reposcout_report",
    "02_reposcout_report",
)
REQUIRED_NON_CODE_RESOURCE_SOURCES = {
    "user_provided_files",
    "configured_local_tools",
    "registered_role_workers",
    "approved_external_research",
}


@dataclass
class PackCandidateValidation:
    valid: bool
    proposal_path: str
    pack_id: str | None = None
    pack: dict[str, Any] | None = None
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "proposal_path": self.proposal_path,
            "pack_id": self.pack_id,
            "issues": self.issues,
            "warnings": self.warnings,
            "pack": self.pack,
        }


def validate_pack_candidate(
    proposal_path: Path,
    catalog_path: Path | None = None,
    *,
    allow_replace: bool = False,
) -> PackCandidateValidation:
    proposal_path = Path(proposal_path)
    proposal = safe_read_yaml(proposal_path, default=None)
    issues: list[str] = []
    warnings: list[str] = []
    if not isinstance(proposal, dict):
        return PackCandidateValidation(
            valid=False,
            proposal_path=str(proposal_path),
            issues=["proposal is missing or is not a YAML mapping"],
        )

    pack = _extract_pack(proposal)
    if not isinstance(pack, dict):
        return PackCandidateValidation(
            valid=False,
            proposal_path=str(proposal_path),
            issues=["proposal must contain a top-level pack mapping or pack_id fields"],
        )

    normalized = _normalize_pack(pack)
    pack_id = str(normalized.get("pack_id") or "")
    _validate_pack_shape(normalized, issues, warnings)
    _validate_resource_contract(normalized, issues)
    _validate_candidate_companion_files(proposal_path, normalized, issues)

    if catalog_path is not None and pack_id:
        catalog = safe_read_yaml(Path(catalog_path), default={}) or {}
        existing_ids = {
            str(item.get("pack_id"))
            for item in catalog.get("packs") or []
            if isinstance(item, dict) and item.get("pack_id")
        }
        if pack_id in existing_ids and not allow_replace:
            issues.append(f"pack_id already exists in catalog: {pack_id}")

    return PackCandidateValidation(
        valid=not issues,
        proposal_path=str(proposal_path),
        pack_id=pack_id or None,
        pack=normalized,
        issues=issues,
        warnings=warnings,
    )


def _validate_candidate_companion_files(
    proposal_path: Path,
    pack: dict[str, Any],
    issues: list[str],
) -> None:
    base_dir = Path(proposal_path).parent
    memory_path = base_dir / "domain_memory_contract.yml"
    lifecycle_path = base_dir / "lifecycle_profile.yml"
    _validate_domain_memory_contract(memory_path, pack, issues)
    _validate_lifecycle_profile(lifecycle_path, pack, issues)


def _validate_domain_memory_contract(path: Path, pack: dict[str, Any], issues: list[str]) -> None:
    data = safe_read_yaml(path, default=None)
    if not isinstance(data, dict):
        issues.append("domain_memory_contract.yml is required and must be a YAML mapping")
        return
    memory_contract = data.get("memory_contract") or []
    if not memory_contract:
        issues.append("domain_memory_contract.yml must define non-empty memory_contract")
        return
    missing = sorted(set(pack.get("memory_contract") or []) - set(memory_contract))
    if missing:
        issues.append(
            "domain_memory_contract.yml missing pack memory entries: "
            + ", ".join(str(item) for item in missing)
        )
    _validate_domain_memory_resource_contract(data, pack, issues)


def _validate_domain_memory_resource_contract(
    data: dict[str, Any],
    pack: dict[str, Any],
    issues: list[str],
) -> None:
    if _pack_intent_is_code(pack):
        return
    pack_resource_contract = pack.get("resource_contract")
    if not isinstance(pack_resource_contract, dict):
        return
    memory_resource_contract = data.get("resource_contract")
    if not isinstance(memory_resource_contract, dict):
        issues.append("domain_memory_contract.yml must mirror pack resource_contract for non-code packs")
        return
    required_true_fields = (
        "external_research_may_not_write_project_memory",
        "evidence_to_memory_promotion_requires_review",
    )
    for field in required_true_fields:
        if memory_resource_contract.get(field) is not True:
            issues.append(f"domain_memory_contract.yml resource_contract.{field} must be true")


def _validate_lifecycle_profile(path: Path, pack: dict[str, Any], issues: list[str]) -> None:
    data = safe_read_yaml(path, default=None)
    if not isinstance(data, dict):
        issues.append("lifecycle_profile.yml is required and must be a YAML mapping")
        return
    lifecycle_nodes = data.get("lifecycle_nodes") or []
    quality_gates = data.get("quality_gates") or []
    if not lifecycle_nodes:
        issues.append("lifecycle_profile.yml must define non-empty lifecycle_nodes")
    if not quality_gates:
        issues.append("lifecycle_profile.yml must define non-empty quality_gates")
    missing_nodes = sorted(set(pack.get("lifecycle_nodes") or []) - set(lifecycle_nodes))
    if missing_nodes:
        issues.append(
            "lifecycle_profile.yml missing pack lifecycle_nodes: "
            + ", ".join(str(item) for item in missing_nodes)
        )


def promote_pack_candidate(
    proposal_path: Path,
    catalog_path: Path,
    *,
    approved_by: str,
    allow_replace: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not str(approved_by or "").strip():
        raise ValueError("approved_by is required")

    catalog_path = Path(catalog_path)
    validation = validate_pack_candidate(
        Path(proposal_path),
        catalog_path,
        allow_replace=allow_replace,
    )
    if not validation.valid or not validation.pack or not validation.pack_id:
        return {
            "promoted": False,
            "status": "invalid",
            "validation": validation.as_dict(),
        }

    catalog = safe_read_yaml(catalog_path, default={}) or {}
    if not isinstance(catalog, dict):
        raise ValueError("production pack catalog is not a YAML mapping")
    packs = catalog.get("packs")
    if not isinstance(packs, list):
        packs = []
        catalog["packs"] = packs

    promoted_pack = dict(validation.pack)
    promoted_pack["generated_from"] = {
        "proposal_path": str(Path(proposal_path)),
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "approved_by": str(approved_by),
    }

    next_packs: list[dict[str, Any]] = []
    replaced = False
    for existing in packs:
        if isinstance(existing, dict) and existing.get("pack_id") == validation.pack_id:
            if allow_replace:
                next_packs.append(promoted_pack)
                replaced = True
            else:
                next_packs.append(existing)
            continue
        next_packs.append(existing)
    if not replaced:
        next_packs.append(promoted_pack)
    catalog["packs"] = next_packs

    if not dry_run:
        atomic_write_yaml(catalog_path, catalog, sort_keys=False, allow_unicode=True)

    return {
        "promoted": not dry_run,
        "status": "dry_run" if dry_run else "promoted",
        "pack_id": validation.pack_id,
        "catalog_path": str(catalog_path),
        "replaced": replaced,
        "validation": validation.as_dict(),
    }


def audit_pack_catalog(
    catalog_path: Path,
    routing_path: Path | None = None,
    domain_route_packs_path: Path | None = None,
) -> dict[str, Any]:
    """Audit pack catalog selector collisions and duplicate registrations."""
    catalog_path = Path(catalog_path)
    if routing_path is None:
        routing_path = catalog_path.parent / "routing_rules.yml"
    if domain_route_packs_path is None:
        domain_route_packs_path = catalog_path.parent / "domain_route_packs.yml"
    catalog = safe_read_yaml(catalog_path, default={}) or {}
    known_routes = _known_routes(Path(routing_path))
    packs = catalog.get("packs") if isinstance(catalog, dict) else []
    packs = [pack for pack in packs if isinstance(pack, dict)] if isinstance(packs, list) else []
    normalized = [_normalize_pack(pack) for pack in packs]
    issues: list[str] = []
    selector_overlaps: list[dict[str, Any]] = []
    route_reference_audit = _route_reference_audit(
        normalized,
        known_routes,
        Path(routing_path),
        Path(domain_route_packs_path),
    )

    seen_ids: dict[str, int] = {}
    for index, pack in enumerate(normalized):
        pack_id = str(pack.get("pack_id") or "")
        if not pack_id:
            issues.append(f"pack at index {index} is missing pack_id")
            continue
        if pack_id in seen_ids:
            issues.append(f"duplicate pack_id: {pack_id}")
        seen_ids[pack_id] = index

    for left_index, left in enumerate(normalized):
        for right in normalized[left_index + 1 :]:
            shared_routes = sorted(set(left.get("routes") or []) & set(right.get("routes") or []))
            for route in shared_routes:
                overlap = _route_selector_overlap(left, right, route)
                selector_overlaps.append(overlap)
                if overlap["status"] == "ambiguous_equal_specificity":
                    issues.append(
                        "ambiguous selector collision on route "
                        f"{route}: {left.get('pack_id')} and {right.get('pack_id')} have equal specificity"
                    )
    issues.extend(route_reference_audit["issues"])

    return {
        "schema_version": 1,
        "report_type": "agentlab_production_pack_catalog_audit",
        "catalog_path": str(catalog_path),
        "status": "fail" if issues else "pass",
        "pack_count": len(normalized),
        "issues": issues,
        "selector_overlaps": selector_overlaps,
        "route_reference_audit": route_reference_audit,
    }


def _extract_pack(proposal: dict[str, Any]) -> dict[str, Any] | None:
    pack = proposal.get("pack")
    if isinstance(pack, dict):
        return pack
    if proposal.get("pack_id"):
        return proposal
    return None


def _normalize_pack(pack: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        key: value
        for key, value in pack.items()
        if key not in {"schema_version", "status", "approval", "validation"}
    }
    for key in LIST_FIELDS:
        normalized[key] = _string_list(normalized.get(key))
    return normalized


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _validate_pack_shape(pack: dict[str, Any], issues: list[str], warnings: list[str]) -> None:
    pack_id = str(pack.get("pack_id") or "").strip()
    if not pack_id:
        issues.append("pack_id is required")
    elif not PACK_ID_PATTERN.match(pack_id):
        issues.append("pack_id must match ^[a-z][a-z0-9_]{2,80}$")
    elif pack_id in RESERVED_PACK_IDS:
        issues.append(f"pack_id is reserved: {pack_id}")

    for field in ("name", "description"):
        if not str(pack.get(field) or "").strip():
            issues.append(f"{field} is required")

    if not any(pack.get(field) for field in SELECTOR_FIELDS):
        issues.append("at least one selector is required: routes, project_types, task_domains, or artifact_types")

    lifecycle_nodes = pack.get("lifecycle_nodes") or []
    if not lifecycle_nodes:
        issues.append("lifecycle_nodes must be non-empty")
    else:
        unknown_nodes = sorted(set(lifecycle_nodes) - set(LIFECYCLE_NODES))
        if unknown_nodes:
            issues.append(f"unknown lifecycle_nodes: {', '.join(unknown_nodes)}")
        missing_core = sorted(CORE_LIFECYCLE_NODES - set(lifecycle_nodes))
        if missing_core:
            issues.append(f"lifecycle_nodes missing core nodes: {', '.join(missing_core)}")

    for field in ("required_outputs", "memory_contract", "quality_gates"):
        if not pack.get(field):
            issues.append(f"{field} must be non-empty")

    for output in pack.get("required_outputs") or []:
        output_path = Path(str(output))
        if output_path.is_absolute() or ".." in output_path.parts:
            issues.append(f"required_outputs contains unsafe path: {output}")

    if not _pack_intent_is_code(pack):
        code_nodes = sorted(set(lifecycle_nodes) & CODE_SHELL_LIFECYCLE_NODES)
        if code_nodes:
            issues.append(
                "non-code production pack cannot include code-shell lifecycle_nodes: "
                + ", ".join(code_nodes)
            )
        code_outputs = [
            str(output)
            for output in pack.get("required_outputs") or []
            if any(term in str(output).lower() for term in CODE_SHELL_OUTPUT_TERMS)
        ]
        if code_outputs:
            issues.append(
                "non-code production pack cannot require code-shell outputs: "
                + ", ".join(code_outputs)
            )


def _validate_resource_contract(pack: dict[str, Any], issues: list[str]) -> None:
    if _pack_intent_is_code(pack):
        return
    resource_contract = pack.get("resource_contract")
    if not isinstance(resource_contract, dict):
        issues.append("non-code production pack must define resource_contract")
        return
    if resource_contract.get("resource_discovery_required") is not True:
        issues.append("resource_contract.resource_discovery_required must be true")
    allowed_sources = set(_string_list(resource_contract.get("allowed_sources")))
    missing_sources = sorted(REQUIRED_NON_CODE_RESOURCE_SOURCES - allowed_sources)
    if missing_sources:
        issues.append("resource_contract.allowed_sources missing: " + ", ".join(missing_sources))
    if resource_contract.get("prefer_internal_workers") is not True:
        issues.append("resource_contract.prefer_internal_workers must be true")
    if resource_contract.get("new_provider_requires_approval") is not True:
        issues.append("resource_contract.new_provider_requires_approval must be true")
    if resource_contract.get("external_research_requires_approval") is not True:
        issues.append("resource_contract.external_research_requires_approval must be true")
    if resource_contract.get("external_research_may_not_write_project_memory") is not True:
        issues.append("resource_contract.external_research_may_not_write_project_memory must be true")
    if resource_contract.get("evidence_to_memory_promotion_requires_review") is not True:
        issues.append("resource_contract.evidence_to_memory_promotion_requires_review must be true")
    if "resource_evidence_ledger" not in set(_string_list(resource_contract.get("external_research_outputs"))):
        issues.append("resource_contract.external_research_outputs must include resource_evidence_ledger")
    authority_boundary = str(resource_contract.get("authority_boundary") or "")
    if "authoritative memory" not in authority_boundary:
        issues.append("resource_contract.authority_boundary must keep external research out of authoritative memory")


def _pack_intent_is_code(pack: dict[str, Any]) -> bool:
    pack_id = str(pack.get("pack_id") or "")
    if pack_id == "code_factory":
        return True
    routes = set(pack.get("routes") or [])
    project_types = set(pack.get("project_types") or [])
    task_domains = set(pack.get("task_domains") or [])
    artifact_types = set(pack.get("artifact_types") or [])
    return bool(
        routes & CODE_ROUTE_KEYS
        or project_types & CODE_PROJECT_TYPES
        or task_domains & CODE_TASK_DOMAINS
        or artifact_types & CODE_ARTIFACT_TYPES
    )


def _known_routes(routing_path: Path) -> set[str]:
    routing = safe_read_yaml(routing_path, default={}) or {}
    routes = routing.get("routes") if isinstance(routing, dict) else {}
    if not isinstance(routes, dict):
        return set()
    return {str(route) for route in routes}


def _route_reference_audit(
    packs: list[dict[str, Any]],
    known_routes: set[str],
    routing_path: Path,
    domain_route_packs_path: Path,
) -> dict[str, Any]:
    issues: list[str] = []
    pack_route_refs: list[dict[str, Any]] = []
    for pack in packs:
        pack_id = str(pack.get("pack_id") or "")
        for route in pack.get("routes") or []:
            route_text = str(route)
            exists = route_text in known_routes
            pack_route_refs.append({"pack_id": pack_id, "route": route_text, "exists": exists})
            if known_routes and not exists:
                issues.append(f"pack {pack_id} references unknown route: {route_text}")

    domain_audit = _domain_route_pack_audit(domain_route_packs_path, known_routes, packs)
    issues.extend(domain_audit["issues"])
    return {
        "status": "fail" if issues else "pass",
        "routing_path": str(routing_path),
        "domain_route_packs_path": str(domain_route_packs_path),
        "known_route_count": len(known_routes),
        "pack_route_references": pack_route_refs,
        "domain_route_packs": domain_audit["domain_route_packs"],
        "issues": issues,
    }


def _domain_route_pack_audit(
    domain_route_packs_path: Path,
    known_routes: set[str],
    packs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    data = safe_read_yaml(domain_route_packs_path, default={}) or {}
    domain_packs = data.get("domain_packs") if isinstance(data, dict) else {}
    issues: list[str] = []
    reports: list[dict[str, Any]] = []
    if domain_packs is None:
        return {"issues": [], "domain_route_packs": []}
    if not isinstance(domain_packs, dict):
        return {"issues": ["domain_route_packs is not a mapping"], "domain_route_packs": []}

    for domain, config in domain_packs.items():
        if not isinstance(config, dict):
            issues.append(f"domain_route_packs.{domain} is not a mapping")
            continue
        route_fields = {
            "recommended_route": config.get("recommended_route"),
            "batch_route": config.get("batch_route"),
            "audit_route": config.get("audit_route"),
        }
        forbidden = _string_list(config.get("forbidden_fallback_routes"))
        route_proposals = {
            "route_proposal": config.get("route_proposal"),
            "batch_route_proposal": config.get("batch_route_proposal"),
            "audit_route_proposal": config.get("audit_route_proposal"),
        }
        route_refs: list[dict[str, Any]] = []
        for field, route in route_fields.items():
            if not route:
                continue
            route_text = str(route)
            exists = route_text in known_routes
            route_refs.append({"field": field, "route": route_text, "exists": exists})
            if known_routes and not exists:
                issues.append(f"domain {domain}.{field} references unknown route: {route_text}")
            if route_text in forbidden:
                issues.append(f"domain {domain}.{field} is also listed as forbidden fallback: {route_text}")
        for route in forbidden:
            exists = route in known_routes
            route_refs.append({"field": "forbidden_fallback_routes", "route": route, "exists": exists})
            if known_routes and not exists:
                issues.append(f"domain {domain}.forbidden_fallback_routes references unknown route: {route}")

        proposal_expected = {
            "route_proposal": route_fields["recommended_route"],
            "batch_route_proposal": route_fields["batch_route"],
            "audit_route_proposal": route_fields["audit_route"],
        }
        for proposal_field, proposal in route_proposals.items():
            if not isinstance(proposal, dict):
                continue
            proposed_route = proposal.get("route_key")
            expected_route = proposal_expected.get(proposal_field)
            if proposed_route and expected_route and str(proposed_route) != str(expected_route):
                issues.append(
                    f"domain {domain}.{proposal_field}.route_key={proposed_route} "
                    f"does not match {expected_route}"
                )

        allowed_routes = {str(route) for route in route_fields.values() if route}
        for pack in packs or []:
            pack_routes = set(_string_list(pack.get("routes")))
            if not pack_routes.intersection(allowed_routes):
                continue
            pack_id = str(pack.get("pack_id") or "<unknown>")
            for route in sorted(pack_routes.intersection(forbidden)):
                issues.append(
                    f"domain {domain} forbidden fallback route {route} "
                    f"is still exposed by pack {pack_id}"
                )

        reports.append(
            {
                "domain": str(domain),
                "route_references": route_refs,
                "forbidden_fallback_routes": forbidden,
            }
        )
    return {"issues": issues, "domain_route_packs": reports}


def _selector_specificity(pack: dict[str, Any]) -> int:
    score = 0
    score += 8 if pack.get("project_types") else 0
    score += 4 if pack.get("task_domains") else 0
    score += 2 if pack.get("artifact_types") else 0
    score += 1 if pack.get("routes") else 0
    return score


def _selector_disambiguators(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    for field in ("project_types", "task_domains", "artifact_types"):
        left_values = set(left.get(field) or [])
        right_values = set(right.get(field) or [])
        if left_values and right_values and left_values.isdisjoint(right_values):
            fields.append(field)
    return fields


def _selectors_can_match_same_mission(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return not _selector_disambiguators(left, right)


def _route_selector_overlap(left: dict[str, Any], right: dict[str, Any], route: str) -> dict[str, Any]:
    left_score = _selector_specificity(left)
    right_score = _selector_specificity(right)
    disambiguators = _selector_disambiguators(left, right)
    if disambiguators:
        status = "selector_disjoint"
    elif left_score == right_score:
        status = "ambiguous_equal_specificity"
    else:
        status = "specificity_ordered"
    return {
        "route": route,
        "pack_ids": [left.get("pack_id"), right.get("pack_id")],
        "status": status,
        "left_specificity": left_score,
        "right_specificity": right_score,
        "can_match_same_mission": _selectors_can_match_same_mission(left, right),
        "disambiguated_by": disambiguators,
    }
