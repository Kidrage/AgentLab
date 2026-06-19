from __future__ import annotations


def build_acceptance_contract(phase_plan: dict) -> dict:
    return {
        "phase_id": phase_plan.get("phase_id"),
        "required_outputs": phase_plan.get("outputs") or [],
        "required_evidence": phase_plan.get("evidence_required") or [],
        "criteria": phase_plan.get("acceptance_criteria") or [],
        "human_approval_required": "approve_phase_close" in (phase_plan.get("human_decision_points") or []),
    }
