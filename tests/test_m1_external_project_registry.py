from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from agent_runtime.external_projects import load_external_project_registry
from agent_runtime.external_projects.registry import ExternalProjectRegistry
from agent_runtime.external_projects.models import ExternalProject
from agent_runtime.run_task import app


REQUIRED_PROJECT_IDS = {
    "mineru",
    "markitdown",
    "codebase_memory_mcp",
    "graphify",
    "supervision",
    "mattpocock_skills",
    "ponytail",
    "agent_reach",
    "babyagi",
    "aitoearn",
}


def test_external_project_registry_loads_deterministically() -> None:
    registry = load_external_project_registry()

    first = registry.to_sorted_dicts()
    second = load_external_project_registry().to_sorted_dicts()

    assert {item["project_id"] for item in first} == REQUIRED_PROJECT_IDS
    assert [item["project_id"] for item in first] == sorted(REQUIRED_PROJECT_IDS)
    assert first == second
    assert all(item["default_enabled"] is False for item in first)
    assert all(item["integration_stage"] == "registry_only" for item in first)


def test_duplicate_project_id_fails() -> None:
    project = load_external_project_registry().get("mineru")

    with pytest.raises(ValueError, match="duplicate project_id"):
        ExternalProjectRegistry([project, project])


def test_risky_projects_require_approval_and_no_execution_permissions() -> None:
    registry = load_external_project_registry()

    for project in registry.to_sorted_projects():
        assert project.permissions["shell"] is False
        assert project.permissions["network"] is False
        assert project.risk.requires_approval is True

    assert registry.get("agent_reach").risk.level == "high"
    assert registry.get("babyagi").risk.level == "high"
    assert registry.get("aitoearn").risk.level == "high"


def test_required_capability_mapping_returns_expected_providers() -> None:
    registry = load_external_project_registry()

    assert [item.project_id for item in registry.providers_for_capability("complex_document_ingestion")] == ["mineru"]
    assert [item.project_id for item in registry.providers_for_capability("office_to_markdown")] == ["markitdown"]
    assert [item.project_id for item in registry.providers_for_capability("self_evolving_skill_research_reference")] == ["babyagi"]

    capability_map = registry.capability_map()
    assert capability_map["market_channel_research"] == ["agent_reach"]
    assert capability_map["channel_operation_reference"] == ["aitoearn"]


def test_config_files_parse_and_match_registry() -> None:
    root = Path(__file__).resolve().parents[1]
    registry_data = yaml.safe_load((root / "config/external_project_registry.yml").read_text())
    risk_policy = yaml.safe_load((root / "config/external_project_risk_policy.yml").read_text())
    capability_map = yaml.safe_load((root / "config/external_project_capability_map.yml").read_text())

    project_ids = {item["project_id"] for item in registry_data["external_projects"]}
    mapped_provider_ids = {
        provider
        for value in capability_map["capabilities"].values()
        for provider in value["providers"]
    }

    assert project_ids == REQUIRED_PROJECT_IDS
    assert mapped_provider_ids <= project_ids
    assert risk_policy["default_mode"] == "registry_only"
    assert risk_policy["safety_invariants"]["no_external_code_execution"] is True
    assert "execute_external_code" in risk_policy["blocked_without_explicit_stage"]


def test_invalid_default_enabled_project_is_rejected() -> None:
    project_data = load_external_project_registry().get("mineru").to_dict()
    project_data["default_enabled"] = True

    with pytest.raises(ValueError, match="default_enabled must be false"):
        ExternalProjectRegistry([ExternalProject.from_dict(project_data)])


def test_external_projects_cli_lists_inspects_maps_and_writes_report(tmp_path: Path) -> None:
    runner = CliRunner()

    list_result = runner.invoke(app, ["external-projects", "list"])
    assert list_result.exit_code == 0
    assert "mineru" in list_result.stdout
    assert "babyagi" in list_result.stdout

    inspect_result = runner.invoke(app, ["external-projects", "inspect", "--project", "mineru"])
    assert inspect_result.exit_code == 0
    assert "complex_document_ingestion" in inspect_result.stdout
    assert "default_enabled: false" in inspect_result.stdout

    map_result = runner.invoke(
        app,
        [
            "external-projects",
            "capability-map",
            "--capability",
            "complex_document_ingestion",
        ],
    )
    assert map_result.exit_code == 0
    assert "mineru" in map_result.stdout

    report_result = runner.invoke(
        app,
        ["external-projects", "risk-report", "--out", str(tmp_path)],
    )
    assert report_result.exit_code == 0
    report = yaml.safe_load((tmp_path / "external_project_risk_report.yml").read_text())
    assert report["safety_invariants"]["no_external_code_execution"] is True
    assert report["safety_invariants"]["no_clone"] is True
    assert report["default_enabled_count"] == 0
