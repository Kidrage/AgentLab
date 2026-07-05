"""Inject selected active skills into workflow plans."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from atomic_io import atomic_write_yaml
from skill_retriever import load_skill_injection_policy, match_active_skills
from skill_usage import record_skill_usage


def _existing_skill_approval_cards(run_dir: Path) -> set[str]:
    from atomic_io import safe_read_yaml

    decision_dir = run_dir / "decision_cards"
    if not decision_dir.exists():
        return set()
    skill_ids: set[str] = set()
    for path in sorted(decision_dir.glob("*.yml")):
        card = safe_read_yaml(path, default={}) or {}
        if not isinstance(card, dict):
            continue
        if card.get("type") != "SKILL_INJECTION_APPROVAL":
            continue
        if card.get("status") not in {"pending", "pending_user_approval", "waiting_for_approval"}:
            continue
        skill_id = card.get("skill", {}).get("skill_id") or card.get("payload", {}).get("skill_id")
        if skill_id:
            skill_ids.add(str(skill_id))
    return skill_ids


def _create_high_risk_skill_approval_cards(
    agentlab_root: Path,
    run_dir: Path,
    *,
    project: str,
    task_id: str,
    rejected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    high_risk = [
        item for item in rejected
        if item.get("approval_type") == "SKILL_INJECTION_APPROVAL"
        or (
            str(item.get("risk_level", "")).lower() == "high"
            and "requires approval" in str(item.get("reason", "")).lower()
        )
    ]
    if not high_risk:
        return []

    from atomic_io import atomic_write_yaml
    from feedback_manager import create_decision_card
    from task_events import append_task_event

    existing = _existing_skill_approval_cards(run_dir)
    created: list[dict[str, Any]] = []
    for skill in high_risk:
        skill_id = str(skill.get("skill_id", "")).strip()
        if not skill_id or skill_id in existing:
            continue
        skill_name = skill.get("name") or skill_id
        card, path = create_decision_card(
            run_dir,
            task_id=task_id,
            card_type="SKILL_INJECTION_APPROVAL",
            title="High-risk skill requires approval",
            reason=f"Skill '{skill_name}' requires user approval before injection.",
            stage="skill_injection",
            options=[
                {"id": "approve_inject", "label": "Approve injection", "risk": "medium"},
                {"id": "reject_inject", "label": "Reject injection", "risk": "low"},
            ],
            recommended_action="approve_inject",
            risk="high",
        )
        card["skill"] = {
            "skill_id": skill_id,
            "name": skill_name,
            "risk_level": skill.get("risk_level", "high"),
            "reason": skill.get("reason", ""),
            "skill_path": skill.get("skill_path"),
        }
        atomic_write_yaml(path, card)
        append_task_event(
            run_dir,
            "SKILL_APPROVAL_REQUIRED",
            stage="skill_injection",
            status="WAITING_FOR_APPROVAL",
            severity="ACTION_REQUIRED",
            message=f"High-risk skill '{skill_name}' requires approval before injection.",
            payload={
                "decision_id": card.get("id"),
                "decision_card": str(path),
                "skill_id": skill_id,
                "skill_name": skill_name,
                "risk_level": skill.get("risk_level", "high"),
            },
        )
        try:
            from webhook_dispatcher import dispatch_event

            dispatch_event(
                agentlab_root,
                event="ACTION_REQUIRED",
                project=project,
                task_id=task_id,
                stage="skill_injection",
                severity="ACTION_REQUIRED",
                summary=f"High-risk skill '{skill_name}' requires approval before injection.",
                reason=skill.get("reason", ""),
                decision_card=card,
            )
        except Exception as exc:
            try:
                from webhook_dispatcher import record_webhook_failure

                record_webhook_failure(
                    agentlab_root,
                    event="ACTION_REQUIRED",
                    project=project,
                    task_id=task_id,
                    error=str(exc),
                    context={"skill_id": skill_id, "decision_id": card.get("id")},
                )
            except Exception:
                pass
        existing.add(skill_id)
        created.append(card)
    return created


def build_skill_plan(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    run_dir: Path,
    task_text: str,
    policy: dict[str, Any] | None = None,
    injected_agents: list[str] | None = None,
    record_usage: bool = True,
) -> dict[str, Any]:
    policy = policy or load_skill_injection_policy(agentlab_root)
    matches = match_active_skills(agentlab_root, task_text=task_text, policy=policy)
    selected = matches.get("selected", [])
    rejected = matches.get("rejected", [])
    if injected_agents:
        for item in selected:
            item["injected_into"] = list(injected_agents)
    approval_cards = _create_high_risk_skill_approval_cards(
        agentlab_root,
        run_dir,
        project=project,
        task_id=task_id,
        rejected=rejected,
    )
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
        "approval_cards": [
            {
                "id": card.get("id"),
                "type": card.get("type"),
                "status": card.get("status"),
                "skill_id": card.get("skill", {}).get("skill_id"),
            }
            for card in approval_cards
        ],
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
    injected_agents = _route_skill_injection_agents(data)
    skills = build_skill_plan(
        agentlab_root,
        project=project,
        task_id=task_id,
        run_dir=run_dir,
        task_text=task_text,
        injected_agents=injected_agents,
        record_usage=record_usage,
    )
    data["skills"] = skills
    atomic_write_yaml(workflow_plan_path, data)
    return skills


def _route_skill_injection_agents(workflow_plan: dict[str, Any]) -> list[str] | None:
    route = workflow_plan.get("route", {})
    agents = route.get("agents", []) if isinstance(route, dict) else []
    if not isinstance(agents, list):
        return None
    creative_agents = [agent for agent in ("Writer", "Reviewer", "Scribe") if agent in agents]
    return creative_agents or None
