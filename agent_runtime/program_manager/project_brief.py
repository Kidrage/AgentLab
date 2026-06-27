from __future__ import annotations

from agent_runtime.program_manager.models import ProjectBrief, to_plain_data
from agent_runtime.program_manager.project_goal import infer_task_type, normalize_capabilities


def build_project_brief_data(project: str, contract: dict) -> dict:
    task_type = infer_task_type(contract)
    artifacts = contract.get("required_artifacts") or []
    if not artifacts and task_type in {"creative_longform", "creative"}:
        artifacts = ["story_bible", "character_bible", "chapter_outline", "continuity_ledger"]
    if not artifacts and task_type == "coding":
        artifacts = ["repo_context", "patch_plan", "tests", "acceptance_report"]
    brief = ProjectBrief(
        project=project,
        task_type=task_type,
        user_goal=str(contract.get("user_goal") or contract.get("goal") or ""),
        intent_summary=str(contract.get("intent_summary") or contract.get("summary") or ""),
        required_capabilities=normalize_capabilities(contract.get("required_capabilities")),
        risk_flags=[str(item) for item in contract.get("risk_flags") or []],
        artifact_targets=[str(item) for item in artifacts],
        long_project_governance=contract.get("long_project_governance") or {},
    )
    return to_plain_data(brief)
