"""Tests for Project Workflow Templates configuration."""

from pathlib import Path
import yaml

def test_workflow_templates_exist_and_valid():
    config_path = Path(__file__).resolve().parents[1] / "config" / "project_workflow_templates.yml"
    assert config_path.exists(), "project_workflow_templates.yml does not exist"

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert data is not None
    assert "templates" in data
    templates = data["templates"]

    required_templates = [
        "codebase_build_project",
        "longform_text_project",
        "video_generation_project",
        "research_archive_project",
        "document_knowledgebase_project",
        "multimodal_content_project",
        "local_automation_project",
        "unknown_project",
    ]

    for t_name in required_templates:
        assert t_name in templates, f"Template {t_name} is missing"
        template = templates[t_name]
        assert "template_id" in template
        assert "project_type" in template
        assert "phases" in template

        phases = template["phases"]
        assert len(phases) >= 5, f"Template {t_name} has only {len(phases)} phases (minimum 5 required)"

        for i, phase in enumerate(phases):
            assert "title" in phase, f"Phase {i} in {t_name} is missing a title"
            assert "goal" in phase, f"Phase {i} ({phase.get('title', 'unnamed')}) in {t_name} is missing a goal"
