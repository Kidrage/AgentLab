"""Load and validate S2 domain workflow template configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import DomainWorkflowTemplate, WorkflowPhase


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DOMAIN_TEMPLATE_PATH = ROOT / "config" / "domain_workflow_templates.yml"
DEFAULT_ARTIFACT_TEMPLATE_PATH = ROOT / "config" / "artifact_contract_templates.yml"
DEFAULT_ACCEPTANCE_TEMPLATE_PATH = ROOT / "config" / "acceptance_gate_templates.yml"


class WorkflowTemplateValidationError(ValueError):
    """Clear validation error for malformed S2 workflow templates."""


class WorkflowTemplateLoadError(ValueError):
    """Clear load error for missing or invalid YAML template files."""


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise WorkflowTemplateLoadError(f"Template config does not exist: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise WorkflowTemplateLoadError(f"Template config is not valid YAML: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkflowTemplateLoadError(f"Template config must be a YAML mapping: {path}")
    return data


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = [value]
    items: list[str] = []
    for item in raw_items:
        text = str(item).strip()
        if text:
            items.append(text)
    return items


def _as_str_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _phase_from_mapping(template_id: str, index: int, raw: Any) -> WorkflowPhase:
    if isinstance(raw, str):
        phase_id = raw.strip()
        if not phase_id:
            raise WorkflowTemplateValidationError(f"{template_id}.phase_plan[{index}] phase_id is empty")
        return WorkflowPhase(
            phase_id=phase_id,
            title=phase_id.replace("_", " ").title(),
            goal=f"Complete workflow phase {phase_id}.",
            expected_artifacts=[phase_id],
        )
    if not isinstance(raw, dict):
        raise WorkflowTemplateValidationError(f"{template_id}.phase_plan[{index}] must be a mapping")
    missing = [key for key in ("phase_id", "title", "goal", "expected_artifacts") if not raw.get(key)]
    if missing:
        raise WorkflowTemplateValidationError(
            f"{template_id}.phase_plan[{index}] missing required fields: {', '.join(missing)}"
        )
    return WorkflowPhase(
        phase_id=str(raw["phase_id"]).strip(),
        title=str(raw["title"]).strip(),
        goal=str(raw["goal"]).strip(),
        required_inputs=_as_list(raw.get("required_inputs")),
        expected_artifacts=_as_list(raw.get("expected_artifacts")),
        acceptance_gates=_as_list(raw.get("acceptance_gates")),
        recommended_agents=_as_list(raw.get("recommended_agents")),
        recommended_skills=_as_list(raw.get("recommended_skills")),
        required_capabilities=_as_list(raw.get("required_capabilities")),
        human_decision_point=bool(raw.get("human_decision_point", False)),
        failure_recovery=_as_str_dict(raw.get("failure_recovery")),
    )


def _template_from_mapping(template_key: str, raw: Any) -> DomainWorkflowTemplate:
    if not isinstance(raw, dict):
        raise WorkflowTemplateValidationError(f"Template {template_key} must be a mapping")
    template_id = str(raw.get("template_id") or template_key).strip()
    if not template_id:
        raise WorkflowTemplateValidationError(f"Template {template_key} has blank template_id")
    phases_raw = raw.get("phase_plan")
    if not isinstance(phases_raw, list):
        raise WorkflowTemplateValidationError(f"Template {template_id} phase_plan must be a list")
    phases = [_phase_from_mapping(template_id, index, item) for index, item in enumerate(phases_raw)]
    if len(phases) < 3:
        raise WorkflowTemplateValidationError(f"Template {template_id} must have at least 3 phases")
    for field_name in ("display_name", "description"):
        if not str(raw.get(field_name, "")).strip():
            raise WorkflowTemplateValidationError(f"Template {template_id} missing {field_name}")
    return DomainWorkflowTemplate(
        template_id=template_id,
        display_name=str(raw.get("display_name", "")).strip(),
        description=str(raw.get("description", "")).strip(),
        trigger_task_types=_as_list(raw.get("trigger_task_types") or raw.get("task_types")),
        trigger_signals=_as_list(raw.get("trigger_signals")),
        required_capabilities=_as_list(raw.get("required_capabilities")),
        recommended_agents=_as_list(raw.get("recommended_agents")),
        recommended_skills=_as_list(raw.get("recommended_skills")),
        phase_plan=phases,
        required_artifacts=_as_list(raw.get("required_artifacts")),
        acceptance_gates=_as_list(raw.get("acceptance_gates")),
        risk_defaults=_as_list(raw.get("risk_defaults")),
        failure_recovery=_as_str_dict(raw.get("failure_recovery")),
        human_decision_points=_as_list(raw.get("human_decision_points")),
        route_preferences=dict(raw.get("route_preferences") or {}),
        risk_notes=_as_list(raw.get("risk_notes") or raw.get("notes")),
        raw=dict(raw),
    )


def load_domain_workflow_templates(path: Path = DEFAULT_DOMAIN_TEMPLATE_PATH) -> list[DomainWorkflowTemplate]:
    """Load S2 domain workflow templates deterministically from YAML."""

    data = _load_yaml_mapping(Path(path))
    raw_templates = data.get("templates", data)
    if not isinstance(raw_templates, dict):
        raise WorkflowTemplateValidationError("domain workflow templates must be a mapping under 'templates'")
    templates: list[DomainWorkflowTemplate] = []
    seen: set[str] = set()
    for template_key in raw_templates:
        template = _template_from_mapping(str(template_key), raw_templates[template_key])
        if template.template_id in seen:
            raise WorkflowTemplateValidationError(f"Duplicate domain workflow template_id: {template.template_id}")
        seen.add(template.template_id)
        templates.append(template)
    if "unknown_exploratory" not in seen:
        raise WorkflowTemplateValidationError("unknown_exploratory fallback template is required")
    return templates


def load_artifact_contract_templates(path: Path) -> dict:
    """Load artifact contract template mapping."""

    data = _load_yaml_mapping(Path(path))
    templates = data.get("artifact_contract_templates", data)
    if not isinstance(templates, dict):
        raise WorkflowTemplateValidationError("artifact contract templates must be a mapping")
    return templates


def load_acceptance_gate_templates(path: Path) -> dict:
    """Load acceptance gate template mapping."""

    data = _load_yaml_mapping(Path(path))
    templates = data.get("acceptance_gate_templates", data)
    if not isinstance(templates, dict):
        raise WorkflowTemplateValidationError("acceptance gate templates must be a mapping")
    return templates
