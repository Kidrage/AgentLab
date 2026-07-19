"""Validation and veto propagation for narrative quality scorecards."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


QUALITY_DIMENSIONS = (
    "causal_reasoning",
    "strategic_competence",
    "character_agency",
    "dramatic_tension",
    "reader_curiosity",
    "non_formulaic_progression",
)
VETO_DIMENSIONS = frozenset(
    {"causal_reasoning", "strategic_competence", "character_agency"}
)


def _expected_severity(score: int) -> str:
    if score <= 2:
        return "blocking"
    if score == 3:
        return "warn"
    return "pass"


def validate_quality_scorecard(
    scorecard: Mapping[str, Any],
    *,
    candidate_sha256: str,
) -> dict[str, object]:
    """Validate six evidence-backed dimensions without averaging vetoes."""
    issues: list[str] = []
    if scorecard.get("candidate_sha256") != candidate_sha256:
        issues.append("candidate_hash_mismatch")
    dimensions = scorecard.get("dimensions")
    if not isinstance(dimensions, Mapping):
        dimensions = {}
        issues.append("missing_dimensions")

    blocking: list[str] = []
    warnings: list[str] = []
    for name in QUALITY_DIMENSIONS:
        value = dimensions.get(name)
        if not isinstance(value, Mapping):
            issues.append(f"missing_dimension:{name}")
            continue
        score = value.get("score")
        if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
            issues.append(f"invalid_score:{name}")
            continue
        expected = _expected_severity(score)
        if str(value.get("severity") or "") != expected:
            issues.append(f"severity_score_mismatch:{name}")
        evidence = value.get("evidence")
        if not isinstance(evidence, Mapping):
            issues.append(f"missing_evidence:{name}")
        else:
            if not isinstance(evidence.get("chapter"), int):
                issues.append(f"missing_evidence_chapter:{name}")
            if not str(evidence.get("scene") or "").strip():
                issues.append(f"missing_evidence_scene:{name}")
            if not str(evidence.get("excerpt_or_locator") or "").strip():
                issues.append(f"missing_evidence_locator:{name}")
        if not str(value.get("reason") or "").strip():
            issues.append(f"missing_reason:{name}")
        if not str(value.get("revision_target") or "").strip():
            issues.append(f"missing_revision_target:{name}")
        if expected == "blocking":
            blocking.append(name)
        elif expected == "warn":
            warnings.append(name)

    computed_status = "blocked" if blocking else "warn" if warnings else "pass"
    if str(scorecard.get("status") or "") != computed_status:
        issues.append("scorecard_status_mismatch")
    valid = not issues
    return {
        "schema_version": 1,
        "valid": valid,
        "status": computed_status if valid else "invalid",
        "allow_seal": valid and not blocking,
        "blocking_dimensions": blocking,
        "warning_dimensions": warnings,
        "veto_dimensions": sorted(VETO_DIMENSIONS.intersection(blocking)),
        "issues": issues,
    }
