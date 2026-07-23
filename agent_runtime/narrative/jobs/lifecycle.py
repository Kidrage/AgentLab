"""Narrative-specific state transitions kept outside the queue controller."""

from __future__ import annotations

from dataclasses import dataclass

from agent_runtime.narrative.audit.gate import SealDecision


MAX_AUTOMATIC_REWRITES = 2


@dataclass(frozen=True)
class NarrativeTransition:
    status: str
    schedule_rewrite: bool = False
    seal_candidate: bool = False
    automatic_rewrite_exhausted: bool = False
    reason: str | None = None


def next_after_heavy_audit(
    *,
    job_kind: str,
    decision: SealDecision,
    automatic_rewrite_count: int,
) -> NarrativeTransition:
    """Apply audit semantics without conflating findings with execution failure."""
    if decision.status == "blocked" and not decision.requires_revision:
        return NarrativeTransition(
            "blocked",
            reason=",".join(decision.blocking_reasons) or "heavy_audit_evidence_invalid",
        )

    if job_kind == "narrative_audit":
        if decision.requires_revision:
            return NarrativeTransition("completed_with_findings")
        if decision.allow_seal:
            return NarrativeTransition("completed_clean")
        return NarrativeTransition("blocked", reason="invalid_audit_closure_decision")

    if decision.allow_seal:
        return NarrativeTransition("batch_sealed", seal_candidate=True)
    if decision.requires_revision:
        if automatic_rewrite_count >= MAX_AUTOMATIC_REWRITES:
            return NarrativeTransition(
                "decision_required",
                automatic_rewrite_exhausted=True,
                reason="insufficient_revision_uplift",
            )
        return NarrativeTransition("rewrite_required", schedule_rewrite=True)
    return NarrativeTransition("blocked", reason="invalid_generation_audit_decision")


def record_audit_batch_result(
    state: dict,
    *,
    decision: SealDecision,
    findings: list[dict],
    now: str,
) -> None:
    """Advance an audit-only job across all planned batches without rewriting."""
    if decision.status == "blocked" and not decision.requires_revision:
        state["status"] = "blocked"
        state["last_error"] = ",".join(decision.blocking_reasons)
        return
    has_findings = bool(decision.requires_revision or findings)
    state["audit_has_findings"] = bool(state.get("audit_has_findings")) or has_findings
    state.setdefault("findings", []).extend(findings)
    batch = dict(state["current_batch"])
    batch.update(
        {
            "status": "completed_with_findings" if has_findings else "completed_clean",
            "audited_at": now,
            "finding_count": len(findings),
        }
    )
    state.setdefault("audited_batches", []).append(batch)
    config = state["config"]
    if int(batch["end"]) >= int(config["end_chapter"]):
        state["status"] = (
            "completed_with_findings" if state["audit_has_findings"] else "completed_clean"
        )
        return
    start = int(batch["end"]) + 1
    state["current_batch"] = {
        "number": int(batch["number"]) + 1,
        "start": start,
        "end": min(int(config["end_chapter"]), start + int(config["batch_size"]) - 1),
    }
    state["status"] = "awaiting_heavy_audit"
