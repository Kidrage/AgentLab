"""Deterministic Mission Contract to domain workflow template matching."""

from __future__ import annotations

from typing import Any

from .models import DomainWorkflowTemplate


UNKNOWN_TEMPLATE_ID = "unknown_exploratory"


def _text(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").strip().lower()


def _contract_domain_values(mission_contract: dict) -> list[str]:
    values: list[str] = []
    for key in ("task_type", "domain"):
        value = _text(mission_contract.get(key))
        if value:
            values.append(value)
    for note in mission_contract.get("notes") or []:
        text = str(note).strip().lower()
        if text.startswith("domain_workflow_template:"):
            values.append(text.split(":", 1)[1].strip())
    return values


def _goal_text(mission_contract: dict) -> str:
    parts = [
        mission_contract.get("user_goal", ""),
        mission_contract.get("intent_summary", ""),
        " ".join(str(item) for item in mission_contract.get("unknowns") or []),
        " ".join(str(item) for item in mission_contract.get("notes") or []),
    ]
    return "\n".join(str(part) for part in parts).lower()


def match_domain_workflow_template(
    mission_contract: dict,
    templates: list[DomainWorkflowTemplate],
) -> DomainWorkflowTemplate:
    """Match a mission contract to the best workflow template with no LLM calls."""

    if not templates:
        raise ValueError("No domain workflow templates loaded")
    by_id = {template.template_id: template for template in templates}
    fallback = by_id.get(UNKNOWN_TEMPLATE_ID) or templates[-1]
    domain_values = _contract_domain_values(mission_contract)
    for value in domain_values:
        if value in by_id:
            return by_id[value]
    for value in domain_values:
        for template in templates:
            if value in {item.lower() for item in template.trigger_task_types}:
                return template
    goal = _goal_text(mission_contract)
    scored: list[tuple[int, str, DomainWorkflowTemplate]] = []
    for template in templates:
        score = sum(1 for signal in template.trigger_signals if signal.lower() and signal.lower() in goal)
        scored.append((score, template.template_id, template))
    scored.sort(key=lambda item: (-item[0], item[1]))
    if scored and scored[0][0] > 0:
        return scored[0][2]
    return fallback
