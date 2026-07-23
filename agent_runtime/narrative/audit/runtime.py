"""Provider-backed adapters for the tiered narrative audit seam."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def run_single_judge_pipeline(
    root: Path,
    *,
    project: str,
    task_id: str,
    budget_mode: str = "balanced",
) -> dict[str, Any]:
    """Run only the Reviewer role and materialize its required audit evidence."""
    from agent_runtime.agent_runner import run_agent_model
    from agent_runtime.narrative_heavy_audit import (
        materialize_narrative_heavy_audit_result,
    )
    from agent_runtime.workflow_plan import build_workflow_plan

    plan = build_workflow_plan(
        Path(root),
        project,
        task_id,
        budget_mode=budget_mode,
    )
    run_dir = Path(plan.run_dir)
    result = run_agent_model(
        Path(root),
        plan,
        "Reviewer",
        run_dir / "reviewer_role_session_capture.md",
    )
    materialized = materialize_narrative_heavy_audit_result(
        result,
        run_dir,
        task_id,
        "Reviewer",
    )
    return {
        "success": bool(materialized),
        "blocked_reason": None if materialized else "single_judge_materialization_failed",
        "judge_receipt": {
            "judge_id": "Reviewer",
            "provider": getattr(result, "provider", None),
            "model": getattr(result, "model", None),
            "status": getattr(result, "status", None),
            "context_id": task_id,
        },
    }


def run_revision_support_pipeline(
    root: Path,
    *,
    project: str,
    task_id: str,
    budget_mode: str = "balanced",
) -> dict[str, Any]:
    """Run state/proposal roles only after structured audit evidence requests revision."""
    receipts: list[dict[str, Any]] = []
    for role in ("Scribe", "Verifier"):
        receipt = run_revision_support_role(
            root,
            project=project,
            task_id=task_id,
            role=role,
            budget_mode=budget_mode,
        )
        if not receipt.get("success"):
            return {
                "success": False,
                "blocked_reason": receipt.get("blocked_reason"),
                "role_receipts": receipts,
            }
        receipts.append(dict(receipt["role_receipt"]))
    return {"success": True, "role_receipts": receipts}


def run_revision_support_role(
    root: Path,
    *,
    project: str,
    task_id: str,
    role: str,
    budget_mode: str = "balanced",
) -> dict[str, Any]:
    """Run exactly one resumable post-finding role."""
    if role not in {"Scribe", "Verifier"}:
        raise ValueError("unsupported revision support role")
    from agent_runtime.agent_runner import run_agent_model
    from agent_runtime.narrative_heavy_audit import (
        materialize_narrative_heavy_audit_result,
    )
    from agent_runtime.workflow_plan import build_workflow_plan

    plan = build_workflow_plan(Path(root), project, task_id, budget_mode=budget_mode)
    run_dir = Path(plan.run_dir)
    result = run_agent_model(
        Path(root),
        plan,
        role,
        run_dir / f"{role.lower()}_role_session_capture.md",
    )
    if not materialize_narrative_heavy_audit_result(
        result,
        run_dir,
        task_id,
        role,
    ):
        return {
            "success": False,
            "blocked_reason": f"{role.lower()}_materialization_failed",
            "provider_result": result,
        }
    return {
        "success": True,
        "role_receipt": {
            "role": role,
            "provider": getattr(result, "provider", None),
            "model": getattr(result, "model", None),
            "status": getattr(result, "status", None),
        },
    }
