from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_runtime.domain_workflows import (
    WorkflowTemplateValidationError,
    load_acceptance_gate_templates,
    load_artifact_contract_templates,
    load_domain_workflow_templates,
    match_domain_workflow_template,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "config" / "domain_workflow_templates.yml"
ARTIFACT_PATH = ROOT / "config" / "artifact_contract_templates.yml"
GATE_PATH = ROOT / "config" / "acceptance_gate_templates.yml"

REQUIRED_TEMPLATE_IDS = {
    "coding_software_engineering",
    "research_investigation",
    "creative_longform",
    "business_strategy",
    "product_design",
    "data_analysis",
    "document_processing",
    "multimodal_vision",
    "audio_music",
    "local_ops_automation",
    "education_tutoring",
    "unknown_exploratory",
}


def test_domain_workflow_templates_load() -> None:
    templates = load_domain_workflow_templates(TEMPLATE_PATH)
    assert REQUIRED_TEMPLATE_IDS <= {template.template_id for template in templates}
    assert len(templates) >= 12
    assert load_artifact_contract_templates(ARTIFACT_PATH)
    assert load_acceptance_gate_templates(GATE_PATH)


def test_domain_workflow_template_ids_unique(tmp_path: Path) -> None:
    duplicate = tmp_path / "domain_workflow_templates.yml"
    duplicate.write_text(
        "templates:\n"
        "  first:\n"
        "    template_id: duplicate\n"
        "    display_name: First\n"
        "    description: First duplicate.\n"
        "    trigger_task_types: [coding]\n"
        "    phase_plan:\n"
        "      - {phase_id: a, title: A, goal: A, expected_artifacts: [a]}\n"
        "      - {phase_id: b, title: B, goal: B, expected_artifacts: [b]}\n"
        "      - {phase_id: c, title: C, goal: C, expected_artifacts: [c]}\n"
        "  second:\n"
        "    template_id: duplicate\n"
        "    display_name: Second\n"
        "    description: Second duplicate.\n"
        "    trigger_task_types: [research]\n"
        "    phase_plan:\n"
        "      - {phase_id: a, title: A, goal: A, expected_artifacts: [a]}\n"
        "      - {phase_id: b, title: B, goal: B, expected_artifacts: [b]}\n"
        "      - {phase_id: c, title: C, goal: C, expected_artifacts: [c]}\n"
        "  unknown_exploratory:\n"
        "    template_id: unknown_exploratory\n"
        "    display_name: Unknown\n"
        "    description: Unknown fallback.\n"
        "    trigger_task_types: [unknown]\n"
        "    phase_plan:\n"
        "      - {phase_id: a, title: A, goal: A, expected_artifacts: [a]}\n"
        "      - {phase_id: b, title: B, goal: B, expected_artifacts: [b]}\n"
        "      - {phase_id: c, title: C, goal: C, expected_artifacts: [c]}\n",
        encoding="utf-8",
    )
    with pytest.raises(WorkflowTemplateValidationError, match="Duplicate"):
        load_domain_workflow_templates(duplicate)


def test_each_template_has_minimum_required_fields() -> None:
    raw = yaml.safe_load(TEMPLATE_PATH.read_text(encoding="utf-8"))
    templates = raw["templates"]
    required = {
        "template_id",
        "display_name",
        "description",
        "trigger_task_types",
        "trigger_signals",
        "required_capabilities",
        "recommended_agents",
        "recommended_skills",
        "phase_plan",
        "failure_recovery",
        "human_decision_points",
        "route_preferences",
        "risk_notes",
    }
    for template_id, template in templates.items():
        assert required <= set(template), template_id
        assert template["template_id"] == template_id
        assert len(template["phase_plan"]) >= 3


def test_each_phase_has_required_fields() -> None:
    templates = load_domain_workflow_templates(TEMPLATE_PATH)
    for template in templates:
        for phase in template.phase_plan:
            assert phase.phase_id
            assert phase.title
            assert phase.goal
            assert phase.expected_artifacts


def test_match_coding_contract_to_coding_template() -> None:
    templates = load_domain_workflow_templates(TEMPLATE_PATH)
    selected = match_domain_workflow_template({"task_type": "coding", "user_goal": "Fix a repo bug and run pytest."}, templates)
    assert selected.template_id == "coding_software_engineering"


def test_match_research_contract_to_research_template() -> None:
    templates = load_domain_workflow_templates(TEMPLATE_PATH)
    selected = match_domain_workflow_template({"task_type": "research", "user_goal": "Research a company with sources."}, templates)
    assert selected.template_id == "research_investigation"


def test_match_creative_contract_to_creative_template() -> None:
    templates = load_domain_workflow_templates(TEMPLATE_PATH)
    selected = match_domain_workflow_template({"task_type": "creative_longform", "user_goal": "Write a story outline."}, templates)
    assert selected.template_id == "creative_longform"


def test_match_unknown_contract_to_unknown_exploratory() -> None:
    templates = load_domain_workflow_templates(TEMPLATE_PATH)
    selected = match_domain_workflow_template({"task_type": "unknown", "user_goal": "Please handle this."}, templates)
    assert selected.template_id == "unknown_exploratory"


def test_domain_workflow_yaml_text_integrity() -> None:
    lines = TEMPLATE_PATH.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("# AgentLab S2")
    assert len(lines) >= 120
    assert max(len(line) for line in lines) <= 1000
