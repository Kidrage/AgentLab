from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.brain.mission_contract import (
    MissionAcceptanceGate,
    MissionArtifactContract,
    MissionAssumption,
    MissionCapabilityRequirement,
    MissionContract,
    MissionHumanApproval,
    MissionRisk,
    MissionTaskType,
    load_mission_contract,
    mission_contract_from_dict,
    mission_contract_to_dict,
    validate_mission_contract,
    write_mission_contract,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = ROOT / "examples" / "mission_contracts"


def _minimal_contract() -> MissionContract:
    return MissionContract(
        mission_id="mission_minimal_001",
        task_type=MissionTaskType.UNKNOWN,
        user_goal="Capture a minimal mission contract.",
    )


def _full_contract() -> MissionContract:
    return MissionContract(
        mission_id="mission_full_001",
        task_type=MissionTaskType.CODING,
        user_goal="Fix a bug and report validation results.",
        intent_summary="Bugfix contract for schema testing.",
        non_goals=["Do not implement unrelated features."],
        hard_constraints=["No external API calls."],
        soft_preferences=["Prefer smallest safe patch."],
        unknowns=["Exact root cause before inspection."],
        assumptions=[
            MissionAssumption(
                id="assumption_001",
                text="Tests reproduce the bug.",
                confidence="medium",
                requires_user_confirmation=False,
            )
        ],
        required_capabilities=[
            MissionCapabilityRequirement(
                capability="file_read",
                reason="Inspect failing code.",
                required=True,
                source="system_required",
            )
        ],
        required_artifacts=[
            MissionArtifactContract(
                artifact_type="patch",
                name="bugfix_patch",
                description="Minimal source patch.",
                required=True,
            )
        ],
        acceptance_gates=[
            MissionAcceptanceGate(
                gate_id="gate_001",
                description="Tests pass.",
                verification_method="test",
                required=True,
            )
        ],
        risks=[
            MissionRisk(
                risk_id="risk_001",
                level="low",
                description="Over-editing could introduce regressions.",
                mitigation="Patch only the failing path.",
            )
        ],
        human_approval=MissionHumanApproval(required=False, reason="Local-only test fixture."),
        recommended_route="RepoScout -> Coder -> Tester",
        notes=["S1-A schema-only fixture."],
    )


def _error_fields(errors: list[dict[str, str]]) -> set[str]:
    return {error["field"] for error in errors}


def test_valid_minimal_mission_contract() -> None:
    contract = _minimal_contract()
    assert validate_mission_contract(contract) == []
    data = mission_contract_to_dict(contract)
    assert data["schema_version"] == "1.0"
    assert data["task_type"] == "unknown"


def test_valid_full_mission_contract() -> None:
    contract = _full_contract()
    assert validate_mission_contract(contract) == []
    data = mission_contract_to_dict(contract)
    assert data["required_capabilities"][0]["capability"] == "file_read"
    assert data["human_approval"]["required"] is False


def test_invalid_empty_user_goal() -> None:
    contract = _minimal_contract()
    contract.user_goal = ""
    assert "user_goal" in _error_fields(validate_mission_contract(contract))


def test_invalid_unknown_task_type() -> None:
    contract = _minimal_contract()
    contract.task_type = "space_mining"
    errors = validate_mission_contract(contract)
    assert "task_type" in _error_fields(errors)
    assert errors[0]["code"] == "unknown_enum"


def test_invalid_capability_missing_reason() -> None:
    contract = _minimal_contract()
    contract.required_capabilities = [MissionCapabilityRequirement(capability="file_read", reason="")]
    assert "required_capabilities[0].reason" in _error_fields(validate_mission_contract(contract))


def test_invalid_artifact_missing_description() -> None:
    contract = _minimal_contract()
    contract.required_artifacts = [MissionArtifactContract(artifact_type="report", name="report", description="")]
    assert "required_artifacts[0].description" in _error_fields(validate_mission_contract(contract))


def test_invalid_acceptance_gate_missing_verification_method() -> None:
    contract = _minimal_contract()
    contract.acceptance_gates = [MissionAcceptanceGate(gate_id="gate_001", description="Review output", verification_method="")]
    assert "acceptance_gates[0].verification_method" in _error_fields(validate_mission_contract(contract))


def test_yaml_roundtrip_is_stable(tmp_path: Path) -> None:
    path = tmp_path / "mission.yml"
    contract = _full_contract()
    write_mission_contract(contract, path)
    first = path.read_text(encoding="utf-8")
    loaded = load_mission_contract(path)
    write_mission_contract(loaded, path)
    second = path.read_text(encoding="utf-8")
    assert first == second
    assert validate_mission_contract(loaded) == []


def test_example_mission_contracts_validate() -> None:
    paths = sorted(EXAMPLE_DIR.glob("*.yml"))
    assert paths, "mission contract examples missing"
    for path in paths:
        contract = load_mission_contract(path)
        assert validate_mission_contract(contract) == [], path.name


def test_human_approval_block_is_supported() -> None:
    contract = _minimal_contract()
    contract.human_approval = MissionHumanApproval(required=True, reason="Needs user approval.")
    data = mission_contract_to_dict(contract)
    assert data["human_approval"] == {"required": True, "reason": "Needs user approval."}
    assert validate_mission_contract(contract) == []


def test_unknowns_and_assumptions_are_supported() -> None:
    contract = mission_contract_from_dict(
        {
            "schema_version": "1.0",
            "mission_id": "mission_unknowns_001",
            "task_type": "research",
            "user_goal": "Research an open question.",
            "unknowns": ["source availability"],
            "assumptions": [
                {
                    "id": "assumption_001",
                    "text": "Sources are available.",
                    "confidence": "low",
                    "requires_user_confirmation": True,
                }
            ],
        }
    )
    assert contract.unknowns == ["source availability"]
    assert contract.assumptions[0].confidence == "low"
    assert validate_mission_contract(contract) == []


def test_multimodal_and_audio_task_types_supported() -> None:
    for task_type in (MissionTaskType.MULTIMODAL, MissionTaskType.AUDIO_MUSIC):
        contract = _minimal_contract()
        contract.task_type = task_type
        assert validate_mission_contract(contract) == []


def test_yaml_mapping_can_be_loaded_from_dict() -> None:
    data = yaml.safe_load((EXAMPLE_DIR / "coding_bugfix.yml").read_text(encoding="utf-8"))
    contract = mission_contract_from_dict(data)
    assert contract.task_type == MissionTaskType.CODING
    assert validate_mission_contract(contract) == []