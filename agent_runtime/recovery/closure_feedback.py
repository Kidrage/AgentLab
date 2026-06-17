"""P2-L Recovery History → Closure Quality Feedback.

Converts recovery history (failure events, diagnoses, plans, verdicts, human
reviews, retry attempts) into structured closure quality feedback that can be
consumed later by reviewer policy, router feedback, provider governance, skill
incubation, and future task planning.

All operations are deterministic and file-based. No LLM calls, no external
services, no database.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from agent_runtime.atomic_io import atomic_write_json, atomic_write_text


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class RecoveryHistoryEntry:
    """A single entry in the recovery timeline for one task."""
    task_id: str
    failure_id: Optional[str] = None
    event_type: str = ""
    status: str = ""
    category: Optional[str] = None
    verdict: Optional[str] = None
    next_action: Optional[str] = None
    evidence_artifacts: list[str] = field(default_factory=list)
    created_at: Optional[str] = None


@dataclass
class ClosureQualityFeedback:
    """Structured feedback derived from recovery history and closure artifacts."""
    task_id: str
    verdict: str = "unknown"
    quality_score: Optional[float] = None
    recovery_used: bool = False
    recovery_successful: Optional[bool] = None
    failure_categories: list[str] = field(default_factory=list)
    retry_count: int = 0
    human_review_required: bool = False
    blocked_reason: Optional[str] = None
    lessons: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    evidence_artifacts: list[str] = field(default_factory=list)


# ── Loading ──────────────────────────────────────────────────────────────────

def _safe_load_json(path: Path) -> dict[str, Any] | None:
    """Load a JSON file, returning None on any failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _safe_load_json_list(path: Path) -> list[dict[str, Any]]:
    """Load a JSON file that contains a list, returning empty list on failure."""
    data = _safe_load_json(path)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # Some files wrap list under "attempts" or similar key
        for key in ("attempts", "decisions", "entries", "items"):
            if key in data and isinstance(data[key], list):
                return data[key]
        return [data]
    return []


def _matches_recovery_signal(text: str | None, signals: list[str]) -> bool:
    """Case-insensitive check whether *text* contains any of *signals*."""
    if not text:
        return False
    lowered = text.lower()
    return any(sig in lowered for sig in signals)


def load_recovery_history(task_run_dir: Path) -> tuple[list[RecoveryHistoryEntry], list[str]]:
    """Load recovery history entries from a task run directory.

    Returns (entries, warnings).  If the recovery directory is missing or empty,
    returns an empty list with an appropriate warning.
    """
    warnings: list[str] = []
    entries: list[RecoveryHistoryEntry] = []

    recovery_dir = task_run_dir / "recovery"
    if not recovery_dir.exists():
        warnings.append("no_recovery_directory")
        return entries, warnings

    task_id = task_run_dir.name

    # ── Top-level artifacts ──────────────────────────────────────────────

    # failure_event.json
    event_data = _safe_load_json(recovery_dir / "failure_event.json")
    if event_data is not None:
        entries.append(RecoveryHistoryEntry(
            task_id=task_id,
            event_type="failure_captured",
            status="captured",
            category=event_data.get("error_type"),
            created_at=event_data.get("created_at"),
            evidence_artifacts=[str(recovery_dir / "failure_event.json")],
        ))

    # failure_diagnosis.json
    diag_data = _safe_load_json(recovery_dir / "failure_diagnosis.json")
    if diag_data is not None:
        entries.append(RecoveryHistoryEntry(
            task_id=task_id,
            event_type="failure_diagnosed",
            status="diagnosed",
            category=diag_data.get("primary_category"),
            verdict=diag_data.get("recommended_next_action"),
            created_at=diag_data.get("created_at"),
            evidence_artifacts=[str(recovery_dir / "failure_diagnosis.json")],
        ))

    # recovery_plan.md
    plan_path = recovery_dir / "recovery_plan.md"
    if plan_path.exists():
        entries.append(RecoveryHistoryEntry(
            task_id=task_id,
            event_type="recovery_plan_generated",
            status="planned",
            evidence_artifacts=[str(plan_path)],
        ))

    # recovery_verdict.json
    verdict_data = _safe_load_json(recovery_dir / "recovery_verdict.json")
    if verdict_data is not None:
        verdict_val = verdict_data.get("verdict", "unknown")
        entries.append(RecoveryHistoryEntry(
            task_id=task_id,
            event_type="recovery_verdict",
            status="verdict",
            verdict=verdict_val,
            next_action=verdict_data.get("reason"),
            category=verdict_data.get("primary_category"),
            created_at=verdict_data.get("created_at"),
            evidence_artifacts=[str(recovery_dir / "recovery_verdict.json")],
        ))

    # ── Indexed failures ────────────────────────────────────────────────

    failures_dir = recovery_dir / "failures"
    if failures_dir.exists():
        for ev_path in sorted(failures_dir.glob("failure_event_*.json")):
            ev = _safe_load_json(ev_path)
            if ev is not None:
                entries.append(RecoveryHistoryEntry(
                    task_id=task_id,
                    failure_id=ev_path.stem,
                    event_type="failure_captured",
                    status="captured",
                    category=ev.get("error_type"),
                    created_at=ev.get("created_at"),
                    evidence_artifacts=[str(ev_path)],
                ))
            else:
                warnings.append(f"corrupt_failure_event:{ev_path.name}")

        for diag_path in sorted(failures_dir.glob("failure_diagnosis_*.json")):
            diag = _safe_load_json(diag_path)
            if diag is not None:
                entries.append(RecoveryHistoryEntry(
                    task_id=task_id,
                    failure_id=diag_path.stem,
                    event_type="failure_diagnosed",
                    status="diagnosed",
                    category=diag.get("primary_category"),
                    verdict=diag.get("recommended_next_action"),
                    created_at=diag.get("created_at"),
                    evidence_artifacts=[str(diag_path)],
                ))
            else:
                warnings.append(f"corrupt_diagnosis:{diag_path.name}")

        for vp in sorted(failures_dir.glob("recovery_verdict_*.json")):
            vd = _safe_load_json(vp)
            if vd is not None:
                verdict_val = vd.get("verdict", "unknown")
                entries.append(RecoveryHistoryEntry(
                    task_id=task_id,
                    failure_id=vp.stem,
                    event_type="recovery_verdict",
                    status="verdict",
                    verdict=verdict_val,
                    next_action=vd.get("reason"),
                    created_at=vd.get("created_at"),
                    evidence_artifacts=[str(vp)],
                ))
            else:
                warnings.append(f"corrupt_verdict:{vp.name}")

    # ── Human reviews ───────────────────────────────────────────────────

    reviews_dir = recovery_dir / "human_reviews"
    if reviews_dir.exists():
        for rp in sorted(reviews_dir.glob("human_review_*.json")):
            rd = _safe_load_json(rp)
            if rd is not None:
                decision = rd.get("decision", "unknown")
                entries.append(RecoveryHistoryEntry(
                    task_id=task_id,
                    event_type="human_review",
                    status=decision,
                    verdict=decision,
                    next_action=rd.get("reason"),
                    created_at=rd.get("created_at"),
                    evidence_artifacts=[str(rp)],
                ))
            else:
                warnings.append(f"corrupt_human_review:{rp.name}")

    # Top-level human_review_decision.json
    top_review = _safe_load_json(recovery_dir / "human_review_decision.json")
    if top_review is not None:
        decision = top_review.get("decision", "unknown")
        entries.append(RecoveryHistoryEntry(
            task_id=task_id,
            event_type="human_review",
            status=decision,
            verdict=decision,
            next_action=top_review.get("reason"),
            created_at=top_review.get("created_at"),
            evidence_artifacts=[str(recovery_dir / "human_review_decision.json")],
        ))

    # ── Retry attempts ──────────────────────────────────────────────────

    retry_path = recovery_dir / "retry_attempts.json"
    if retry_path.exists():
        retry_data = _safe_load_json(retry_path)
        if retry_data is not None:
            attempts = retry_data.get("attempts", []) if isinstance(retry_data, dict) else []
            if isinstance(retry_data, list):
                attempts = retry_data
            for i, attempt in enumerate(attempts):
                if isinstance(attempt, dict):
                    entries.append(RecoveryHistoryEntry(
                        task_id=task_id,
                        failure_id=f"retry_{i + 1}",
                        event_type="retry_attempt",
                        status=attempt.get("result", "unknown"),
                        verdict=attempt.get("verdict"),
                        next_action=attempt.get("command"),
                        category=attempt.get("failure_category"),
                        created_at=attempt.get("created_at"),
                        evidence_artifacts=[str(retry_path)],
                    ))
        else:
            warnings.append("corrupt_retry_attempts_file")

    if not entries:
        warnings.append("no_recovery_entries_found")

    return entries, warnings


# ── Feedback derivation ──────────────────────────────────────────────────────

def derive_closure_quality_feedback(
    task_id: str,
    recovery_history: list[RecoveryHistoryEntry],
    closure_artifacts: dict[str, Any] | None = None,
) -> ClosureQualityFeedback:
    """Derive closure quality feedback from recovery history.

    Args:
        task_id: The task identifier.
        recovery_history: Entries loaded by ``load_recovery_history``.
        closure_artifacts: Optional dict of closure artifacts (verdict, etc.).

    Returns:
        A ``ClosureQualityFeedback`` with deterministic analysis.
    """
    closure = closure_artifacts or {}

    # ── Recovery used ────────────────────────────────────────────────────

    recovery_signals = [
        "failure_captured", "failure_diagnosed", "recovery_plan_generated",
        "recovery_verdict", "retry_attempt", "human_review",
    ]
    recovery_used = any(
        e.event_type in recovery_signals for e in recovery_history
    )

    # ── Verdict ──────────────────────────────────────────────────────────

    raw_verdict = closure.get("verdict", closure.get("final_outcome", ""))
    if not raw_verdict:
        # Try to infer from recovery history
        for e in reversed(recovery_history):
            if e.event_type == "recovery_verdict" and e.verdict:
                raw_verdict = e.verdict
                break
            if e.event_type == "retry_attempt" and e.status:
                raw_verdict = e.status
                break

    verdict = "unknown"
    if raw_verdict:
        lowered = str(raw_verdict).lower()
        if any(sig in lowered for sig in ("pass", "success", "accepted", "passed", "completed")):
            verdict = "passed"
        elif any(sig in lowered for sig in ("fail", "failed", "blocked", "rejected", "stop", "error")):
            verdict = "failed"
        elif lowered == "retry":
            verdict = "retry"
        elif lowered == "continue":
            verdict = "exhausted"

    # ── Recovery successful ──────────────────────────────────────────────

    recovery_successful: Optional[bool] = None
    if recovery_used:
        if verdict == "passed":
            recovery_successful = True
        elif verdict == "failed":
            recovery_successful = False

    # ── Retry count ─────────────────────────────────────────────────────

    retry_signals = ["retry", "resume", "rerun"]
    retry_count = sum(
        1 for e in recovery_history
        if _matches_recovery_signal(e.next_action, retry_signals)
        or _matches_recovery_signal(e.verdict, retry_signals)
        or _matches_recovery_signal(e.status, retry_signals)
    )

    # ── Human review required ────────────────────────────────────────────

    human_signals = ["human_review", "approval_required", "rejected", "stopped", "blocked"]
    human_review_required = any(
        _matches_recovery_signal(e.verdict, human_signals)
        or _matches_recovery_signal(e.status, human_signals)
        or _matches_recovery_signal(e.event_type, ["human_review"])
        for e in recovery_history
    )

    # ── Failure categories ───────────────────────────────────────────────

    seen_categories: dict[str, None] = {}
    for e in recovery_history:
        if e.category:
            seen_categories[e.category] = None
    failure_categories = list(seen_categories.keys())

    # ── Blocked reason ───────────────────────────────────────────────────

    blocked_reason: Optional[str] = None
    if verdict == "failed":
        for e in reversed(recovery_history):
            if e.event_type == "human_review" and e.status in ("reject_retry", "stop", "rejected"):
                blocked_reason = e.next_action or e.status
                break
            if e.verdict in ("stop", "blocked", "rejected"):
                blocked_reason = e.next_action or e.verdict
                break

    # ── Quality score ────────────────────────────────────────────────────

    quality_score: Optional[float] = None

    if verdict == "passed":
        quality_score = 1.0
    elif verdict == "unknown":
        quality_score = 0.5
    elif verdict in ("failed", "retry", "exhausted"):
        quality_score = 0.0
    else:
        quality_score = 0.5

    if quality_score is not None:
        # Subtract per retry
        quality_score = max(0.0, quality_score - 0.05 * retry_count)
        # Subtract for human review
        if human_review_required:
            quality_score = max(0.0, quality_score - 0.10)
        # Bonus for successful recovery
        if recovery_successful is True:
            quality_score = min(1.0, quality_score + 0.10)

    # ── Lessons ──────────────────────────────────────────────────────────

    lessons: list[str] = []

    if not recovery_used:
        lessons.append(
            "No recovery history found; closure feedback is limited."
        )
    else:
        if recovery_successful is True:
            lessons.append(
                "Recovery was required before closure; future reviewer should "
                "inspect failure evidence before accepting similar tasks."
            )
        if retry_count >= 2:
            lessons.append(
                "Repeated retries occurred; router should consider a safer "
                "executor or smaller task split."
            )
        if human_review_required:
            lessons.append(
                "Human review was required; future tasks in this category "
                "should keep approval gates enabled."
            )
        if verdict == "failed" and recovery_used:
            lessons.append(
                "Recovery was attempted but closure failed; root cause may "
                "require task redesign rather than retry."
            )
        if not lessons:
            lessons.append(
                "Recovery history present but no strong lesson pattern detected."
            )

    # ── Recommended actions ──────────────────────────────────────────────

    recommended_actions: list[str] = []

    if not recovery_used:
        recommended_actions.append("no_action")
    else:
        if human_review_required:
            recommended_actions.append("keep_recovery_gate_enabled")
        if retry_count >= 2:
            recommended_actions.append("prefer_smaller_task_split")
        if recovery_successful is False and human_review_required:
            recommended_actions.append("route_similar_failures_to_human_review")
        if verdict == "passed" and recovery_used:
            recommended_actions.append("increase_test_evidence_requirement")
        if not recommended_actions:
            recommended_actions.append("no_action")

    # ── Evidence artifacts ───────────────────────────────────────────────

    evidence_artifacts = closure.get("evidence_artifacts", [])
    if not evidence_artifacts:
        for e in recovery_history:
            evidence_artifacts.extend(e.evidence_artifacts)

    return ClosureQualityFeedback(
        task_id=task_id,
        verdict=verdict,
        quality_score=quality_score,
        recovery_used=recovery_used,
        recovery_successful=recovery_successful,
        failure_categories=failure_categories,
        retry_count=retry_count,
        human_review_required=human_review_required,
        blocked_reason=blocked_reason,
        lessons=lessons,
        recommended_actions=recommended_actions,
        evidence_artifacts=evidence_artifacts,
    )


# ── Output writers ───────────────────────────────────────────────────────────

def _feedback_to_dict(fb: ClosureQualityFeedback) -> dict[str, Any]:
    """Serialize a ClosureQualityFeedback to a plain dict for JSON output."""
    return {
        "task_id": fb.task_id,
        "verdict": fb.verdict,
        "quality_score": fb.quality_score,
        "recovery_used": fb.recovery_used,
        "recovery_successful": fb.recovery_successful,
        "failure_categories": fb.failure_categories,
        "retry_count": fb.retry_count,
        "human_review_required": fb.human_review_required,
        "blocked_reason": fb.blocked_reason,
        "lessons": fb.lessons,
        "recommended_actions": fb.recommended_actions,
        "evidence_artifacts": fb.evidence_artifacts,
    }


def write_closure_feedback_json(
    feedback: ClosureQualityFeedback,
    output_dir: Path,
) -> Path:
    """Write ``closure_quality_feedback.json`` to *output_dir*."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "closure_quality_feedback.json"
    atomic_write_json(path, _feedback_to_dict(feedback))
    return path


def write_closure_feedback_report(
    feedback: ClosureQualityFeedback,
    output_dir: Path,
) -> Path:
    """Write ``closure_quality_feedback.md`` to *output_dir*."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "closure_quality_feedback.md"

    lines = [
        "# Closure Quality Feedback",
        "",
        f"**Task ID:** `{feedback.task_id}`",
        "",
        "## Verdict",
        "",
        f"- **Final Verdict:** {feedback.verdict}",
    ]

    if feedback.quality_score is not None:
        lines.append(f"- **Quality Score:** {feedback.quality_score:.2f}")
    else:
        lines.append("- **Quality Score:** N/A")

    lines += [
        f"- **Recovery Used:** {feedback.recovery_used}",
        f"- **Recovery Successful:** {feedback.recovery_successful}",
        f"- **Retry Count:** {feedback.retry_count}",
        f"- **Human Review Required:** {feedback.human_review_required}",
    ]

    if feedback.blocked_reason:
        lines.append(f"- **Blocked Reason:** {feedback.blocked_reason}")

    lines.append("")

    if feedback.failure_categories:
        lines.append("## Failure Categories")
        lines.append("")
        for cat in feedback.failure_categories:
            lines.append(f"- `{cat}`")
        lines.append("")
    else:
        lines.append("## Failure Categories")
        lines.append("")
        lines.append("None recorded.")
        lines.append("")

    lines.append("## Lessons Learned")
    lines.append("")
    if feedback.lessons:
        for lesson in feedback.lessons:
            lines.append(f"- {lesson}")
    else:
        lines.append("- No lessons recorded.")
    lines.append("")

    lines.append("## Recommended Actions")
    lines.append("")
    if feedback.recommended_actions:
        for action in feedback.recommended_actions:
            lines.append(f"- `{action}`")
    else:
        lines.append("- No actions recommended.")
    lines.append("")

    if feedback.evidence_artifacts:
        lines.append("## Evidence Artifacts")
        lines.append("")
        for art in feedback.evidence_artifacts:
            lines.append(f"- `{art}`")
        lines.append("")

    lines.append("## Quality Score Heuristic")
    lines.append("")
    lines.append(
        "The quality score is a deterministic heuristic, not a business-grade "
        "metric. Rules:"
    )
    lines.append("")
    lines.append("- Start at 1.0 if closure passed/accepted.")
    lines.append("- Start at 0.5 if closure unknown.")
    lines.append("- Start at 0.0 if closure failed/blocked/rejected.")
    lines.append("- Subtract 0.05 per retry, floor at 0.0.")
    lines.append("- Subtract 0.10 if human review was required.")
    lines.append("- Add 0.10 if recovery succeeded after initial failure, cap at 1.0.")
    lines.append("")

    lines.append("## Limitations")
    lines.append("")
    lines.append("- Passive feedback only — does not mutate live router or provider policy.")
    lines.append("- Heuristic quality score — not calibrated against production data.")
    lines.append("- No dashboard or web UI.")
    lines.append("- Lessons are deterministic templates, not LLM-generated prose.")
    lines.append("")

    report = "\n".join(lines)
    atomic_write_text(path, report)
    return path


# ── CLI entrypoint ───────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: generate closure quality feedback from a task run directory.

    Usage::

        python -m agent_runtime.recovery.closure_feedback --task-run-dir <path>
        python -m agent_runtime.recovery.closure_feedback --task-id <id> --project <name>
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate P2-L closure quality feedback from recovery history.",
    )
    parser.add_argument(
        "--task-run-dir",
        type=Path,
        default=None,
        help="Path to a task run directory (e.g. projects/<Project>/runs/<task_id>).",
    )
    parser.add_argument(
        "--task-id",
        type=str,
        default=None,
        help="Task identifier (requires --project).",
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
        help="Project name (required with --task-id).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for feedback artifacts (default: task run dir).",
    )
    args = parser.parse_args(argv)

    # Resolve run directory
    run_dir: Path | None = None
    if args.task_run_dir:
        run_dir = args.task_run_dir
    elif args.task_id and args.project:
        # Resolve AgentLab root: go up from this file to repo root
        agentlab_root = Path(__file__).resolve().parents[2]
        run_dir = agentlab_root / "projects" / args.project / "runs" / args.task_id
    else:
        parser.error("Either --task-run-dir or (--task-id + --project) is required.")

    if not run_dir.exists():
        print(f"ERROR: Task run directory does not exist: {run_dir}", file=sys.stderr)
        return 1

    output_dir = args.output_dir or run_dir
    task_id = run_dir.name

    # Load
    print(f"Loading recovery history from {run_dir} ...")
    history, warnings = load_recovery_history(run_dir)

    for w in warnings:
        print(f"  [WARNING] {w}")

    # Derive
    feedback = derive_closure_quality_feedback(
        task_id=task_id,
        recovery_history=history,
    )

    # Write
    json_path = write_closure_feedback_json(feedback, output_dir)
    md_path = write_closure_feedback_report(feedback, output_dir)

    print(f"\nClosure Quality Feedback — {task_id}")
    print(f"  Verdict:            {feedback.verdict}")
    print(f"  Quality Score:      {feedback.quality_score}")
    print(f"  Recovery Used:      {feedback.recovery_used}")
    print(f"  Recovery Success:   {feedback.recovery_successful}")
    print(f"  Retry Count:        {feedback.retry_count}")
    print(f"  Human Review:       {feedback.human_review_required}")
    if feedback.blocked_reason:
        print(f"  Blocked Reason:     {feedback.blocked_reason}")
    print(f"  Lessons:            {len(feedback.lessons)}")
    print(f"  Recommended Actions: {feedback.recommended_actions}")
    print(f"\n  JSON: {json_path}")
    print(f"  MD:   {md_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
