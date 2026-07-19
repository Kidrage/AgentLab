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
    required_chapters: tuple[int, ...] | list[int] | None = None,
) -> dict[str, object]:
    """Validate one evidence-backed six-dimension scorecard per audited chapter."""
    issues: list[str] = []
    if scorecard.get("candidate_sha256") != candidate_sha256:
        issues.append("candidate_hash_mismatch")
    blocking: list[str] = []
    warnings: list[str] = []
    chapter_records = scorecard.get("chapters")
    normalized: list[tuple[int | None, Mapping[str, Any], str]] = []
    if isinstance(chapter_records, list):
        seen: set[int] = set()
        for index, record in enumerate(chapter_records):
            if not isinstance(record, Mapping) or not isinstance(record.get("chapter_id"), int):
                issues.append(f"invalid_chapter_scorecard:{index}")
                continue
            chapter_id = int(record["chapter_id"])
            if chapter_id in seen:
                issues.append(f"duplicate_chapter_scorecard:{chapter_id}")
                continue
            seen.add(chapter_id)
            dimensions = record.get("dimensions")
            if not isinstance(dimensions, Mapping):
                issues.append(f"missing_dimensions:{chapter_id}")
                dimensions = {}
            normalized.append((chapter_id, dimensions, str(record.get("status") or "")))
    else:
        dimensions = scorecard.get("dimensions")
        if not isinstance(dimensions, Mapping):
            dimensions = {}
            issues.append("missing_dimensions")
        normalized.append((None, dimensions, str(scorecard.get("status") or "")))

    required = sorted(set(int(chapter) for chapter in (required_chapters or [])))
    covered = {chapter for chapter, _, _ in normalized if chapter is not None}
    if required:
        if normalized and normalized[0][0] is None and len(required) > 1:
            issues.append("batch_scorecard_requires_per_chapter_entries")
        elif covered:
            for chapter in required:
                if chapter not in covered:
                    issues.append(f"missing_chapter_scorecard:{chapter}")

    for chapter_id, dimensions, declared_status in normalized:
        chapter_blocking: list[str] = []
        chapter_warnings: list[str] = []
        label = str(chapter_id) if chapter_id is not None else "root"
        for name in QUALITY_DIMENSIONS:
            value = dimensions.get(name)
            if not isinstance(value, Mapping):
                issues.append(f"missing_dimension:{label}:{name}")
                continue
            score = value.get("score")
            if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
                issues.append(f"invalid_score:{label}:{name}")
                continue
            expected = _expected_severity(score)
            if str(value.get("severity") or "") != expected:
                issues.append(f"severity_score_mismatch:{label}:{name}")
            evidence = value.get("evidence")
            if not isinstance(evidence, Mapping):
                issues.append(f"missing_evidence:{label}:{name}")
            else:
                evidence_chapter = evidence.get("chapter")
                if not isinstance(evidence_chapter, int):
                    issues.append(f"missing_evidence_chapter:{label}:{name}")
                elif chapter_id is not None and evidence_chapter != chapter_id:
                    issues.append(f"evidence_chapter_mismatch:{label}:{name}")
                if not str(evidence.get("scene") or "").strip():
                    issues.append(f"missing_evidence_scene:{label}:{name}")
                if not str(evidence.get("excerpt_or_locator") or "").strip():
                    issues.append(f"missing_evidence_locator:{label}:{name}")
            if not str(value.get("reason") or "").strip():
                issues.append(f"missing_reason:{label}:{name}")
            if not str(value.get("revision_target") or "").strip():
                issues.append(f"missing_revision_target:{label}:{name}")
            key = name if chapter_id is None else f"{chapter_id}:{name}"
            if expected == "blocking":
                chapter_blocking.append(key)
            elif expected == "warn":
                chapter_warnings.append(key)
        chapter_status = (
            "blocked" if chapter_blocking else "warn" if chapter_warnings else "pass"
        )
        if declared_status != chapter_status:
            issues.append(f"chapter_scorecard_status_mismatch:{label}")
        blocking.extend(chapter_blocking)
        warnings.extend(chapter_warnings)

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
        "veto_dimensions": sorted(
            key for key in blocking if key.rsplit(":", 1)[-1] in VETO_DIMENSIONS
        ),
        "issues": issues,
    }
