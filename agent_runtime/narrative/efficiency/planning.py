"""Risk-tiered narrative production and audit planning."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


HIGH_RISK_SIGNALS = frozenset(
    {
        "arc_boundary",
        "key_reveal",
        "new_pov",
        "major_character_decision",
        "existing_warning",
        "existing_blocking",
        "foreshadowing_payoff",
        "user_priority",
    }
)


def plan_chapter_execution(
    chapters: Iterable[int],
    *,
    risk_signals: Mapping[int, Iterable[str]] | None = None,
) -> dict[str, object]:
    """Return the least expensive allowed plan for each chapter."""
    signals_by_chapter = risk_signals or {}
    planned: list[dict[str, object]] = []
    for chapter in chapters:
        chapter_id = int(chapter)
        signals = sorted(set(str(item) for item in signals_by_chapter.get(chapter_id, ())))
        high_risk = bool(HIGH_RISK_SIGNALS.intersection(signals))
        if high_risk:
            planned.append(
                {
                    "chapter_id": chapter_id,
                    "risk_tier": "high",
                    "risk_signals": signals,
                    "strategy_count": 2,
                    "candidate_count": 2,
                    "judge_count": 2,
                    "audit_stages": [
                        "deterministic_precheck",
                        "primary_literary_judge",
                        "independent_second_judge",
                        "conflict_arbitration_if_needed",
                    ],
                }
            )
            continue
        planned.append(
            {
                "chapter_id": chapter_id,
                "risk_tier": "ordinary",
                "risk_signals": signals,
                "strategy_count": 1,
                "candidate_count": 1,
                "judge_count": 1,
                "audit_stages": [
                    "deterministic_precheck",
                    "primary_literary_judge",
                ],
            }
        )
    return {"schema_version": 1, "chapters": planned}


def compute_incremental_audit_window(
    *,
    changed_chapters: Iterable[int],
    available_chapters: Iterable[int],
    fact_dependencies: Mapping[int, Iterable[int]] | None = None,
    full_reaudit_reason: str | None = None,
) -> dict[str, object]:
    """Bound re-audit to edits, immediate neighbors, and declared fact impacts."""
    available = sorted(set(int(chapter) for chapter in available_chapters))
    available_set = set(available)
    changed = sorted(set(int(chapter) for chapter in changed_chapters))
    if full_reaudit_reason:
        return {
            "mode": "full",
            "changed_chapters": changed,
            "audit_chapters": available,
            "excluded_chapters": [],
            "reason": str(full_reaudit_reason),
        }
    dependencies = fact_dependencies or {}
    audit: set[int] = set()
    for chapter in changed:
        audit.update(
            candidate
            for candidate in (chapter - 1, chapter, chapter + 1)
            if candidate in available_set
        )
        audit.update(
            int(candidate)
            for candidate in dependencies.get(chapter, ())
            if int(candidate) in available_set
        )
    audit_chapters = sorted(audit)
    return {
        "mode": "incremental",
        "changed_chapters": changed,
        "audit_chapters": audit_chapters,
        "excluded_chapters": [
            chapter for chapter in available if chapter not in audit
        ],
        "reason": "changed_neighbors_and_fact_dependencies",
    }


def select_batch_plan(
    plan: Mapping[str, object], *, start_chapter: int, end_chapter: int
) -> dict[str, object]:
    """Select one persisted chapter-plan window without reclassifying it."""
    records = plan.get("chapters")
    if not isinstance(records, list):
        records = []
    return {
        "schema_version": int(plan.get("schema_version") or 1),
        "chapters": [
            dict(record)
            for record in records
            if isinstance(record, Mapping)
            and start_chapter <= int(record.get("chapter_id") or 0) <= end_chapter
        ],
    }
