"""P2-F Closure Runner: orchestrate review → verdict → revision → governance → router feedback."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.governance.models import GovernanceDecision
from agent_runtime.governance.performance import (
    build_provider_performance_profiles,
    derive_governance_decisions,
)
from agent_runtime.p2_closure.capability_map import scan_p2_capabilities, write_capability_map
from agent_runtime.p2_closure.evidence import (
    write_provider_feedback,
    write_review_verdict,
    write_revision_packet,
    write_router_dry_run,
    write_router_feedback,
)
from agent_runtime.p2_closure.models import (
    P2ClosureResult,
    ProviderFeedback,
    RouterApplyResult,
    RouterFeedback,
)
from agent_runtime.p2_closure.report_writer import write_closure_report
from agent_runtime.review import ReviewTarget, load_review_policy, run_three_e_review
from agent_runtime.router_update.approval import load_router_patch_approval
from agent_runtime.router_update.models import (
    RouterPatchApproval,
    RouterPolicyPatch,
    RouterUpdatePolicy,
)
from agent_runtime.router_update.patch_applier import apply_router_policy_patch
from agent_runtime.router_update.patch_builder import build_router_policy_patch
from agent_runtime.router_update.recommendation_loader import load_router_policy, load_router_update_policy
from agent_runtime.router_update.rollback import create_router_rollback_plan


def run_p2_closure(
    task_id: str,
    delivery_path: Path,
    output_dir: Path,
    config_root: Path | None = None,
    provider_id: str | None = None,
    executor: str | None = None,
    dry_run: bool = True,
    allow_router_apply: bool = False,
    approval_path: Path | None = None,
) -> P2ClosureResult:
    """Run the full P2-F closure pipeline.

    All operations are deterministic and local-first. No network calls,
    no external script execution, no secrets access.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    delivery_id = delivery_path.name
    if config_root is None:
        config_root = Path(__file__).resolve().parents[2] / "config"

    # Step 0: Capability Map
    cap_map_path = output_dir / "p2_capability_map.yml"
    cap_map = scan_p2_capabilities()
    write_capability_map(cap_map, cap_map_path)

    # Step 1: 3E Review
    review_policy = load_review_policy(config_root / "review_policy.yml")
    target = ReviewTarget(
        task_id=task_id,
        target_dir=delivery_path,
        handoff_path=delivery_path / "external_handoff.md",
        report_path=delivery_path / "p1_acceptance_report.md",
    )
    review_report = run_three_e_review(target, review_policy, output_dir)

    # Step 2: Write unified review verdict
    verdict_path = output_dir / "review_verdict.yml"
    write_review_verdict(
        task_id=task_id,
        delivery_id=delivery_id,
        review_report=review_report,
        provider_id=provider_id,
        executor=executor,
        output_path=verdict_path,
    )
    verdict_status = review_report.verdict.status
    verdict_normalized = _normalize(verdict_status)

    # Step 3: Revision Packet if needed
    revision_path: Optional[str] = None
    revision_required = verdict_normalized in {"needs_revision", "rejected", "unsafe"}
    if revision_required:
        scores = _extract_scores(verdict_path)
        failed_checks = [
            f"{f.severity.upper()} {f.category}: {f.message}"
            for f in review_report.findings
            if f.status == "fail"
        ]
        missing_evidence = list(review_report.summary.required_artifacts_missing)
        safety_findings = [
            {"severity": f.severity, "message": f.message}
            for f in review_report.findings
            if f.category in {"secrets", "safety"} and f.status == "fail"
        ]
        suggested_executor = _suggest_executor(verdict_normalized)
        revision_path = str(
            write_revision_packet(
                task_id=task_id,
                delivery_id=delivery_id,
                provider_id=provider_id or "unknown",
                executor=executor or "unknown",
                verdict=verdict_normalized,
                failed_checks=failed_checks,
                missing_evidence=missing_evidence,
                safety_findings=safety_findings,
                files_to_inspect=review_report.summary.changed_files,
                acceptance_criteria=[
                    "All required artifacts are present.",
                    "All required report sections include concrete evidence.",
                    "No safety findings in the delivery.",
                    "The next 3E review verdict is accepted.",
                ],
                suggested_executor=suggested_executor,
                output_path=output_dir / "revision_packet.md",
            )
        )

    # Step 4: Provider Governance Feedback
    scores = _extract_scores(verdict_path)
    failure_reasons = [
        f"{f.severity}/{f.category}: {f.message}"
        for f in review_report.findings
        if f.status == "fail"
    ]
    evidence_files = [
        str(verdict_path),
        str(review_report.markdown_path) if review_report.markdown_path else "",
    ]
    if revision_path:
        evidence_files.append(revision_path)

    provider_fb_path = output_dir / "provider_feedback.yml"
    write_provider_feedback(
        task_id=task_id,
        delivery_id=delivery_id,
        provider_id=provider_id or "unknown",
        executor=executor or "unknown",
        review_verdict=verdict_normalized,
        scores=scores,
        failure_reasons=failure_reasons,
        evidence_files=[f for f in evidence_files if f],
        output_path=provider_fb_path,
    )

    # Step 5: Router Feedback
    router_fb_path = output_dir / "router_feedback.yml"
    write_router_feedback(
        task_id=task_id,
        provider_id=provider_id or "unknown",
        review_verdict=verdict_normalized,
        governance_recommendation=_governance_recommendation(verdict_normalized, scores),
        failure_reasons=failure_reasons,
        evidence_files=[f for f in evidence_files if f],
        output_path=router_fb_path,
    )

    # Step 6: Router Update dry-run (always)
    router_dry_run_path = output_dir / "router_update_dry_run.yml"
    governance_rec = _governance_recommendation(verdict_normalized, scores)
    write_router_dry_run(
        task_id=task_id,
        provider_id=provider_id or "unknown",
        recommendation=governance_rec,
        output_path=router_dry_run_path,
    )

    # Step 7: Router apply (only if allowed + approval exists)
    router_apply_result: Optional[RouterApplyResult] = None
    router_apply_path: Optional[str] = None
    router_rollback_path: Optional[str] = None

    if allow_router_apply and not dry_run:
        router_apply_result, router_apply_path, router_rollback_path = _try_router_apply(
            task_id=task_id,
            provider_id=provider_id or "unknown",
            recommendation=governance_rec,
            config_root=config_root,
            output_dir=output_dir,
            approval_path=approval_path,
        )
    elif allow_router_apply and dry_run:
        # Dry-run with approval check
        if approval_path and approval_path.exists():
            router_apply_result = RouterApplyResult(
                patch_id=f"patch_{task_id}",
                applied=False,
                status="DRY_RUN_APPROVED",
                reasons=["dry-run mode; apply would succeed with provided approval"],
            )
        else:
            router_apply_result = RouterApplyResult(
                patch_id=f"patch_{task_id}",
                applied=False,
                status="APPROVAL_REQUIRED",
                reasons=["approval artifact missing or invalid"],
            )
        router_apply_path = str(output_dir / "router_update_apply_result.yml")
        atomic_write_yaml(
            Path(router_apply_path),
            {
                "patch_id": router_apply_result.patch_id,
                "applied": router_apply_result.applied,
                "status": router_apply_result.status,
                "reasons": router_apply_result.reasons,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    # Step 8: Build and write closure report
    report_path = output_dir / "p2_closure_report.md"
    write_closure_report(
        task_id=task_id,
        verdict_status=verdict_normalized,
        verdict_path=str(verdict_path),
        revision_path=revision_path,
        provider_feedback_path=str(provider_fb_path),
        router_feedback_path=str(router_fb_path),
        router_dry_run_path=str(router_dry_run_path),
        router_apply_path=router_apply_path,
        router_rollback_path=router_rollback_path,
        cap_map_path=str(cap_map_path),
        output_path=report_path,
    )

    return P2ClosureResult(
        task_id=task_id,
        delivery_id=delivery_id,
        verdict_status=verdict_normalized,
        output_dir=output_dir,
        capability_map_path=str(cap_map_path),
        review_verdict_path=str(verdict_path),
        revision_packet_path=revision_path,
        provider_feedback_path=str(provider_fb_path),
        router_feedback_path=str(router_fb_path),
        router_dry_run_path=str(router_dry_run_path),
        router_apply_result_path=router_apply_path,
        router_rollback_path=router_rollback_path,
        closure_report_path=str(report_path),
        verdict_reasons=review_report.verdict.reasons,
        revision_required=revision_required,
        provider_feedback=ProviderFeedback(
            task_id=task_id,
            delivery_id=delivery_id,
            provider_id=provider_id or "unknown",
            executor=executor or "unknown",
            review_verdict=verdict_normalized,
            quality_score=scores.get("overall", 0.0),
            artifact_completeness=scores.get("artifact_completeness", 0.0),
            test_confidence=scores.get("test_confidence", 0.0),
            safety_confidence=scores.get("safety_confidence", 0.0),
            retry_recommended=revision_required,
            failure_reasons=failure_reasons,
            governance_recommendation=governance_rec,
        ),
        router_feedback=RouterFeedback(
            task_id=task_id,
            provider_id=provider_id or "unknown",
            recommendation=governance_rec,
            reason=failure_reasons if failure_reasons else [f"{verdict_normalized} verdict"],
            confidence="high" if len(failure_reasons) >= 2 else "medium" if failure_reasons else "low",
            dry_run=True,
            apply_allowed=False,
            approval_required=True,
            evidence=[str(verdict_path), str(provider_fb_path)],
        ),
        router_apply=router_apply_result,
    )


def _try_router_apply(
    task_id: str,
    provider_id: str,
    recommendation: str,
    config_root: Path,
    output_dir: Path,
    approval_path: Path | None,
) -> tuple[RouterApplyResult, str, Optional[str]]:
    """Attempt router apply with approval check. Uses temp copy, never production."""
    router_policy_src = config_root / "executor_router.yml"
    update_policy_src = config_root / "router_update_policy.yml"

    # Create temp copies for safe apply
    temp_router = output_dir / "temp_router_policy.yml"
    temp_update = output_dir / "temp_update_policy.yml"

    if router_policy_src.exists():
        temp_router.write_text(router_policy_src.read_text())
    else:
        atomic_write_yaml(temp_router, {"executor_router": {"providers": [], "provider_priority": {"default": [provider_id]}, "safety": {"forbid_production_mutations": True}}})

    if update_policy_src.exists():
        temp_update.write_text(update_policy_src.read_text())
    else:
        atomic_write_yaml(temp_update, {
            "router_update_policy": {
                "enabled": True,
                "safety": {"allow_apply_to_production": False},
                "approval": {"method": "file_token", "token_file_name": "APPROVE_ROUTER_PATCH", "token_value": "APPROVED"},
            }
        })

    # Check approval
    if approval_path is None or not approval_path.exists():
        result = RouterApplyResult(
            patch_id=f"patch_{task_id}",
            applied=False,
            status="APPROVAL_REQUIRED",
            reasons=["approval_required"],
        )
        result_path = output_dir / "router_update_apply_result.yml"
        atomic_write_yaml(result_path, {
            "applied": False,
            "reason": "approval_required",
            "patch_id": result.patch_id,
            "status": result.status,
        })
        return result, str(result_path), None

    # Load approval
    update_policy = load_router_update_policy(temp_update)
    approval = load_router_patch_approval(
        RouterPolicyPatch(
            patch_id=f"patch_{task_id}",
            source_recommendations_path="",
            router_policy_path="",
        ),
        update_policy,
        approval_path,
    )

    if not approval.approved:
        result = RouterApplyResult(
            patch_id=f"patch_{task_id}",
            applied=False,
            status="APPROVAL_REQUIRED",
            reasons=["approval token missing or mismatch"],
        )
        result_path = output_dir / "router_update_apply_result.yml"
        atomic_write_yaml(result_path, {
            "applied": False,
            "reason": "approval_required",
            "patch_id": result.patch_id,
            "status": result.status,
        })
        return result, str(result_path), None

    # Build and apply patch to temp copy
    router_policy = load_router_policy(router_policy_src if router_policy_src.exists() else temp_router)
    from agent_runtime.governance.models import ProviderRoutingRecommendation

    rec = ProviderRoutingRecommendation(
        provider_id=provider_id,
        recommendation=recommendation,
        reason=[f"P2-F closure: {recommendation} based on review verdict"],
    )
    patch = build_router_policy_patch([rec], router_policy, update_policy, output_dir)

    # Create a temp patched copy
    patched_copy = output_dir / "temp_router_policy_patched.yml"
    result_path = output_dir / "router_update_apply_result.yml"

    original_policy = load_router_policy(router_policy_src if router_policy_src.exists() else temp_router)

    try:
        # Save the patch as YAML for apply_router_policy_patch to load
        patch_yaml = output_dir / f"{patch.patch_id}.yml"
        atomic_write_yaml(patch_yaml, {
            "patch_id": patch.patch_id,
            "source_recommendations_path": "",
            "router_policy_path": "",
            "operations": [
                {
                    "operation_id": op.operation_id,
                    "provider_id": op.provider_id,
                    "operation_type": op.operation_type,
                    "target_path": op.target_path,
                    "old_value": op.old_value,
                    "new_value": op.new_value,
                    "reason": op.reason,
                    "source_recommendation": op.source_recommendation,
                    "safety_level": op.safety_level,
                    "requires_approval": op.requires_approval,
                }
                for op in patch.operations
            ],
            "requires_human_approval": patch.requires_human_approval,
            "warnings": patch.warnings,
        })

        patch_result = apply_router_policy_patch(
            router_policy_path=temp_router,
            patch_path=patch_yaml,
            update_policy_path=temp_update,
            output_path=patched_copy,
            approval_dir=approval_path.parent if approval_path.is_file() else approval_path,
        )

        # Create rollback plan
        patched_policy = load_router_policy(patched_copy)
        rollback = create_router_rollback_plan(original_policy, patched_policy, patch, output_dir)
        rollback_path = str(output_dir / "rollback_plan.yml")

        result = RouterApplyResult(
            patch_id=patch.patch_id,
            applied=patch_result.applied,
            applied_to=patch_result.applied_to,
            status=patch_result.status,
            reasons=patch_result.reasons,
            rollback_plan_path=rollback_path,
        )
        atomic_write_yaml(result_path, {
            "applied": result.applied,
            "applied_to": result.applied_to,
            "status": result.status,
            "reasons": result.reasons,
            "rollback_plan_path": result.rollback_plan_path,
        })

        return result, str(result_path), rollback_path

    except Exception as e:
        result = RouterApplyResult(
            patch_id=f"patch_{task_id}",
            applied=False,
            status="VALIDATION_FAILED",
            reasons=[str(e)],
        )
        atomic_write_yaml(result_path, {
            "applied": False,
            "status": result.status,
            "reasons": result.reasons,
        })
        return result, str(result_path), None


# ─── Helpers ───────────────────────────────────────────────────────


def _normalize(status: str) -> str:
    mapping = {
        "PASS": "accepted",
        "PASS_WITH_WARNINGS": "accepted",
        "NEEDS_REVISION": "needs_revision",
        "FAIL": "rejected",
        "BLOCKED": "unsafe",
    }
    return mapping.get(status, status.lower() if status else "needs_revision")


def _extract_scores(verdict_path: Path) -> dict[str, float]:
    if verdict_path.exists():
        data = yaml.safe_load(verdict_path.read_text()) or {}
        return data.get("scores", {})
    return {}


def _suggest_executor(verdict: str) -> str:
    if verdict == "unsafe":
        return "agentlab_internal"
    if verdict == "rejected":
        return "deepseek"
    return "codex"


def _governance_recommendation(verdict: str, scores: dict[str, float]) -> str:
    if verdict in {"unsafe", "rejected"}:
        return "quarantine"
    if verdict == "needs_revision":
        quality = scores.get("overall", 0.0)
        return "watchlist" if quality < 0.5 else "neutral"
    quality = scores.get("overall", 0.0)
    if quality >= 0.8:
        return "prefer"
    return "neutral"
