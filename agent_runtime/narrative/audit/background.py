"""Background execution seam for deterministic and risk-tiered narrative audit."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from agent_runtime.atomic_io import atomic_write_yaml, safe_read_yaml
from agent_runtime.narrative.audit.execution import execute_tiered_audit
from agent_runtime.narrative.audit.precheck import (
    candidate_manifest_from_audit_bundle,
    run_deterministic_precheck,
)


def prepare_and_precheck_audit(
    request: dict[str, Any],
    *,
    task_id: str,
) -> dict[str, Any]:
    """Prepare the exact requested chapter window and run cheap checks once."""
    from agent_runtime.narrative_heavy_audit import prepare_crown_narrative_heavy_audit

    root = Path(request["agentlab_root"])
    batch = request["batch"]
    audit_window = request.get("audit_window")
    chapter_ids = (
        [int(item) for item in audit_window.get("audit_chapters") or []]
        if isinstance(audit_window, dict)
        else list(range(int(batch["start"]), int(batch["end"]) + 1))
    )
    try:
        from agent_runtime.narrative.quality.selection import (
            load_selected_revision_records,
        )

        draft_bindings = load_selected_revision_records(request)
    except ValueError as exc:
        return {
            "prepared": {"status": "blocked", "issues": [str(exc)]},
            "precheck": None,
        }
    prepared = prepare_crown_narrative_heavy_audit(
        root,
        eval_id=str(request["config"]["eval_id"]),
        start_chapter=int(batch["start"]),
        end_chapter=int(batch["end"]),
        task_id=task_id,
        chapter_ids=chapter_ids,
        draft_bindings=draft_bindings,
    )
    if prepared.get("status") != "ready":
        return {"prepared": prepared, "precheck": None}
    manifest_path = Path(str(prepared["manifest_path"]))
    audit_manifest = safe_read_yaml(manifest_path, default={}) or {}
    source_root = root / "projects" / request["project"]
    candidate_manifest = candidate_manifest_from_audit_bundle(
        audit_manifest if isinstance(audit_manifest, dict) else {},
        source_root=source_root,
    )
    precheck = run_deterministic_precheck(
        candidate_manifest,
        source_root=source_root,
        required_chapters=chapter_ids,
        expected_manifest_version=1,
    )
    run_dir = Path(str(prepared.get("run_dir") or manifest_path.parent))
    atomic_write_yaml(run_dir / "deterministic_precheck.yml", precheck)
    return {"prepared": prepared, "precheck": precheck}


def _evidence_status(run_dir: Path) -> str:
    for name in (
        "fiction_review.yml",
        "continuity_failure_report.yml",
        "narrative_quality_scorecard.yml",
    ):
        value = safe_read_yaml(run_dir / name, default={}) or {}
        if not isinstance(value, Mapping):
            return "blocked"
        if str(value.get("status") or "").lower() in {
            "block",
            "blocked",
            "fail",
            "failed",
            "rejected",
        }:
            return "blocked"
        if int(value.get("blocking_issue_count") or 0) > 0:
            return "blocked"
    return "pass"


def run_tiered_followup(
    request: dict[str, Any],
    *,
    primary_task_id: str,
    primary_pipeline: Mapping[str, Any],
) -> dict[str, object]:
    """Apply one primary judgment to all chapters and add only risk-triggered judges."""
    from agent_runtime.narrative.audit.runtime import run_single_judge_pipeline

    root = Path(request["agentlab_root"])
    project = str(request["project"])
    primary_run = root / "projects" / project / "runs" / primary_task_id
    primary_receipt = dict(primary_pipeline.get("judge_receipt") or {})
    primary_receipt["status"] = _evidence_status(primary_run)
    execution_plan = request.get("narrative_execution_plan")
    chapter_plans = (
        execution_plan.get("chapters")
        if isinstance(execution_plan, Mapping)
        else []
    )
    audit_window = request.get("audit_window")
    allowed_chapters = (
        {int(item) for item in audit_window.get("audit_chapters") or []}
        if isinstance(audit_window, Mapping)
        else None
    )
    results: list[dict[str, object]] = []
    for raw_plan in chapter_plans or []:
        if not isinstance(raw_plan, Mapping):
            continue
        plan = dict(raw_plan)
        chapter_id = int(plan["chapter_id"])
        if allowed_chapters is not None and chapter_id not in allowed_chapters:
            continue
        second_receipt: dict[str, Any] | None = None
        if int(plan.get("judge_count") or 1) > 1:
            secondary_task_id = f"{primary_task_id}_ch{chapter_id:03d}_judge2"[:120]
            secondary_request = {
                **request,
                "batch": {"start": chapter_id, "end": chapter_id},
                "audit_window": None,
            }
            prepared = prepare_and_precheck_audit(
                secondary_request,
                task_id=secondary_task_id,
            )
            precheck = prepared.get("precheck")
            if not isinstance(precheck, Mapping) or precheck.get("status") != "pass":
                return {
                    "status": "execution_failed",
                    "reason": "second_judge_precheck_blocked",
                    "chapter_id": chapter_id,
                }
            pipeline = run_single_judge_pipeline(
                root,
                project=project,
                task_id=secondary_task_id,
                budget_mode="max-quality",
            )
            if not pipeline.get("success"):
                return {
                    "status": "execution_failed",
                    "reason": pipeline.get("blocked_reason")
                    or "second_judge_pipeline_failed",
                    "chapter_id": chapter_id,
                }
            second_receipt = dict(pipeline.get("judge_receipt") or {})
            second_receipt["status"] = _evidence_status(
                root / "projects" / project / "runs" / secondary_task_id
            )
        result = execute_tiered_audit(
            plan,
            deterministic_precheck={"status": "pass", "blocking_codes": []},
            primary_judge=lambda _chapter, receipt=primary_receipt: receipt,
            second_judge=(
                (lambda _chapter, receipt=second_receipt: receipt)
                if second_receipt is not None
                else None
            ),
            arbitrator=lambda _chapter, _primary, _second: {
                "status": "blocked",
                "reason": "judge_conflict_requires_human_or_independent_arbitration",
            },
        )
        results.append(result)
    receipt = {
        "schema_version": 1,
        "status": (
            "blocked"
            if any(result.get("status") != "pass" for result in results)
            else "pass"
        ),
        "chapters": results,
    }
    atomic_write_yaml(primary_run / "tiered_audit_receipt.yml", receipt)
    return receipt
