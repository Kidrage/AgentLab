"""Render S2 WorkflowPlan objects to dictionaries, YAML, and Markdown."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from .models import WorkflowPlan


def workflow_plan_to_dict(plan: WorkflowPlan) -> dict[str, Any]:
    """Convert a WorkflowPlan dataclass into deterministic plain data."""

    data = asdict(plan)
    ordered_keys = [
        "task_id",
        "template_id",
        "domain",
        "source_mission_contract_path",
        "phases",
        "required_capabilities",
        "recommended_agents",
        "recommended_skills",
        "expected_artifacts",
        "acceptance_gates",
        "human_decision_points",
        "route_preferences",
        "warnings",
        "decision_points",
    ]
    return {key: data.get(key) for key in ordered_keys}


def write_workflow_plan_yaml(plan: WorkflowPlan, path: Path) -> None:
    """Write a WorkflowPlan to YAML without executing the plan."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(workflow_plan_to_dict(plan), sort_keys=False, allow_unicode=True), encoding="utf-8")


def _bullet(items: list[str]) -> str:
    if not items:
        return "- None\n"
    return "".join(f"- {item}\n" for item in items)


def render_workflow_plan_markdown(plan: WorkflowPlan) -> str:
    """Render a readable Markdown report for a WorkflowPlan."""

    lines: list[str] = [
        "# Workflow Plan",
        "",
        "## Template",
        f"- `{plan.template_id}`",
        "",
        "## Domain",
        f"- `{plan.domain}`",
        "",
        "## Required Capabilities",
        _bullet(plan.required_capabilities).rstrip(),
        "",
        "## Recommended Agents",
        _bullet(plan.recommended_agents).rstrip(),
        "",
        "## Recommended Skills",
        _bullet(plan.recommended_skills).rstrip(),
        "",
        "## Phases",
    ]
    for index, phase in enumerate(plan.phases, start=1):
        lines.extend(
            [
                f"### {index}. {phase.title}",
                f"- Phase ID: `{phase.phase_id}`",
                f"- Goal: {phase.goal}",
                f"- Human decision point: {phase.human_decision_point}",
                "- Expected artifacts:",
                _bullet(phase.expected_artifacts).rstrip(),
                "- Acceptance gates:",
                _bullet(phase.acceptance_gates).rstrip(),
                "",
            ]
        )
    lines.extend(
        [
            "## Expected Artifacts",
            _bullet(plan.expected_artifacts).rstrip(),
            "",
            "## Acceptance Gates",
            _bullet(plan.acceptance_gates).rstrip(),
            "",
            "## Human Decision Points",
            _bullet(plan.human_decision_points).rstrip(),
            "",
            "## Warnings",
        ]
    )
    if plan.warnings:
        for warning in plan.warnings:
            lines.append(f"- `{warning.warning_id}` ({warning.level}): {warning.message}")
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)
