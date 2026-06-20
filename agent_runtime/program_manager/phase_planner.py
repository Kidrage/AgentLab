from __future__ import annotations

from agent_runtime.program_manager.models import PhasePlan, to_plain_data


def build_phase_plan(project_brief: dict, roadmap: dict, phase_id: str | None = None) -> dict:
    milestones = roadmap.get("milestones") or []
    selected = next((item for item in milestones if item.get("phase_id") == phase_id), None)
    if selected is None and milestones:
        selected = milestones[0]
    selected = selected or {"phase_id": phase_id or "phase_1", "goal": "Plan the next safe phase"}
    task_type = str(project_brief.get("task_type") or "unknown")
    
    outputs = selected.get("expected_artifacts") or _outputs_for_task_type(task_type, str(selected.get("phase_id")))
    acceptance_criteria = selected.get("acceptance_gates") or [
        "all_required_outputs_have_evidence",
        "phase_evidence_ledger_written",
        "no_policy_bypass_or_external_auto_execution",
    ]
    
    phase = PhasePlan(
        phase_id=str(selected.get("phase_id")),
        goal=str(selected.get("goal")),
        scope=selected.get("scope") or ["planning", "artifact_generation", "evidence_review"],
        inputs=selected.get("inputs") or ["project_brief.yml", "roadmap.yml", "milestone_graph.yml"],
        outputs=outputs,
        acceptance_criteria=acceptance_criteria,
        required_capabilities=selected.get("required_capabilities") or [str(item) for item in project_brief.get("required_capabilities") or []],
        recommended_skills=selected.get("recommended_skills") or [f"{task_type}_planner", "evidence_reviewer"],
        risk_flags=selected.get("risk_flags") or [str(item) for item in project_brief.get("risk_flags") or []],
        human_decision_points=selected.get("human_decision_points") or ["approve_phase_close", "request_replanning"],
        evidence_required=selected.get("evidence_required") or [f"{item}.yml" for item in outputs],
    )
    data = to_plain_data(phase)
    data["project"] = project_brief.get("project")
    return data


def _outputs_for_task_type(task_type: str, phase_id: str) -> list[str]:
    if task_type in {"creative_longform", "creative"}:
        if "foundation" in phase_id:
            return ["story_constitution", "world_bible", "character_bible"]
        return ["chapter_outline", "scene_cards", "continuity_ledger"]
    if task_type == "coding":
        if "repo_context" in phase_id:
            return ["repo_context", "risk_map", "patch_plan"]
        return ["task_packet", "test_evidence", "acceptance_report"]
    return ["artifact_plan", "evidence_ledger", "acceptance_report"]
