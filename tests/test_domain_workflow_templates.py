from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.brain.domain_signals import classify_task_type
from agent_runtime.brain.domain_workflows import (
    DomainWorkflowCatalog,
    DomainWorkflowTemplate,
    load_domain_workflow_templates,
    select_domain_workflow,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "config" / "domain_workflow_templates.yml"

REQUIRED_TEMPLATE_IDS = {
    "coding_software_engineering",
    "research_investigation",
    "business_strategy",
    "creative_longform",
    "document_processing",
    "data_analysis",
    "audio_music",
    "multimodal_vision",
    "local_ops_automation",
    "education_tutoring",
    "unknown_exploratory",
}

REQUIRED_FIELDS = {
    "task_types",
    "trigger_signals",
    "required_capabilities",
    "phase_plan",
    "required_artifacts",
    "acceptance_gates",
    "risk_defaults",
    "human_approval",
    "notes",
}


def _classified_template(prompt: str) -> DomainWorkflowTemplate:
    classification = classify_task_type(prompt)
    catalog = load_domain_workflow_templates()
    return select_domain_workflow(classification.task_type.value, classification.domain_signals, catalog)


def test_domain_workflow_templates_load() -> None:
    catalog = load_domain_workflow_templates()
    assert isinstance(catalog, DomainWorkflowCatalog)
    assert not catalog.warnings
    assert REQUIRED_TEMPLATE_IDS <= set(catalog.templates)
    assert catalog.templates["unknown_exploratory"].human_approval["required_by_default"] is True


def test_domain_workflow_template_fields_are_complete() -> None:
    raw = yaml.safe_load(TEMPLATE_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    templates = raw.get("templates")
    assert isinstance(templates, dict)
    for template_id, template in templates.items():
        assert template.get("template_id") == template_id
        for field in REQUIRED_FIELDS:
            assert field in template, f"{template_id} missing {field}"
            assert template[field], f"{template_id} has empty {field}"
        assert isinstance(template["human_approval"], dict)
        assert "required_by_default" in template["human_approval"]
        assert "required_when" in template["human_approval"]


def test_select_coding_workflow_for_repo_prompt() -> None:
    selected = _classified_template(
        "Fix a bug in this repo, patch the function, run pytest, and summarize changed files."
    )
    assert selected.template_id in {"coding_software_engineering", "debugging_triage"}
    assert "repo_inspection" in selected.required_capabilities
    assert "test_results.md" in selected.required_artifacts


def test_select_research_workflow_for_company_prompt() -> None:
    selected = _classified_template(
        "Research the latest company market competitors and produce a sourced report."
    )
    assert selected.template_id in {"research_investigation", "business_strategy"}
    assert "web_search" in selected.required_capabilities
    assert "fake_citation_risk" in selected.risk_defaults


def test_select_creative_workflow() -> None:
    selected = _classified_template(
        "Write a novel story outline with characters, tone, audience, scenes, and continuity."
    )
    assert selected.template_id == "creative_longform"
    assert "outline.md" in selected.required_artifacts
    assert "continuity_drift_risk" in selected.risk_defaults


def test_select_audio_workflow() -> None:
    selected = _classified_template(
        "Analyze spatial audio music stems for HRTF, loudness, binaural balance, and mix issues."
    )
    assert selected.template_id == "audio_music"
    assert "audio_analysis" in selected.required_capabilities
    assert "subjective_evaluation_risk" in selected.risk_defaults


def test_select_multimodal_workflow() -> None:
    selected = _classified_template(
        "Review this screenshot image, extract visible text, and label uncertain visual findings."
    )
    assert selected.template_id == "multimodal_vision"
    assert "vision_observations.yml" in selected.required_artifacts
    assert "visual_hallucination_risk" in selected.risk_defaults


def test_select_local_ops_workflow() -> None:
    selected = _classified_template(
        "Delete duplicate local files in this folder after dry-run and rollback planning."
    )
    assert selected.template_id == "local_ops_automation"
    assert selected.human_approval["required_by_default"] is True
    assert "dry_run_report.md" in selected.required_artifacts


def test_unknown_workflow_fallback() -> None:
    selected = _classified_template("Please handle this.")
    assert selected.template_id == "unknown_exploratory"
    assert "human_approval" in selected.required_capabilities
    assert "ambiguous_goal_risk" in selected.risk_defaults


def test_malformed_template_returns_catalog_warning(tmp_path: Path) -> None:
    broken = tmp_path / "domain_workflow_templates.yml"
    broken.write_text(
        "templates:\n"
        "  broken_template:\n"
        "    template_id: broken_template\n"
        "    task_types: coding\n",
        encoding="utf-8",
    )
    catalog = load_domain_workflow_templates(broken)
    assert catalog.warnings
    assert "unknown_exploratory" in catalog.templates
    selected = select_domain_workflow("not_a_real_type", [], catalog)
    assert selected.template_id == "unknown_exploratory"


def test_template_yaml_is_readable_multiline() -> None:
    lines = TEMPLATE_PATH.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 120
    assert max(len(line) for line in lines) <= 1000
    assert lines[0].startswith("# AgentLab S2")
