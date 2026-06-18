"""Build deterministic S2 WorkflowPlan objects from Mission Contract mappings."""

from __future__ import annotations

from typing import Any

from agent_runtime.brain.assumption_builder import SUPPORTED_CAPABILITIES

from .matcher import match_domain_workflow_template
from .models import (
    DomainWorkflowTemplate,
    WorkflowPhase,
    WorkflowPlan,
    WorkflowPlanDecisionPoint,
    WorkflowPlanWarning,
)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _capability_names(mission_contract: dict) -> list[str]:
    names: list[str] = []
    for item in mission_contract.get("required_capabilities") or []:
        if isinstance(item, dict):
            names.append(str(item.get("capability", "")))
        else:
            names.append(str(item))
    return _dedupe(names)


def _artifact_names(mission_contract: dict) -> list[str]:
    names: list[str] = []
    for item in mission_contract.get("required_artifacts") or []:
        if isinstance(item, dict):
            names.append(str(item.get("name", "")))
        else:
            names.append(str(item))
    return _dedupe(names)


def _gate_names(mission_contract: dict) -> list[str]:
    names: list[str] = []
    for item in mission_contract.get("acceptance_gates") or []:
        if isinstance(item, dict):
            names.append(str(item.get("gate_id") or item.get("description", "")))
        else:
            names.append(str(item))
    return _dedupe(names)


def _phase_artifacts(phases: list[WorkflowPhase]) -> list[str]:
    values: list[str] = []
    for phase in phases:
        values.extend(phase.expected_artifacts)
    return _dedupe(values)


def _phase_gates(phases: list[WorkflowPhase]) -> list[str]:
    values: list[str] = []
    for phase in phases:
        values.extend(phase.acceptance_gates)
    return _dedupe(values)


def _warning(warning_id: str, message: str, level: str = "warning", source: str = "workflow_planner") -> WorkflowPlanWarning:
    return WorkflowPlanWarning(warning_id=warning_id, level=level, message=message, source=source)


def _decision(decision_id: str, title: str, reason: str, phase_id: str | None = None) -> WorkflowPlanDecisionPoint:
    return WorkflowPlanDecisionPoint(decision_id=decision_id, title=title, reason=reason, phase_id=phase_id)


def _mission_human_approval_required(mission_contract: dict) -> bool:
    approval = mission_contract.get("human_approval") or {}
    if isinstance(approval, dict):
        return bool(approval.get("required", False))
    return False


def _domain(mission_contract: dict, template: DomainWorkflowTemplate) -> str:
    domain = mission_contract.get("domain") or mission_contract.get("task_type") or template.template_id
    return str(getattr(domain, "value", domain))


def _source_path(mission_contract: dict) -> str | None:
    value = mission_contract.get("source_mission_contract_path") or mission_contract.get("_source_path")
    return str(value) if value else None


def build_workflow_plan(
    mission_contract: dict,
    templates: list[DomainWorkflowTemplate],
    artifact_templates: dict | None = None,
    acceptance_gate_templates: dict | None = None,
) -> WorkflowPlan:
    """Transform a mission contract mapping into a domain-aware workflow plan."""

    template = match_domain_workflow_template(mission_contract, templates)
    phases = list(template.phase_plan)
    mission_capabilities = _capability_names(mission_contract)
    required_capabilities = _dedupe(mission_capabilities + template.required_capabilities)
    expected_artifacts = _dedupe(_artifact_names(mission_contract) + template.required_artifacts + _phase_artifacts(phases))
    acceptance_gates = _dedupe(_gate_names(mission_contract) + template.acceptance_gates + _phase_gates(phases))
    warnings: list[WorkflowPlanWarning] = []
    decision_points: list[WorkflowPlanDecisionPoint] = []

    for unknown in mission_contract.get("unknowns") or []:
        warnings.append(_warning("mission_unknown", f"Mission unknown preserved: {unknown}", "info", "mission_contract"))
    for assumption in mission_contract.get("assumptions") or []:
        if isinstance(assumption, dict) and assumption.get("requires_user_confirmation"):
            text = assumption.get("text", "assumption requires confirmation")
            warnings.append(_warning("assumption_requires_confirmation", str(text), "info", "mission_contract"))
            decision_points.append(_decision("confirm_assumption", "Confirm mission assumption", str(text)))

    gaps = [capability for capability in required_capabilities if capability not in SUPPORTED_CAPABILITIES]
    for gap in gaps:
        warnings.append(_warning("capability_gap", f"Required capability is not available locally: {gap}", "warning"))
    if gaps:
        decision_points.append(
            _decision(
                "capability_gap_review",
                "Review capability gaps before execution",
                "Unavailable capabilities: " + ", ".join(sorted(set(gaps))),
            )
        )

    human_decisions = list(template.human_decision_points)
    for phase in phases:
        if phase.human_decision_point:
            human_decisions.append(f"phase:{phase.phase_id}")
            decision_points.append(
                _decision(
                    f"phase_{phase.phase_id}",
                    f"Human decision for {phase.title}",
                    "Template marks this phase as a human decision point.",
                    phase.phase_id,
                )
            )
    if _mission_human_approval_required(mission_contract):
        human_decisions.append("mission_contract_human_approval")
        decision_points.append(
            _decision(
                "mission_contract_human_approval",
                "Mission contract requires human approval",
                str((mission_contract.get("human_approval") or {}).get("reason", "approval required")),
            )
        )

    template_id = template.template_id
    if template_id == "creative_longform":
        phase_ids = [phase.phase_id for phase in phases]
        if "draft_content" in phase_ids:
            draft_index = phase_ids.index("draft_content")
            planning_ids = {"define_genre_and_audience", "build_structure_outline", "create_scene_or_section_cards"}
            if not all(pid in phase_ids[:draft_index] for pid in planning_ids):
                warnings.append(_warning("creative_planning_order", "Creative drafting must follow planning phases.", "error"))
    if template_id == "research_investigation":
        acceptance_gates = _dedupe(acceptance_gates + ["source_quality_gate", "citation_grounding_gate", "no_fake_citations"])
    if template_id == "coding_software_engineering":
        acceptance_gates = _dedupe(acceptance_gates + ["relevant_tests_pass_or_limitations_recorded", "text_integrity_audit_passes", "rollback_notes_exist"])
    if template_id == "unknown_exploratory":
        acceptance_gates = _dedupe(acceptance_gates + ["no_execution_without_clarification"])
        warnings.append(_warning("unknown_no_execution", "Unknown workflow is exploratory and must not execute.", "warning"))
        human_decisions.append("clarify_intent_before_execution")

    return WorkflowPlan(
        task_id=str(mission_contract.get("mission_id") or mission_contract.get("task_id") or "") or None,
        template_id=template.template_id,
        domain=_domain(mission_contract, template),
        source_mission_contract_path=_source_path(mission_contract),
        phases=phases,
        required_capabilities=required_capabilities,
        recommended_agents=_dedupe(template.recommended_agents),
        recommended_skills=_dedupe(template.recommended_skills),
        expected_artifacts=expected_artifacts,
        acceptance_gates=acceptance_gates,
        human_decision_points=_dedupe(human_decisions),
        route_preferences=dict(template.route_preferences),
        warnings=warnings,
        decision_points=decision_points,
    )
