from __future__ import annotations

from pathlib import Path
import os
import re
import subprocess
import yaml

from agent_runtime.frontdesk_intent import (
    compile_frontdesk_intent,
    load_frontdesk_intent_policy,
)


def test_deterministic_status_check_routes_f0() -> None:
    result = compile_frontdesk_intent(
        "Check the current AgentLab status without changing anything.",
        project="AgentLab",
    )

    assert result["schema_version"] == "frontdesk-intent/v2"
    assert result["route_tier"] == "F0"
    assert result["mutation_scope"] == "none"
    assert result["external_effect"] == "none"
    assert result["normalized_request"] == "check the current agentlab status without changing anything."
    assert len(result["request_sha256"]) == 64


def test_scoped_implementation_routes_single_agent_f2() -> None:
    result = compile_frontdesk_intent(
        "Fix the CLI default in one file and run its focused tests.",
        project="AgentLab",
    )

    assert result["route_tier"] == "F2"
    assert result["mutation_scope"] == "project_scoped"
    assert "file_edit" in result["required_capabilities"]


def test_ambiguous_request_never_auto_escalates_to_f4() -> None:
    result = compile_frontdesk_intent(
        "Please improve the project.",
        project="AgentLab",
    )

    assert result["route_tier"] == "F3"
    assert result["confidence"] < 0.8
    assert "project_contract_required_for_f4" in result["approval_requirements"]


def test_explicit_long_running_project_contract_allows_f4() -> None:
    result = compile_frontdesk_intent(
        (
            "Run this long-term multi-stage production project continuously, "
            "with ongoing maintenance and governance."
        ),
        project="Crown_of_Ash",
        project_contract_exists=True,
    )

    assert result["route_tier"] == "F4"
    assert result["task_scope"] == "project_program"


def test_transport_adapter_cannot_change_route_result() -> None:
    request = "Audit this bounded change with planning, execution, and review."

    openclaw = compile_frontdesk_intent(
        request,
        project="AgentLab",
        adapter="openclaw",
    )
    hermes = compile_frontdesk_intent(
        request,
        project="AgentLab",
        adapter="hermes",
    )

    assert openclaw == hermes
    assert openclaw["route_tier"] == "F3"


def test_frontdesk_policy_configuration_controls_intent_vocabulary() -> None:
    root = Path(__file__).resolve().parents[1]
    policy = load_frontdesk_intent_policy(root)
    policy = yaml.safe_load(yaml.safe_dump(policy))
    policy["vocabularies"]["status"] = ["probe-state"]

    configured = compile_frontdesk_intent(
        "probe-state AgentLab",
        project="AgentLab",
        policy=policy,
    )

    assert configured["route_tier"] == "F0"
    assert "config:frontdesk_policy.yml#intent_compiler_v2" in configured["evidence"]


def test_frontdesk_route_cli_is_registered() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [str(root / "agentlab.sh"), "frontdesk", "route", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "NO_COLOR": "1", "COLUMNS": "180"},
    )

    assert result.returncode == 0, result.stderr
    stdout = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", result.stdout)
    assert "--explain" in stdout
    assert "--adapter" in stdout
