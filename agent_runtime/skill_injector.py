"""Inject selected active skills into workflow plans."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from atomic_io import atomic_write_yaml
from skill_retriever import load_skill_injection_policy, match_active_skills
from skill_usage import record_skill_usage


def build_skill_plan(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    run_dir: Path,
    task_text: str,
    policy: dict[str, Any] | None = None,
    record_usage: bool = True,
) -> dict[str, Any]:
    policy = policy or load_skill_injection_policy(agentlab_root)
    matches = match_active_skills(agentlab_root, task_text=task_text, policy=policy)
    selected = matches.get("selected", [])
    rejected = matches.get("rejected", [])
    usage_paths = {}
    if record_usage and policy.get("usage", {}).get("write_task_usage", True):
        usage_paths = record_skill_usage(
            agentlab_root,
            run_dir,
            project=project,
            task_id=task_id,
            selected=selected,
            rejected=rejected,
        )
    return {
        "selected": selected,
        "rejected": rejected,
        "usage": usage_paths,
        "policy": {
            "source": "config/skill_injection_policy.yml",
            "max_skills_per_task": policy.get("retrieval", {}).get("max_skills_per_task", 3),
            "high_risk_requires_approval": policy.get("retrieval", {}).get("high_risk_requires_approval", True),
        },
    }


def inject_skills_into_workflow_plan(
    agentlab_root: Path,
    workflow_plan_path: Path,
    *,
    project: str,
    task_id: str,
    task_text: str,
    record_usage: bool = True,
) -> dict[str, Any]:
    data = yaml.safe_load(workflow_plan_path.read_text(encoding="utf-8")) if workflow_plan_path.exists() else {}
    if not isinstance(data, dict):
        data = {}
    run_dir = workflow_plan_path.parent
    skills = build_skill_plan(
        agentlab_root,
        project=project,
        task_id=task_id,
        run_dir=run_dir,
        task_text=task_text,
        record_usage=record_usage,
    )
    data["skills"] = skills
    atomic_write_yaml(workflow_plan_path, data)
    return skills
