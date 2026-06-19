from __future__ import annotations


def build_roadmap(brief: dict) -> dict:
    task_type = str(brief.get("task_type") or "unknown")
    if task_type in {"creative_longform", "creative"}:
        phases = [
            ("phase_1_foundation", "Create story constitution and world/character bibles"),
            ("phase_2_outline", "Create chapter outline and scene cards"),
            ("phase_3_revision_loop", "Draft, review continuity, and package delivery"),
        ]
    elif task_type == "coding":
        phases = [
            ("phase_1_repo_context", "Map repository context and risks"),
            ("phase_2_patch_packet", "Create patch task packet and execute safely"),
            ("phase_3_acceptance", "Review evidence, tests, and delivery package"),
        ]
    else:
        phases = [
            ("phase_1_clarify", "Clarify goal, evidence needs, and constraints"),
            ("phase_2_plan", "Plan artifacts and controlled execution"),
            ("phase_3_acceptance", "Review evidence and package deliverables"),
        ]
    return {
        "project": brief.get("project"),
        "task_type": task_type,
        "milestones": [
            {"milestone_id": f"m{i + 1}", "phase_id": phase_id, "goal": goal, "status": "planned"}
            for i, (phase_id, goal) in enumerate(phases)
        ],
        "no_direct_execution": True,
        "acceptance_required_before_next_phase": True,
    }
