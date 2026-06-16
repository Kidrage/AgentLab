"""Recovery closure summary: include recovery history in final task report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def build_recovery_closure_summary(run_dir: Path) -> dict | None:
    """Build a recovery summary for inclusion in closure reports.

    Returns None if no recovery artifacts exist.
    Does not expose secrets — reuses existing redaction behavior.
    """
    recovery_dir = run_dir / "recovery"
    if not recovery_dir.exists():
        return None

    summary: dict = {
        "has_recovery_artifacts": True,
        "failure_count": 0,
        "categories": [],
        "verdict_history": [],
        "human_decisions": [],
        "retry_attempts": 0,
        "final_outcome": "unknown",
    }

    # Count indexed failures
    failures_dir = recovery_dir / "failures"
    if failures_dir.exists():
        indexed = sorted(failures_dir.glob("failure_event_*.json"))
        summary["failure_count"] = len(indexed)

        # Collect categories from diagnosis files
        for diag_path in sorted(failures_dir.glob("failure_diagnosis_*.json")):
            try:
                data = json.loads(diag_path.read_text(encoding="utf-8"))
                cat = data.get("primary_category", "unknown")
                if cat not in summary["categories"]:
                    summary["categories"].append(cat)
            except (json.JSONDecodeError, KeyError):
                pass

        # Collect verdict history
        for verdict_path in sorted(failures_dir.glob("recovery_verdict_*.json")):
            try:
                data = json.loads(verdict_path.read_text(encoding="utf-8"))
                summary["verdict_history"].append({
                    "verdict": data.get("verdict", "unknown"),
                    "reason": data.get("reason", "")[:200],
                })
            except (json.JSONDecodeError, KeyError):
                pass

    # Also check top-level verdict
    verdict_path = recovery_dir / "recovery_verdict.json"
    if verdict_path.exists() and not summary["verdict_history"]:
        try:
            data = json.loads(verdict_path.read_text(encoding="utf-8"))
            summary["verdict_history"].append({
                "verdict": data.get("verdict", "unknown"),
                "reason": data.get("reason", "")[:200],
            })
        except (json.JSONDecodeError, KeyError):
            pass

    # Human decisions
    reviews_dir = recovery_dir / "human_reviews"
    if reviews_dir.exists():
        for review_path in sorted(reviews_dir.glob("human_review_*.json")):
            try:
                data = json.loads(review_path.read_text(encoding="utf-8"))
                summary["human_decisions"].append({
                    "decision": data.get("decision", "unknown"),
                    "reason": data.get("reason", "")[:200],
                    "force_used": data.get("force_used", False),
                })
            except (json.JSONDecodeError, KeyError):
                pass

    # Retry attempts
    retry_path = recovery_dir / "retry_attempts.json"
    if retry_path.exists():
        try:
            data = json.loads(retry_path.read_text(encoding="utf-8"))
            attempts = data.get("attempts", [])
            summary["retry_attempts"] = len(attempts)
            # Determine final outcome from last attempt
            if attempts:
                last = attempts[-1]
                summary["final_outcome"] = last.get("result", "unknown")
        except (json.JSONDecodeError, KeyError):
            pass

    # Determine final outcome from verdict if no retry attempts
    if summary["retry_attempts"] == 0 and summary["verdict_history"]:
        last_verdict = summary["verdict_history"][-1]["verdict"]
        if last_verdict == "retry":
            summary["final_outcome"] = "recoverable"
        elif last_verdict in ("stop", "human_review"):
            summary["final_outcome"] = "blocked"
        elif last_verdict == "continue":
            summary["final_outcome"] = "exhausted"

    return summary