"""Professional narrative team contracts and risk-bounded activation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence
import hashlib
import re

import yaml

from atomic_io import atomic_write_yaml

REQUIRED_AUTHOR_ROLES = (
    "authorial_director",
    "canon_timeline_steward",
    "plot_causality_architect",
    "character_ensemble_director",
    "relationship_director",
    "world_archaeologist",
    "foreshadow_mystery_keeper",
    "arc_scene_planner",
    "research_style_curator",
    "writer",
    "senior_editor",
    "reader_simulation_panel",
    "state_projector",
)

BASE_CHAPTER_ROLES = (
    "authorial_director",
    "canon_timeline_steward",
    "arc_scene_planner",
    "writer",
    "senior_editor",
    "state_projector",
)

FULL_TEAM_RISKS = {
    "battle",
    "death",
    "relationship_turn",
    "major_reveal",
    "volume_finale",
}

RISK_ROLE_MAP = {
    "causality": ("plot_causality_architect",),
    "character_decision": ("character_ensemble_director",),
    "relationship_progression": (
        "relationship_director",
        "reader_simulation_panel",
    ),
    "world_semantics": ("world_archaeologist",),
    "foreshadow_payoff": (
        "foreshadow_mystery_keeper",
        "reader_simulation_panel",
    ),
    "research_or_style": ("research_style_curator",),
    "reader_promise": ("reader_simulation_panel",),
}

KNOWN_RISKS = FULL_TEAM_RISKS | set(RISK_ROLE_MAP)
_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$")

_REQUIRED_FIELDS = (
    "manifest_version",
    "professional_duties",
    "knowledge_namespaces",
    "input_schema",
    "output_schema",
    "tools",
    "runtime",
    "authority",
    "forbidden_actions",
    "dependencies",
    "acceptance_rules",
)


def _nonempty_strings(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def validate_author_team_contract(
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the full v2 team contract and its separation-of-duty gates."""

    issues: list[str] = []
    if contract.get("schema_version") != "narrative-author-team/v2":
        issues.append("schema_version_must_be_narrative_author_team_v2")
    roles = contract.get("roles")
    if not isinstance(roles, Mapping):
        roles = {}
        issues.append("roles_mapping_required")
    role_ids = {str(role_id) for role_id in roles}
    for role_id in REQUIRED_AUTHOR_ROLES:
        if role_id not in roles:
            issues.append(f"missing_required_role:{role_id}")
    for role_id in sorted(role_ids - set(REQUIRED_AUTHOR_ROLES)):
        issues.append(f"unknown_role:{role_id}")
    for role_id in REQUIRED_AUTHOR_ROLES:
        raw = roles.get(role_id)
        if not isinstance(raw, Mapping):
            continue
        for field in _REQUIRED_FIELDS:
            if field not in raw:
                issues.append(f"{role_id}:{field}_required")
        if raw.get("manifest_version") != 2:
            issues.append(f"{role_id}:manifest_version_must_be_2")
        for field in (
            "professional_duties",
            "knowledge_namespaces",
            "forbidden_actions",
            "acceptance_rules",
        ):
            if field in raw and not _nonempty_strings(raw.get(field)):
                issues.append(f"{role_id}:{field}_must_be_nonempty_strings")
        for field in ("tools", "dependencies"):
            if field in raw and (
                not isinstance(raw.get(field), list)
                or any(
                    not isinstance(item, str) or not item.strip()
                    for item in raw.get(field, [])
                )
            ):
                issues.append(f"{role_id}:{field}_must_be_strings")
        for field in ("input_schema", "output_schema"):
            if field in raw and (
                not isinstance(raw.get(field), str)
                or not str(raw.get(field)).strip()
            ):
                issues.append(f"{role_id}:{field}_required")
        runtime = raw.get("runtime")
        if not isinstance(runtime, Mapping):
            issues.append(f"{role_id}:runtime_mapping_required")
        elif not str(runtime.get("model_tier") or "").strip():
            issues.append(f"{role_id}:runtime_model_tier_required")
        authority = raw.get("authority")
        if not isinstance(authority, Mapping):
            issues.append(f"{role_id}:authority_mapping_required")
        else:
            for scope in ("read", "write"):
                values = authority.get(scope)
                if not isinstance(values, list) or any(
                    not isinstance(item, str) or not item.strip()
                    for item in values
                ):
                    issues.append(
                        f"{role_id}:authority_{scope}_must_be_strings"
                    )
    writer = roles.get("writer") if isinstance(roles, Mapping) else {}
    writer = writer if isinstance(writer, Mapping) else {}
    writer_forbidden = set(writer.get("forbidden_actions") or [])
    for action, issue in (
        ("self_review", "writer:self_review_must_be_forbidden"),
        ("approve_own_work", "writer:approve_own_work_must_be_forbidden"),
        (
            "commit_narrative_state",
            "writer:commit_narrative_state_must_be_forbidden",
        ),
    ):
        if action not in writer_forbidden:
            issues.append(issue)
    writer_authority = writer.get("authority")
    writer_writes = (
        writer_authority.get("write") or []
        if isinstance(writer_authority, Mapping)
        else []
    )
    if any(
        str(scope).startswith(("project_brain/", "production/state"))
        for scope in writer_writes
    ):
        issues.append("writer:project_state_write_forbidden")
    projector = (
        roles.get("state_projector") if isinstance(roles, Mapping) else {}
    )
    projector = projector if isinstance(projector, Mapping) else {}
    projector_runtime = projector.get("runtime")
    projector_runtime = (
        projector_runtime
        if isinstance(projector_runtime, Mapping)
        else {}
    )
    if projector_runtime.get("deterministic") is not True:
        issues.append("state_projector:deterministic_runtime_required")
    if projector_runtime.get("model_tier") != "deterministic":
        issues.append("state_projector:generative_model_forbidden")
    return {
        "schema_version": "narrative-author-team-validation/v1",
        "status": "pass" if not issues else "blocked",
        "contract_id": contract.get("contract_id"),
        "role_count": len(role_ids),
        "roles": sorted(role_ids),
        "writer_boundary": {
            "self_review_forbidden": "self_review" in writer_forbidden,
            "approval_forbidden": "approve_own_work" in writer_forbidden,
            "state_commit_forbidden": (
                "commit_narrative_state" in writer_forbidden
            ),
        },
        "state_projector": {
            "deterministic": projector_runtime.get("deterministic") is True,
            "model_tier": projector_runtime.get("model_tier"),
        },
        "issues": sorted(set(issues)),
    }


def select_author_team(
    contract: Mapping[str, Any],
    *,
    risk_flags: Sequence[str],
) -> dict[str, Any]:
    """Select the smallest validated role subgraph for one chapter."""

    validation = validate_author_team_contract(contract)
    if validation["status"] != "pass":
        return {
            "schema_version": "narrative-author-team-selection/v1",
            "status": "blocked",
            "active_roles": [],
            "inactive_roles": [],
            "full_team": False,
            "issues": ["invalid_author_team_contract", *validation["issues"]],
        }
    normalized = [str(flag).strip() for flag in risk_flags]
    unknown = sorted(set(normalized) - KNOWN_RISKS)
    if unknown:
        return {
            "schema_version": "narrative-author-team-selection/v1",
            "status": "blocked",
            "active_roles": [],
            "inactive_roles": list(REQUIRED_AUTHOR_ROLES),
            "full_team": False,
            "issues": [f"unknown_risk_flag:{flag}" for flag in unknown],
        }
    full_team = bool(set(normalized) & FULL_TEAM_RISKS)
    active = (
        set(REQUIRED_AUTHOR_ROLES)
        if full_team
        else set(BASE_CHAPTER_ROLES)
    )
    if not full_team:
        for flag in normalized:
            active.update(RISK_ROLE_MAP.get(flag, ()))
    active_roles = [
        role_id for role_id in REQUIRED_AUTHOR_ROLES if role_id in active
    ]
    inactive_roles = [
        role_id for role_id in REQUIRED_AUTHOR_ROLES if role_id not in active
    ]
    return {
        "schema_version": "narrative-author-team-selection/v1",
        "status": "pass",
        "contract_id": contract.get("contract_id"),
        "risk_flags": normalized,
        "active_roles": active_roles,
        "inactive_roles": inactive_roles,
        "full_team": full_team,
        "issues": [],
    }


def materialize_author_team_contract(
    agentlab_root: Path,
    *,
    project: str,
    template_path: Path | None = None,
) -> dict[str, Any]:
    """Create one project-bound v2 contract without overwriting drift."""

    if not _PROJECT_ID.fullmatch(project):
        raise ValueError("project identifier is invalid")
    root = Path(agentlab_root).resolve()
    source = (
        Path(template_path)
        if template_path is not None
        else root / "config" / "narrative_author_team.yml"
    ).resolve()
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise ValueError("author-team template must be inside AgentLab root") from exc
    source_bytes = source.read_bytes()
    raw = yaml.safe_load(source_bytes) or {}
    if not isinstance(raw, Mapping):
        raise ValueError("author-team template must be a mapping")
    contract = dict(raw)
    contract["project_id"] = project
    contract["contract_id"] = f"{project}-professional-author-team"
    contract["template_binding"] = {
        "path": source.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(source_bytes).hexdigest(),
    }
    validation = validate_author_team_contract(contract)
    if validation["status"] != "pass":
        raise ValueError(
            "author-team template is invalid: " + ",".join(validation["issues"])
        )
    target = (
        root
        / "projects"
        / project
        / "production"
        / "author_team_contract.yml"
    )
    if target.is_file():
        current = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        if current != contract:
            raise ValueError(
                "project author-team contract already exists with different content"
            )
        status = "current"
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_yaml(target, contract)
        status = "created"
    return {
        "schema_version": "narrative-author-team-materialization/v1",
        "status": status,
        "project_id": project,
        "contract_path": target.relative_to(root).as_posix(),
        "template_sha256": contract["template_binding"]["sha256"],
        "role_count": len(REQUIRED_AUTHOR_ROLES),
    }
