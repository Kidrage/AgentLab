"""Strict anonymous literary A/B evidence for governed narrative revisions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from agent_runtime.narrative.quality.blind_review import (
    select_candidate_after_blind_review,
)
from agent_runtime.narrative.quality.scorecard import QUALITY_DIMENSIONS


EDITORIAL_DIMENSIONS = (
    "voice_differentiation",
    "dialogue_naturalness",
    "rhetorical_fatigue",
    "explanation_density",
    "life_texture",
    "mystery_branching",
    "continue_reading_intent",
)
LITERARY_EDITOR_DIMENSIONS = QUALITY_DIMENSIONS + EDITORIAL_DIMENSIONS


def _severity(score: int) -> str:
    if score <= 2:
        return "blocking"
    if score == 3:
        return "warn"
    return "pass"


def build_literary_ab_output_schema() -> dict[str, Any]:
    """Return the enforced one-call Editor schema for anonymous manuscripts A/B."""
    evidence = {
        "type": "object",
        "required": ["chapter", "scene", "excerpt_or_locator"],
        "properties": {
            "chapter": {"type": "integer", "minimum": 1},
            "scene": {"type": "string", "minLength": 1},
            "excerpt_or_locator": {"type": "string", "minLength": 1},
        },
        "additionalProperties": False,
    }
    dimension = {
        "type": "object",
        "required": ["score", "severity", "evidence", "reason", "revision_target"],
        "properties": {
            "score": {"type": "integer", "minimum": 1, "maximum": 5},
            "severity": {"enum": ["blocking", "warn", "pass"]},
            "evidence": evidence,
            "reason": {"type": "string", "minLength": 1},
            "revision_target": {"type": "string", "minLength": 1},
        },
        "additionalProperties": False,
    }
    scorecard = {
        "type": "object",
        "required": ["status", "dimensions"],
        "properties": {
            "status": {"enum": ["pass", "warn", "blocked"]},
            "dimensions": {
                "type": "object",
                "required": list(LITERARY_EDITOR_DIMENSIONS),
                "properties": {
                    name: dimension for name in LITERARY_EDITOR_DIMENSIONS
                },
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": [
            "schema_version",
            "status",
            "pair_id",
            "anonymous_scorecards",
            "blind_review",
        ],
        "properties": {
            "schema_version": {"const": 1},
            "status": {"const": "completed"},
            "pair_id": {"type": "string", "minLength": 1},
            "anonymous_scorecards": {
                "type": "object",
                "required": ["A", "B"],
                "properties": {"A": scorecard, "B": scorecard},
                "additionalProperties": False,
            },
            "blind_review": {
                "type": "object",
                "required": [
                    "preferred_version",
                    "preference_strength",
                    "reason",
                    "comparative_evidence",
                ],
                "properties": {
                    "preferred_version": {"enum": ["A", "B", "tie"]},
                    "preference_strength": {
                        "enum": ["weak", "moderate", "strong"]
                    },
                    "reason": {"type": "string", "minLength": 1},
                    "comparative_evidence": {
                        "type": "array",
                        "minItems": 2,
                        "items": {"type": "string", "minLength": 1},
                    },
                },
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    }


def find_literary_ab_payload(value: Any) -> dict[str, Any] | None:
    """Find the enforced payload inside Qwen stream-json or nested result wrappers."""
    if isinstance(value, Mapping):
        if {
            "schema_version",
            "status",
            "pair_id",
            "anonymous_scorecards",
            "blind_review",
        } <= set(value):
            return dict(value)
        for child in value.values():
            found = find_literary_ab_payload(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in reversed(value):
            found = find_literary_ab_payload(child)
            if found is not None:
                return found
    elif isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return find_literary_ab_payload(parsed)
    return None


def find_literary_ab_payload_in_output(raw: str) -> dict[str, Any] | None:
    """Parse a complete JSON response or newline-delimited stream-json events."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    found = find_literary_ab_payload(parsed)
    if found is not None:
        return found
    if "## Output" in raw:
        output = raw.split("## Output", 1)[1].lstrip("\n ")
        output = output.split("\n\n## stderr", 1)[0].strip()
        if output.startswith("```json") and output.endswith("```"):
            output = output.removeprefix("```json").removesuffix("```").strip()
        try:
            parsed_output = json.loads(output)
        except json.JSONDecodeError:
            parsed_output = None
        found = find_literary_ab_payload(parsed_output)
        if found is not None:
            return found
    for line in reversed(raw.splitlines()):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        found = find_literary_ab_payload(event)
        if found is not None:
            return found
    return None


def _validate_scorecard(
    scorecard: Any,
    *,
    label: str,
    chapter_id: int,
) -> dict[str, Any]:
    if not isinstance(scorecard, Mapping):
        raise ValueError(f"invalid_anonymous_scorecard:{label}")
    dimensions = scorecard.get("dimensions")
    if not isinstance(dimensions, Mapping) or set(dimensions) != set(
        LITERARY_EDITOR_DIMENSIONS
    ):
        raise ValueError(f"invalid_dimensions:{label}")
    normalized: dict[str, Any] = {}
    blocking = False
    warning = False
    for name in LITERARY_EDITOR_DIMENSIONS:
        value = dimensions.get(name)
        if not isinstance(value, Mapping):
            raise ValueError(f"invalid_dimension:{label}:{name}")
        score = value.get("score")
        if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
            raise ValueError(f"invalid_score:{label}:{name}")
        expected = _severity(score)
        if value.get("severity") != expected:
            raise ValueError(f"severity_score_mismatch:{label}:{name}")
        evidence = value.get("evidence")
        if not isinstance(evidence, Mapping):
            raise ValueError(f"missing_evidence:{label}:{name}")
        evidence_chapter = evidence.get("chapter")
        if (
            isinstance(evidence_chapter, bool)
            or not isinstance(evidence_chapter, int)
            or evidence_chapter != chapter_id
        ):
            raise ValueError(f"evidence_chapter_mismatch:{label}:{name}")
        for field in ("scene", "excerpt_or_locator"):
            if not isinstance(evidence.get(field), str) or not evidence[field].strip():
                raise ValueError(f"missing_evidence_{field}:{label}:{name}")
        for field in ("reason", "revision_target"):
            if not isinstance(value.get(field), str) or not value[field].strip():
                raise ValueError(f"missing_{field}:{label}:{name}")
        blocking = blocking or score <= 2
        warning = warning or score == 3
        normalized[name] = {
            "score": score,
            "severity": expected,
            "evidence": {
                "chapter": chapter_id,
                "scene": evidence["scene"].strip(),
                "excerpt_or_locator": evidence["excerpt_or_locator"].strip(),
            },
            "reason": value["reason"].strip(),
            "revision_target": value["revision_target"].strip(),
        }
    expected_status = "blocked" if blocking else "warn" if warning else "pass"
    if scorecard.get("status") != expected_status:
        raise ValueError(f"scorecard_status_mismatch:{label}")
    return {"status": expected_status, "dimensions": normalized}


def _hash_bound_scorecard(
    scorecard: Mapping[str, Any],
    *,
    chapter_id: int,
    candidate_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": scorecard["status"],
        "candidate_sha256": candidate_sha256,
        "chapters": [
            {
                "chapter_id": chapter_id,
                "status": scorecard["status"],
                "dimensions": dict(scorecard["dimensions"]),
            }
        ],
    }


def _blocking_dimensions(scorecard: Mapping[str, Any]) -> list[str]:
    dimensions = scorecard["dimensions"]
    return [
        name
        for name in LITERARY_EDITOR_DIMENSIONS
        if int(dimensions[name]["score"]) <= 2
    ]


def finalize_literary_ab_review(
    payload: Mapping[str, Any],
    *,
    chapter_id: int,
    expected_pair_id: str,
    blind_mapping: Mapping[str, str],
    original_sha256: str,
    revised_sha256: str,
    automatic_rewrite_number: int,
    judge_receipt: Mapping[str, Any],
    production_digest_before: str,
    production_digest_after: str,
) -> dict[str, Any]:
    """Validate, reveal, and decide without writing either candidate or Production."""
    if isinstance(chapter_id, bool) or not isinstance(chapter_id, int) or chapter_id < 1:
        raise ValueError("invalid_chapter_id")
    if payload.get("schema_version") != 1 or isinstance(
        payload.get("schema_version"), bool
    ):
        raise ValueError("invalid_literary_ab_schema_version")
    if payload.get("status") != "completed":
        raise ValueError("literary_ab_not_completed")
    if payload.get("pair_id") != expected_pair_id:
        raise ValueError("literary_ab_pair_id_mismatch")
    if set(blind_mapping) != {"A", "B"} or set(blind_mapping.values()) != {
        original_sha256,
        revised_sha256,
    }:
        raise ValueError("blind_mapping_mismatch")
    if production_digest_before != production_digest_after:
        raise ValueError("production_changed_during_literary_review")
    if (
        isinstance(automatic_rewrite_number, bool)
        or automatic_rewrite_number not in (1, 2)
    ):
        raise ValueError("invalid_automatic_rewrite_number")
    if (
        judge_receipt.get("judge_id") != "Reviewer"
        or judge_receipt.get("model") != "qwen3.7-max"
        or not str(judge_receipt.get("provider") or "").strip()
        or not str(judge_receipt.get("context_id") or "").strip()
    ):
        raise ValueError("invalid_literary_editor_judge_receipt")

    anonymous = payload.get("anonymous_scorecards")
    if not isinstance(anonymous, Mapping) or set(anonymous) != {"A", "B"}:
        raise ValueError("anonymous_scorecards_must_be_exactly_A_B")
    normalized = {
        label: _validate_scorecard(
            anonymous[label],
            label=label,
            chapter_id=chapter_id,
        )
        for label in ("A", "B")
    }
    blind = payload.get("blind_review")
    if not isinstance(blind, Mapping):
        raise ValueError("invalid_blind_review")
    preferred = blind.get("preferred_version")
    if preferred not in {"A", "B", "tie"}:
        raise ValueError("invalid_blind_preference")
    if blind.get("preference_strength") not in {"weak", "moderate", "strong"}:
        raise ValueError("invalid_blind_preference_strength")
    if not isinstance(blind.get("reason"), str) or not blind["reason"].strip():
        raise ValueError("missing_blind_reason")
    comparative = blind.get("comparative_evidence")
    if (
        not isinstance(comparative, list)
        or len(comparative) < 2
        or any(not isinstance(item, str) or not item.strip() for item in comparative)
    ):
        raise ValueError("missing_blind_comparative_evidence")

    hash_to_label = {candidate_hash: label for label, candidate_hash in blind_mapping.items()}
    original_label = hash_to_label[original_sha256]
    revised_label = hash_to_label[revised_sha256]
    original_anonymous = normalized[original_label]
    revised_anonymous = normalized[revised_label]
    original_scorecard = _hash_bound_scorecard(
        original_anonymous,
        chapter_id=chapter_id,
        candidate_sha256=original_sha256,
    )
    revised_scorecard = _hash_bound_scorecard(
        revised_anonymous,
        chapter_id=chapter_id,
        candidate_sha256=revised_sha256,
    )
    original_blocking = set(_blocking_dimensions(original_anonymous))
    revised_blocking = set(_blocking_dimensions(revised_anonymous))
    remaining_blocking = sorted(revised_blocking)
    new_regressions = sorted(revised_blocking - original_blocking)
    blind_receipt = {
        "status": "completed",
        "pair_id": expected_pair_id,
        "judge_id": judge_receipt["judge_id"],
        "preferred_version": preferred,
        "preference_strength": blind["preference_strength"],
        "reason": blind["reason"].strip(),
        "comparative_evidence": [item.strip() for item in comparative],
        "remaining_blocking": remaining_blocking,
        "new_regressions": new_regressions,
    }
    selection = select_candidate_after_blind_review(
        original_sha256=original_sha256,
        revised_sha256=revised_sha256,
        blind_mapping=blind_mapping,
        blind_receipt=blind_receipt,
    )
    accepted = bool(selection["replace_current_candidate"])
    status = selection["status"]
    reason = selection["reason"]
    automatic_rewrite_exhausted = False
    if not accepted and automatic_rewrite_number == 2:
        status = "decision_required"
        reason = "insufficient_revision_uplift"
        automatic_rewrite_exhausted = True
    score_delta = {
        name: (
            int(revised_anonymous["dimensions"][name]["score"])
            - int(original_anonymous["dimensions"][name]["score"])
        )
        for name in LITERARY_EDITOR_DIMENSIONS
    }
    mapping_sha256 = hashlib.sha256(
        json.dumps(dict(blind_mapping), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": 1,
        "status": status,
        "reason": reason,
        "candidate_only": True,
        "production_modified": False,
        "chapter_id": chapter_id,
        "pair_id": expected_pair_id,
        "automatic_rewrite_number": automatic_rewrite_number,
        "automatic_rewrite_exhausted": automatic_rewrite_exhausted,
        "replace_current_candidate": accepted,
        "selected_sha256": selection["selected_sha256"],
        "rejected_sha256": selection["rejected_sha256"],
        "remaining_blocking": remaining_blocking,
        "new_regressions": new_regressions,
        "score_delta_by_dimension": score_delta,
        "original_scorecard": original_scorecard,
        "revised_scorecard": revised_scorecard,
        "blind_receipt": blind_receipt,
        "blind_mapping_sha256": mapping_sha256,
        "judge_receipt": dict(judge_receipt),
        "production_digest_before": production_digest_before,
        "production_digest_after": production_digest_after,
    }
