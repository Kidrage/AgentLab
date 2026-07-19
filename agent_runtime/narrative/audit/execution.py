"""Risk-tiered literary audit orchestration behind one small interface."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


Judge = Callable[[int], Mapping[str, Any]]
Arbitrator = Callable[[int, Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]


def execute_tiered_audit(
    chapter_plan: Mapping[str, Any],
    *,
    deterministic_precheck: Mapping[str, Any],
    primary_judge: Judge,
    second_judge: Judge | None = None,
    arbitrator: Arbitrator | None = None,
) -> dict[str, object]:
    """Run only the judge stages authorized by a chapter risk plan."""
    chapter_id = int(chapter_plan["chapter_id"])
    if deterministic_precheck.get("status") != "pass":
        return {
            "schema_version": 1,
            "chapter_id": chapter_id,
            "status": "blocked",
            "deterministic_precheck": dict(deterministic_precheck),
            "judge_receipts": [],
            "arbitration": None,
        }

    primary = dict(primary_judge(chapter_id))
    receipts = [primary]
    arbitration: dict[str, Any] | None = None
    if int(chapter_plan.get("judge_count") or 1) > 1:
        if second_judge is None:
            raise ValueError("high-risk audit requires a second judge")
        second = dict(second_judge(chapter_id))
        receipts.append(second)
        if (
            primary.get("judge_id") == second.get("judge_id")
            and primary.get("context_id") == second.get("context_id")
        ):
            return {
                "schema_version": 1,
                "chapter_id": chapter_id,
                "status": "blocked",
                "deterministic_precheck": dict(deterministic_precheck),
                "judge_receipts": receipts,
                "arbitration": {
                    "status": "blocked",
                    "reason": "judge_independence_not_proven",
                },
            }
        if primary.get("status") != second.get("status"):
            if arbitrator is None:
                arbitration = {
                    "status": "blocked",
                    "reason": "judge_conflict_requires_arbitration",
                }
            else:
                arbitration = dict(arbitrator(chapter_id, primary, second))
        status = str(
            (arbitration or {}).get("status")
            or (
                "pass"
                if primary.get("status") == second.get("status") == "pass"
                else "blocked"
            )
        )
    else:
        status = "pass" if primary.get("status") == "pass" else "blocked"
    return {
        "schema_version": 1,
        "chapter_id": chapter_id,
        "status": status,
        "deterministic_precheck": dict(deterministic_precheck),
        "judge_receipts": receipts,
        "arbitration": arbitration,
    }
