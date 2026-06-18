from __future__ import annotations

import socket
import subprocess
import urllib.request
from pathlib import Path

import yaml

from agent_runtime.domain_workflows import (
    load_acceptance_gate_templates,
    load_artifact_contract_templates,
    load_domain_workflow_templates,
)
from agent_runtime.domain_workflows.planner import build_workflow_plan
from agent_runtime.domain_workflows.renderer import (
    render_workflow_plan_markdown,
    workflow_plan_to_dict,
    write_workflow_plan_yaml,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "config" / "domain_workflow_templates.yml"
ARTIFACT_PATH = ROOT / "config" / "artifact_contract_templates.yml"
GATE_PATH = ROOT / "config" / "acceptance_gate_templates.yml"
EXAMPLES = ROOT / "examples" / "mission_contracts"


def _templates():
    return load_domain_workflow_templates(TEMPLATE_PATH)


def _contract(name: str) -> dict:
    return yaml.safe_load((EXAMPLES / name).read_text(encoding="utf-8"))


def _plan(name: str):
    return build_workflow_plan(
        _contract(name),
        _templates(),
        load_artifact_contract_templates(ARTIFACT_PATH),
        load_acceptance_gate_templates(GATE_PATH),
    )


def test_build_workflow_plan_merges_required_capabilities() -> None:
    plan = _plan("coding_bug.yml")
    assert "code_edit" in plan.required_capabilities
    assert "repo_inspection" in plan.required_capabilities


def test_build_workflow_plan_merges_required_artifacts() -> None:
    plan = _plan("coding_bug.yml")
    assert "patch_plan" in plan.expected_artifacts
    assert "acceptance_report" in plan.expected_artifacts


def test_build_workflow_plan_merges_acceptance_gates() -> None:
    plan = _plan("coding_bug.yml")
    assert "tests_recorded" in plan.acceptance_gates
    assert "rollback_notes_exist" in plan.acceptance_gates


def test_creative_workflow_has_planning_before_drafting() -> None:
    plan = _plan("creative_longform.yml")
    phase_ids = [phase.phase_id for phase in plan.phases]
    assert phase_ids.index("build_structure_outline") < phase_ids.index("draft_content")
    assert phase_ids.index("create_scene_or_section_cards") < phase_ids.index("draft_content")


def test_research_workflow_requires_source_quality_gate() -> None:
    plan = _plan("research_company.yml")
    assert plan.template_id == "research_investigation"
    assert "source_quality_gate" in plan.acceptance_gates
    assert "citation_grounding_gate" in plan.acceptance_gates


def test_coding_workflow_requires_tests_or_audit_gate() -> None:
    plan = _plan("coding_bug.yml")
    gates = set(plan.acceptance_gates)
    assert "relevant_tests_pass_or_limitations_recorded" in gates
    assert "text_integrity_audit_passes" in gates
    assert "rollback_notes_exist" in gates


def test_multimodal_workflow_adds_capability_gap_warning_when_vision_missing() -> None:
    plan = _plan("multimodal_image.yml")
    assert plan.template_id == "multimodal_vision"
    assert any(w.warning_id == "capability_gap" and "image_understanding" in w.message for w in plan.warnings)


def test_unknown_workflow_does_not_execute_and_requests_clarification() -> None:
    plan = _plan("unknown_exploratory.yml")
    assert plan.template_id == "unknown_exploratory"
    assert "no_execution_without_clarification" in plan.acceptance_gates
    assert "clarify_intent_before_execution" in plan.human_decision_points


def test_write_workflow_plan_yaml_roundtrip(tmp_path: Path) -> None:
    plan = _plan("coding_bug.yml")
    output = tmp_path / "workflow_plan.yml"
    write_workflow_plan_yaml(plan, output)
    loaded = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert loaded == workflow_plan_to_dict(plan)
    assert loaded["template_id"] == "coding_software_engineering"


def test_render_workflow_plan_markdown_contains_phases() -> None:
    markdown = render_workflow_plan_markdown(_plan("coding_bug.yml"))
    assert "# Workflow Plan" in markdown
    assert "## Phases" in markdown
    assert "Compile mission" in markdown


def test_workflow_planner_does_not_call_network(monkeypatch) -> None:
    def blocked(*args, **kwargs):  # pragma: no cover - should never run
        raise AssertionError("workflow planner must not call network")

    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    plan = _plan("research_company.yml")
    assert plan.template_id == "research_investigation"


def test_workflow_planner_does_not_execute_external_tools(monkeypatch) -> None:
    def blocked(*args, **kwargs):  # pragma: no cover - should never run
        raise AssertionError("workflow planner must not execute external tools")

    monkeypatch.setattr(subprocess, "run", blocked)
    monkeypatch.setattr(subprocess, "Popen", blocked)
    plan = _plan("coding_bug.yml")
    assert plan.template_id == "coding_software_engineering"


def test_s2_does_not_require_heavy_dependencies() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    forbidden = ["playwright", "selenium", "opencv", "torch", "tensorflow", "beautifulsoup4"]
    assert not any(name in requirements for name in forbidden)
