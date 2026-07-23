"""Measured original-versus-revision quality uplift receipts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent_runtime.narrative.quality.scorecard import QUALITY_DIMENSIONS


def _scores(scorecard: Mapping[str, Any]) -> dict[str, int]:
    dimensions = scorecard.get("dimensions")
    if not isinstance(dimensions, Mapping):
        raise ValueError("scorecard dimensions are missing")
    scores: dict[str, int] = {}
    for name in QUALITY_DIMENSIONS:
        value = dimensions.get(name)
        if not isinstance(value, Mapping) or not isinstance(value.get("score"), int):
            raise ValueError(f"scorecard dimension is invalid: {name}")
        scores[name] = int(value["score"])
    return scores


def build_revision_uplift_receipt(
    *,
    original_scorecard: Mapping[str, Any],
    revised_scorecard: Mapping[str, Any],
    selection: Mapping[str, Any],
    revision_cost_usd: float,
    revision_wall_seconds: float,
) -> dict[str, object]:
    """Measure uplift only when blind selection actually accepts the revision."""
    original = _scores(original_scorecard)
    revised = _scores(revised_scorecard)
    original_blocking = {name for name, score in original.items() if score <= 2}
    revised_blocking = {name for name, score in revised.items() if score <= 2}
    deltas = {name: revised[name] - original[name] for name in QUALITY_DIMENSIONS}
    resolved = sorted(original_blocking - revised_blocking)
    new = sorted(revised_blocking - original_blocking)
    unresolved = sorted(original_blocking & revised_blocking)
    accepted = bool(selection.get("replace_current_candidate")) and not new and (
        bool(resolved) or any(delta > 0 for delta in deltas.values())
    )
    return {
        "schema_version": 1,
        "status": "accepted_improvement" if accepted else "insufficient_revision_uplift",
        "accepted_improvement": accepted,
        "original_status": original_scorecard.get("status"),
        "revised_status": revised_scorecard.get("status"),
        "score_delta_by_dimension": deltas,
        "unresolved_blocking": unresolved,
        "resolved_blocking": resolved,
        "new_blocking": new,
        "blind_selection_status": selection.get("status"),
        "cost_per_accepted_improvement_usd": float(revision_cost_usd)
        if accepted
        else None,
        "time_per_accepted_improvement_seconds": float(revision_wall_seconds)
        if accepted
        else None,
    }
