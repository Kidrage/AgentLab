"""Professional authorial audit planning and finding contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence
import hashlib
import json

from agent_runtime.narrative.author_team import (
    load_author_team_contract,
    select_author_team,
)
from agent_runtime.narrative.quality.revision import (
    compile_scene_revision_contract,
)

HARD_AUDIT_CHECKS = (
    "timeline",
    "age",
    "life_status",
    "location",
    "item",
    "ability_source",
    "character_knowledge_boundary",
    "canon_source_hash",
    "adult_consent_exit_right",
    "promise_payoff_state",
    "state_commit_idempotency",
)

_SOFT_REVIEW_DIMENSIONS = {
    "plot_causality_architect": ("causality", "foreshadow_enablement"),
    "character_ensemble_director": (
        "character_motive",
        "knowledge_and_false_belief",
        "offstage_action",
    ),
    "relationship_director": (
        "relationship_progression",
        "consent_and_agency",
    ),
    "world_archaeologist": ("world_semantics", "environmental_history"),
    "foreshadow_mystery_keeper": (
        "promise_state",
        "mystery_fairness",
    ),
    "research_style_curator": (
        "craft_device_fit",
        "originality_and_source_rights",
    ),
    "reader_simulation_panel": (
        "reader_promise",
        "emotional_effect",
        "position_bias_check",
    ),
}
_REVIEWER_ROLES = frozenset(
    {"canon_timeline_steward", *_SOFT_REVIEW_DIMENSIONS}
)
_FINDING_TEXT_FIELDS = (
    "finding_id",
    "target_scene",
    "problem_type",
    "evidence_locator",
    "evidence",
    "counterinterpretation",
    "revision_target",
)
_FINDING_SCOPES = frozenset({"line", "paragraph", "scene", "chapter"})
_FINDING_CLASSIFICATIONS = frozenset(
    {"hard_error", "aesthetic_disagreement"}
)


def validate_authorial_review_finding(
    finding: Mapping[str, object],
) -> list[str]:
    """Validate one evidence-rich hard or soft professional review finding."""

    issues: list[str] = []
    if finding.get("schema_version") != "authorial-review-finding/v1":
        issues.append("unsupported_finding_schema")
    reviewer_role = str(finding.get("reviewer_role") or "")
    if reviewer_role not in _REVIEWER_ROLES:
        issues.append(f"reviewer_role_not_allowed:{reviewer_role}")
    chapter_id = finding.get("chapter_id")
    if (
        isinstance(chapter_id, bool)
        or not isinstance(chapter_id, int)
        or chapter_id <= 0
    ):
        issues.append("chapter_id_must_be_positive")
    for field in _FINDING_TEXT_FIELDS:
        value = finding.get(field)
        if not isinstance(value, str) or not value.strip():
            issues.append(f"{field}_required")
    classification = str(finding.get("classification") or "")
    if classification not in _FINDING_CLASSIFICATIONS:
        issues.append(f"classification_invalid:{classification}")
    confidence = finding.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0.0 <= float(confidence) <= 1.0
    ):
        issues.append("confidence_must_be_between_zero_and_one")
    scope = str(finding.get("minimal_revision_scope") or "")
    if scope not in _FINDING_SCOPES:
        issues.append(f"minimal_revision_scope_invalid:{scope}")
    strengths = finding.get("preserve_strengths")
    if (
        not isinstance(strengths, list)
        or not strengths
        or not all(
            isinstance(item, str) and item.strip() for item in strengths
        )
    ):
        issues.append("preserve_strengths_required")
    candidate_sha256 = finding.get("candidate_sha256")
    if (
        not isinstance(candidate_sha256, str)
        or len(candidate_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in candidate_sha256
        )
    ):
        issues.append("candidate_sha256_invalid")
    return issues


def build_authorial_audit_plan(
    agentlab_root: Path,
    *,
    chapter_id: int,
    candidate_path: Path,
    risk_flags: Sequence[str],
) -> dict[str, Any]:
    """Bind mandatory hard checks and risk-triggered reviewers to a candidate."""

    if chapter_id <= 0:
        return {"status": "blocked", "issues": ["chapter_id_must_be_positive"]}
    candidate = Path(candidate_path).resolve()
    if not candidate.is_file():
        return {"status": "blocked", "issues": ["candidate_not_found"]}
    try:
        contract = load_author_team_contract(Path(agentlab_root))
    except ValueError as exc:
        return {
            "status": "blocked",
            "issues": [f"author_team_contract_invalid:{exc}"],
        }
    selection = select_author_team(contract, risk_flags=risk_flags)
    if selection["status"] != "pass":
        return {"status": "blocked", "issues": selection["issues"]}

    active_roles = set(selection["active_roles"])
    soft_reviews = [
        {
            "reviewer_role": role_id,
            "dimensions": list(dimensions),
        }
        for role_id, dimensions in _SOFT_REVIEW_DIMENSIONS.items()
        if role_id in active_roles
    ]
    identity: dict[str, Any] = {
        "schema_version": "authorial-audit-plan/v1",
        "chapter_id": chapter_id,
        "candidate": {
            "path": str(candidate),
            "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        },
        "risk_flags": sorted(set(str(item) for item in risk_flags)),
        "active_roles": selection["active_roles"],
        "hard_audit": {
            "reviewer_role": "canon_timeline_steward",
            "checks": list(HARD_AUDIT_CHECKS),
        },
        "soft_reviews": soft_reviews,
        "senior_editor_role": "senior_editor",
        "revision_attempt_limit": 2,
        "escalation_role": "authorial_director",
        "blind_review": {
            "required_after_revision": True,
            "anonymous": True,
            "order": "hash_randomized",
            "reviewer_role": "reader_simulation_panel",
        },
        "authority_bindings": contract["authority_bindings"],
    }
    plan_sha256 = hashlib.sha256(
        json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        **identity,
        "status": "pass",
        "plan_sha256": plan_sha256,
        "issues": [],
    }


def _deduplicated_strings(values: Sequence[object]) -> list[str]:
    return list(
        dict.fromkeys(
            text
            for value in values
            if (text := str(value).strip())
        )
    )


def compile_senior_editor_revision_contracts(
    findings: Sequence[Mapping[str, object]],
    *,
    candidate_path: Path,
    constraints: Mapping[str, object],
) -> dict[str, Any]:
    """Merge strict reviewer findings into executable scene-level contracts."""

    candidate = Path(candidate_path).resolve()
    if not candidate.is_file():
        return {"status": "blocked", "issues": ["candidate_not_found"]}
    candidate_sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if not findings:
        return {"status": "blocked", "issues": ["review_findings_required"]}

    issues: list[str] = []
    for index, finding in enumerate(findings):
        issues.extend(
            f"finding[{index}]:{issue}"
            for issue in validate_authorial_review_finding(finding)
        )
        if finding.get("candidate_sha256") != candidate_sha256:
            issues.append(f"finding[{index}]:candidate_sha256_mismatch")
    if issues:
        return {"status": "blocked", "issues": issues}
    triggering_audit_sha256 = hashlib.sha256(
        json.dumps(
            [dict(finding) for finding in findings],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    list_fields = (
        "must_preserve",
        "causal_requirements",
        "character_knowledge_before",
        "character_knowledge_after",
        "forbidden_regressions",
    )
    scalar_fields = ("allowed_freedom", "decision_cost", "new_information")
    normalized_constraints: dict[str, Any] = {}
    for field in list_fields:
        value = constraints.get(field)
        if not isinstance(value, list):
            return {
                "status": "blocked",
                "issues": [f"constraint_{field}_required"],
            }
        normalized = _deduplicated_strings(value)
        if not normalized:
            return {
                "status": "blocked",
                "issues": [f"constraint_{field}_required"],
            }
        normalized_constraints[field] = normalized
    for field in scalar_fields:
        value = constraints.get(field)
        if not isinstance(value, str) or not value.strip():
            return {
                "status": "blocked",
                "issues": [f"constraint_{field}_required"],
            }
        normalized_constraints[field] = value.strip()

    grouped: dict[tuple[int, str], list[Mapping[str, object]]] = {}
    for finding in findings:
        key = (int(finding["chapter_id"]), str(finding["target_scene"]))
        grouped.setdefault(key, []).append(finding)

    contracts: list[dict[str, object]] = []
    for (chapter_id, target_scene), scene_findings in grouped.items():
        evidence_lines = [
            (
                f"{finding['reviewer_role']} "
                f"({float(finding['confidence']):.2f}) "
                f"{finding['evidence_locator']}: {finding['evidence']} "
                f"Counterinterpretation: {finding['counterinterpretation']}"
            )
            for finding in scene_findings
        ]
        merged = {
            "chapter_id": chapter_id,
            "target_scene": target_scene,
            "problem_type": " + ".join(
                _deduplicated_strings(
                    [finding["problem_type"] for finding in scene_findings]
                )
            ),
            "evidence": "\n".join(evidence_lines),
            "revision_target": str(scene_findings[0]["revision_target"]),
        }
        preserve_strengths = _deduplicated_strings(
            [
                *normalized_constraints["must_preserve"],
                *(
                    strength
                    for finding in scene_findings
                    for strength in finding["preserve_strengths"]
                ),
            ]
        )
        contract = compile_scene_revision_contract(
            merged,
            must_preserve=preserve_strengths,
            allowed_freedom=normalized_constraints["allowed_freedom"],
            causal_requirements=normalized_constraints["causal_requirements"],
            character_knowledge_before=normalized_constraints[
                "character_knowledge_before"
            ],
            character_knowledge_after=normalized_constraints[
                "character_knowledge_after"
            ],
            decision_cost=normalized_constraints["decision_cost"],
            new_information=normalized_constraints["new_information"],
            forbidden_regressions=normalized_constraints[
                "forbidden_regressions"
            ],
        )
        contract["must_change"] = _deduplicated_strings(
            [finding["revision_target"] for finding in scene_findings]
        )
        contract["rewrite_scope"] = (
            "chapter"
            if any(
                finding["minimal_revision_scope"] == "chapter"
                for finding in scene_findings
            )
            else "scene"
        )
        contract["compiled_by"] = "senior_editor"
        contract["candidate_sha256"] = candidate_sha256
        contract["source_candidate_sha256"] = candidate_sha256
        contract["triggering_audit_sha256"] = triggering_audit_sha256
        contract["finding_classification"] = (
            "hard_error"
            if any(
                finding["classification"] == "hard_error"
                for finding in scene_findings
            )
            else "aesthetic_disagreement"
        )
        contract["review_evidence"] = [
            {
                field: finding[field]
                for field in (
                    "finding_id",
                    "reviewer_role",
                    "classification",
                    "evidence_locator",
                    "confidence",
                    "counterinterpretation",
                    "minimal_revision_scope",
                )
            }
            for finding in scene_findings
        ]
        contract.pop("revision_contract_id", None)
        contract["revision_contract_id"] = "rev-" + hashlib.sha256(
            json.dumps(
                contract,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:24]
        contracts.append(contract)

    result_identity = {
        "schema_version": "senior-editor-revision-set/v1",
        "candidate": {
            "path": str(candidate),
            "sha256": candidate_sha256,
        },
        "triggering_audit_sha256": triggering_audit_sha256,
        "compiled_by": "senior_editor",
        "revision_attempt_limit": 2,
        "escalation_role": "authorial_director",
        "blind_ab_required": True,
        "contracts": contracts,
    }
    return {
        **result_identity,
        "status": "pass",
        "revision_set_sha256": hashlib.sha256(
            json.dumps(
                result_identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "issues": [],
    }
