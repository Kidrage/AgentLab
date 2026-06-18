from __future__ import annotations

import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_runtime.domain_workflows import (  # noqa: E402
    load_acceptance_gate_templates,
    load_artifact_contract_templates,
    load_domain_workflow_templates,
)
from agent_runtime.domain_workflows.planner import build_workflow_plan  # noqa: E402
from agent_runtime.domain_workflows.renderer import workflow_plan_to_dict, write_workflow_plan_yaml  # noqa: E402
from agent_runtime.skills.package_parser import parse_skill_package  # noqa: E402
from agent_runtime.skills.skill_search_plan import build_skill_search_plan, write_skill_search_plan  # noqa: E402
from agent_runtime.skills.source_registry import load_skill_source_registry, validate_skill_source_registry  # noqa: E402


EXAMPLES = ROOT / "examples" / "mission_contracts"


def _contract(name: str) -> dict:
    return yaml.safe_load((EXAMPLES / name).read_text(encoding="utf-8"))


def _workflow(contract: dict) -> dict:
    plan = build_workflow_plan(
        contract,
        load_domain_workflow_templates(ROOT / "config" / "domain_workflow_templates.yml"),
        load_artifact_contract_templates(ROOT / "config" / "artifact_contract_templates.yml"),
        load_acceptance_gate_templates(ROOT / "config" / "acceptance_gate_templates.yml"),
    )
    return workflow_plan_to_dict(plan)


def test_skill_search_plan_from_mission_and_workflow() -> None:
    contract = _contract("coding_bug.yml")
    workflow = _workflow(contract)

    plan = build_skill_search_plan(contract, workflow)

    assert "code_edit" in plan["required_capabilities"]
    assert "repo_inspection" in plan["required_capabilities"]
    assert plan["approval_required"] is True
    assert plan["risk_policy"]["auto_import"] is False
    assert plan["risk_policy"]["auto_promote"] is False
    assert plan["risk_policy"]["never_execute_external_code"] is True
    assert any(source["source_id"] == "github_raw_allowlisted" and source["enabled"] is False for source in plan["candidate_sources"])
    assert "coding software engineering" in plan["search_terms"]


def test_skill_search_plan_does_not_call_network_or_tools(monkeypatch) -> None:
    def blocked(*args, **kwargs):  # pragma: no cover - should never run
        raise AssertionError("S3 skill search plan must not call network or tools")

    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(subprocess, "run", blocked)
    monkeypatch.setattr(subprocess, "Popen", blocked)

    plan = build_skill_search_plan(_contract("research_company.yml"), _workflow(_contract("research_company.yml")))

    assert "web_search" in plan["required_capabilities"]
    assert plan["risk_policy"]["allow_network"] is False


def test_skill_source_registry_safe_defaults() -> None:
    registry = load_skill_source_registry(ROOT / "config" / "skill_source_registry.yml")

    assert validate_skill_source_registry(registry) == []
    assert registry["network_enabled"] is False
    assert registry["auto_install"] is False
    assert registry["require_human_review"] is True


def test_parse_local_skill_fixture_metadata_only() -> None:
    parsed = parse_skill_package(ROOT / "tests" / "fixtures" / "external_skills" / "skill-creator")

    assert parsed["skill_id"] == "skill-creator"
    assert parsed["display_name"] == "skill-creator"
    assert parsed["dispatchable"] is False
    assert parsed["permissions"]["network"] is False
    assert "permissions must be declared" in parsed["validation_errors"]
    assert "risk_level must be declared" in parsed["validation_errors"]
    assert "source type is unknown" in parsed["validation_errors"]
    assert "source_code" not in parsed


def test_skill_search_plan_cli(tmp_path: Path) -> None:
    contract_path = EXAMPLES / "coding_bug.yml"
    workflow_plan = build_workflow_plan(
        _contract("coding_bug.yml"),
        load_domain_workflow_templates(ROOT / "config" / "domain_workflow_templates.yml"),
        load_artifact_contract_templates(ROOT / "config" / "artifact_contract_templates.yml"),
        load_acceptance_gate_templates(ROOT / "config" / "acceptance_gate_templates.yml"),
    )
    workflow_path = tmp_path / "workflow_plan.yml"
    write_workflow_plan_yaml(workflow_plan, workflow_path)

    completed = subprocess.run(
        [
            str(ROOT / "agentlab.sh"),
            "skill-search-plan",
            "--mission-contract",
            str(contract_path),
            "--workflow-plan",
            str(workflow_path),
            "--out",
            str(tmp_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    output = tmp_path / "skill_search_plan.yml"
    assert output.exists()
    data = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert data["approval_required"] is True
    assert "code_edit" in data["required_capabilities"]
