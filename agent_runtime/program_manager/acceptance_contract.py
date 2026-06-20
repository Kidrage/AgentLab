from __future__ import annotations


def build_acceptance_contract(phase_plan: dict) -> dict:
    plan = phase_plan.get("task_packet") or phase_plan
    return {
        "phase_id": plan.get("phase_id"),
        "required_outputs": plan.get("outputs") or plan.get("required_outputs") or [],
        "required_evidence": plan.get("evidence_required") or [],
        "criteria": plan.get("acceptance_criteria") or [],
        "human_approval_required": "approve_phase_close" in (plan.get("human_decision_points") or []),
    }

