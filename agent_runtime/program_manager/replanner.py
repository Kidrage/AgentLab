from __future__ import annotations


def recommend_next_action(acceptance_history: dict, roadmap: dict) -> dict:
    accepted = {item.get("phase_id") for item in acceptance_history.get("entries") or [] if item.get("accepted")}
    for milestone in roadmap.get("milestones") or []:
        if milestone.get("phase_id") not in accepted:
            return {
                "next_phase_id": milestone.get("phase_id"),
                "next_action": "prepare_phase_task_packet",
                "reason": "first unaccepted roadmap phase",
            }
    return {"next_phase_id": None, "next_action": "prepare_delivery_package", "reason": "all phases accepted"}
