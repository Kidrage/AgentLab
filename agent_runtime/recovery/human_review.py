"""Human review decision: durable record of human decisions on recovery."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class DecisionType(str):
    APPROVE_RETRY = "approve_retry"
    REJECT_RETRY = "reject_retry"
    MARK_SAFE = "mark_safe"
    STOP = "stop"


@dataclass
class HumanReviewDecision:
    """A human decision on a recovery verdict.

    Written as a durable artifact in recovery/human_reviews/.
    Multiple decisions are indexed and never overwritten.
    """

    task_id: str
    decision: str  # approve_retry | reject_retry | mark_safe | stop
    reason: str
    created_at: str
    source: str = "cli"
    applies_to_failure_index: int = 1
    force_used: bool = False

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "decision": self.decision,
            "reason": self.reason,
            "created_at": self.created_at,
            "source": self.source,
            "applies_to_failure_index": self.applies_to_failure_index,
            "force_used": self.force_used,
        }

    @classmethod
    def from_dict(cls, data: dict) -> HumanReviewDecision:
        return cls(
            task_id=data.get("task_id", ""),
            decision=data.get("decision", ""),
            reason=data.get("reason", ""),
            created_at=data.get("created_at", ""),
            source=data.get("source", "cli"),
            applies_to_failure_index=data.get("applies_to_failure_index", 1),
            force_used=data.get("force_used", False),
        )


def write_human_review_decision(
    run_dir: Path,
    task_id: str,
    decision: str,
    reason: str,
    *,
    source: str = "cli",
    applies_to_failure_index: int = 1,
    force_used: bool = False,
) -> Path:
    """Write a human review decision as a durable artifact.

    Decisions are indexed under recovery/human_reviews/ to preserve history.
    Also writes the latest decision at recovery/human_review_decision.json.

    Returns the path of the indexed decision file.
    """
    reviews_dir = run_dir / "recovery" / "human_reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)

    existing = sorted(reviews_dir.glob("human_review_*.json"))
    index = len(existing) + 1

    decision_obj = HumanReviewDecision(
        task_id=task_id,
        decision=decision,
        reason=reason,
        created_at=datetime.now(timezone.utc).isoformat(),
        source=source,
        applies_to_failure_index=applies_to_failure_index,
        force_used=force_used,
    )

    indexed_path = reviews_dir / f"human_review_{index}.json"
    indexed_path.write_text(
        json.dumps(decision_obj.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Write latest copy
    latest_path = run_dir / "recovery" / "human_review_decision.json"
    latest_path.write_text(
        json.dumps(decision_obj.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return indexed_path


def load_latest_human_review_decision(run_dir: Path) -> HumanReviewDecision | None:
    """Load the latest human review decision, if any."""
    latest_path = run_dir / "recovery" / "human_review_decision.json"
    if not latest_path.exists():
        return None
    try:
        data = json.loads(latest_path.read_text(encoding="utf-8"))
        return HumanReviewDecision.from_dict(data)
    except (json.JSONDecodeError, KeyError):
        return None


def load_all_human_review_decisions(run_dir: Path) -> list[HumanReviewDecision]:
    """Load all human review decisions in order."""
    reviews_dir = run_dir / "recovery" / "human_reviews"
    if not reviews_dir.exists():
        return []
    decisions = []
    for path in sorted(reviews_dir.glob("human_review_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            decisions.append(HumanReviewDecision.from_dict(data))
        except (json.JSONDecodeError, KeyError):
            continue
    return decisions