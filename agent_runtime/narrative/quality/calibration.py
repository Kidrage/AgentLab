"""Frozen replay and human blind-review expansion gate."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def evaluate_calibration_gate(
    *,
    negative_chapters: Iterable[int],
    positive_chapters: Iterable[int],
    replay_findings: Mapping[int, Iterable[str]],
    human_blind_receipts: Iterable[Mapping[str, Any]],
) -> dict[str, object]:
    """Authorize quality claims only after negative, positive, and human gates."""
    negatives = sorted(set(int(chapter) for chapter in negative_chapters))
    positives = sorted(set(int(chapter) for chapter in positive_chapters))
    negative_detection = {
        chapter: bool(list(replay_findings.get(chapter, ()))) for chapter in negatives
    }
    positive_blocking = {
        chapter: bool(list(replay_findings.get(chapter, ()))) for chapter in positives
    }
    receipts = list(human_blind_receipts)
    wins = sum(
        1
        for receipt in receipts
        if receipt.get("new_won") is True
        or str(receipt.get("preferred_version") or "").lower()
        in {"new", "revised"}
    )
    win_rate = wins / len(receipts) if receipts else None
    reasons: list[str] = []
    if len(positives) < 3:
        reasons.append("missing_user_positive_samples")
    if not all(negative_detection.values()):
        reasons.append("known_negative_not_detected")
    if any(positive_blocking.values()):
        reasons.append("positive_sample_false_blocking")
    if len(receipts) < 10:
        reasons.append("insufficient_human_blind_pairs")
    elif win_rate is None or win_rate < 0.7:
        reasons.append("human_blind_win_rate_below_70_percent")
    return {
        "schema_version": 1,
        "status": "pass" if not reasons else "blocked",
        "quality_uplift_claim_allowed": not reasons,
        "negative_detection": negative_detection,
        "positive_blocking": positive_blocking,
        "positive_sample_count": len(positives),
        "human_blind_pair_count": len(receipts),
        "human_new_system_wins": wins,
        "human_new_system_win_rate": win_rate,
        "blocking_reasons": reasons,
    }
