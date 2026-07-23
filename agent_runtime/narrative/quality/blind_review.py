"""Anonymous old/new candidate selection without confirmation bias."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def select_candidate_after_blind_review(
    *,
    original_sha256: str,
    revised_sha256: str,
    blind_mapping: Mapping[str, str],
    blind_receipt: Mapping[str, Any],
) -> dict[str, object]:
    """Replace the original only when the anonymous revision wins cleanly."""
    if set(blind_mapping) != {"A", "B"} or set(blind_mapping.values()) != {
        original_sha256,
        revised_sha256,
    }:
        raise ValueError("blind mapping must bind A/B to the exact candidate hashes")
    required = ("pair_id", "judge_id", "preferred_version", "reason")
    if blind_receipt.get("status") != "completed" or any(
        not blind_receipt.get(field) for field in required
    ):
        raise ValueError("blind review receipt is incomplete")
    preferred = str(blind_receipt["preferred_version"])
    if preferred not in {*blind_mapping, "tie"}:
        raise ValueError("blind review preference is not an anonymous candidate label")
    preferred_hash = blind_mapping.get(preferred)
    remaining = blind_receipt.get("remaining_blocking") or []
    regressions = blind_receipt.get("new_regressions") or []
    if preferred_hash == revised_sha256 and not remaining and not regressions:
        return {
            "status": "accepted_revision",
            "replace_current_candidate": True,
            "selected_sha256": revised_sha256,
            "rejected_sha256": original_sha256,
            "reason": "revised_candidate_won_blind_review_without_regression",
        }
    return {
        "status": "retained_original",
        "replace_current_candidate": False,
        "selected_sha256": original_sha256,
        "rejected_sha256": revised_sha256,
        "reason": (
            "revision_introduced_or_retained_blocking"
            if remaining or regressions
            else "revision_did_not_win_blind_review"
        ),
    }
