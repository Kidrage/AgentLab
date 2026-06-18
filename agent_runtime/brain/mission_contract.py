"""Mission Contract schema foundation for AgentLab S1-A.

This module intentionally defines only the stable data contract and validation
helpers. It does not classify domains, build artifacts, compile tasks, or wire
mission contracts into the runtime lifecycle.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


SCHEMA_VERSION = "1.0"


class _StringEnum(str, Enum):
    """Enum base that serializes cleanly as a string."""

    def __str__(self) -> str:
        return self.value


class MissionTaskType(_StringEnum):
    CODING = "coding"
    DEBUGGING = "debugging"
    RESEARCH = "research"
    BUSINESS = "business"
    CREATIVE_LONGFORM = "creative_longform"
    DOCUMENT_PROCESSING = "document_processing"
    DATA_ANALYSIS = "data_analysis"
    AUDIO_MUSIC = "audio_music"
    MULTIMODAL = "multimodal"
    LOCAL_OPS = "local_ops"
    EDUCATION = "education"
    UNKNOWN = "unknown"


class MissionPriority(_StringEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MissionConstraint(_StringEnum):
    HARD = "hard"
    SOFT = "soft"


@dataclass
class MissionAssumption:
    id: str = ""
    text: str = ""
    confidence: str = "low"
    requires_user_confirmation: bool = True


@dataclass
class MissionCapabilityRequirement:
    capability: str = ""
    reason: str = ""
    required: bool = True
    source: str = "inferred"


@dataclass
class MissionArtifactContract:
    artifact_type: str = ""
    name: str = ""
    description: str = ""
    required: bool = True


@dataclass
class MissionAcceptanceGate:
    gate_id: str = ""
    description: str = ""
    verification_method: str = ""
    required: bool = True


@dataclass
class MissionRisk:
    risk_id: str = ""
    level: str = "low"
    description: str = ""
    mitigation: str = ""


@dataclass
class MissionHumanApproval:
    required: bool = False
    reason: str = ""


@dataclass
class MissionContract:
    schema_version: str = SCHEMA_VERSION
    mission_id: str = ""
    created_at: str | None = None
    task_type: MissionTaskType | str = MissionTaskType.UNKNOWN
    user_goal: str = ""
    intent_summary: str = ""
    non_goals: list[str] = field(default_factory=list)
    hard_constraints: list[str] = field(default_factory=list)
    soft_preferences: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    assumptions: list[MissionAssumption] = field(default_factory=list)
    required_capabilities: list[MissionCapabilityRequirement] = field(default_factory=list)
    required_artifacts: list[MissionArtifactContract] = field(default_factory=list)
    acceptance_gates: list[MissionAcceptanceGate] = field(default_factory=list)
    risks: list[MissionRisk] = field(default_factory=list)
    human_approval: MissionHumanApproval = field(default_factory=MissionHumanApproval)
    recommended_route: str = ""
    notes: list[str] = field(default_factory=list)


def _enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _clean_mapping(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _clean_mapping(asdict(value))
    if isinstance(value, dict):
        return {key: _clean_mapping(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean_mapping(item) for item in value]
    return value


def _coerce_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _build_items(cls: type, values: Any) -> list[Any]:
    items: list[Any] = []
    for item in _coerce_list(values):
        if isinstance(item, cls):
            items.append(item)
        elif isinstance(item, dict):
            items.append(cls(**item))
        else:
            items.append(item)
    return items


def mission_contract_to_dict(contract: MissionContract) -> dict[str, Any]:
    """Convert a MissionContract to deterministic plain Python data."""

    data = _clean_mapping(contract)
    ordered_keys = [
        "schema_version",
        "mission_id",
        "created_at",
        "task_type",
        "user_goal",
        "intent_summary",
        "non_goals",
        "hard_constraints",
        "soft_preferences",
        "unknowns",
        "assumptions",
        "required_capabilities",
        "required_artifacts",
        "acceptance_gates",
        "risks",
        "human_approval",
        "recommended_route",
        "notes",
    ]
    return {key: data.get(key) for key in ordered_keys}


def mission_contract_from_dict(data: dict[str, Any]) -> MissionContract:
    """Build a MissionContract from YAML/JSON-compatible data.

    Unknown enum values are preserved as strings so validation can return a
    structured error instead of raising a raw traceback.
    """

    payload = dict(data or {})
    human_approval_data = payload.get("human_approval") or {}
    if isinstance(human_approval_data, MissionHumanApproval):
        human_approval = human_approval_data
    elif isinstance(human_approval_data, dict):
        human_approval = MissionHumanApproval(**human_approval_data)
    else:
        human_approval = MissionHumanApproval()

    task_type_raw = payload.get("task_type", MissionTaskType.UNKNOWN)
    try:
        task_type: MissionTaskType | str = MissionTaskType(_enum_value(task_type_raw))
    except ValueError:
        task_type = str(task_type_raw)

    return MissionContract(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        mission_id=str(payload.get("mission_id", "")),
        created_at=payload.get("created_at"),
        task_type=task_type,
        user_goal=str(payload.get("user_goal", "")),
        intent_summary=str(payload.get("intent_summary", "")),
        non_goals=[str(item) for item in _coerce_list(payload.get("non_goals"))],
        hard_constraints=[str(item) for item in _coerce_list(payload.get("hard_constraints"))],
        soft_preferences=[str(item) for item in _coerce_list(payload.get("soft_preferences"))],
        unknowns=[str(item) for item in _coerce_list(payload.get("unknowns"))],
        assumptions=_build_items(MissionAssumption, payload.get("assumptions")),
        required_capabilities=_build_items(
            MissionCapabilityRequirement,
            payload.get("required_capabilities"),
        ),
        required_artifacts=_build_items(
            MissionArtifactContract,
            payload.get("required_artifacts"),
        ),
        acceptance_gates=_build_items(
            MissionAcceptanceGate,
            payload.get("acceptance_gates"),
        ),
        risks=_build_items(MissionRisk, payload.get("risks")),
        human_approval=human_approval,
        recommended_route=str(payload.get("recommended_route", "")),
        notes=[str(item) for item in _coerce_list(payload.get("notes"))],
    )


def _error(field: str, message: str, code: str = "invalid") -> dict[str, str]:
    return {"field": field, "message": message, "code": code}


def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _validate_enum(field: str, value: Any, allowed: set[str], errors: list[dict[str, str]]) -> None:
    text = str(_enum_value(value))
    if text not in allowed:
        errors.append(
            _error(
                field,
                f"unknown value {text!r}; expected one of {sorted(allowed)}",
                "unknown_enum",
            )
        )


def validate_mission_contract(contract: MissionContract | dict[str, Any]) -> list[dict[str, str]]:
    """Return structured validation errors for a Mission Contract.

    An empty list means the contract is valid. The function deliberately returns
    structured errors instead of raising so callers can surface clear feedback to
    users or future compiler stages.
    """

    if isinstance(contract, dict):
        try:
            contract = mission_contract_from_dict(contract)
        except Exception as exc:
            return [_error("contract", f"failed to parse contract mapping: {exc}", "parse_error")]

    errors: list[dict[str, str]] = []
    if _is_blank(contract.schema_version):
        errors.append(_error("schema_version", "schema_version is required", "required"))
    if _is_blank(contract.mission_id):
        errors.append(_error("mission_id", "mission_id is required", "required"))
    _validate_enum(
        "task_type",
        contract.task_type,
        {item.value for item in MissionTaskType},
        errors,
    )
    if _is_blank(contract.user_goal):
        errors.append(_error("user_goal", "user_goal cannot be empty", "required"))

    for index, item in enumerate(contract.assumptions):
        if not isinstance(item, MissionAssumption):
            errors.append(_error(f"assumptions[{index}]", "entry must be a mapping", "type"))
            continue
        _validate_enum(
            f"assumptions[{index}].confidence",
            item.confidence,
            {"low", "medium", "high"},
            errors,
        )

    for index, item in enumerate(contract.required_capabilities):
        if not isinstance(item, MissionCapabilityRequirement):
            errors.append(_error(f"required_capabilities[{index}]", "entry must be a mapping", "type"))
            continue
        if _is_blank(item.capability):
            errors.append(_error(f"required_capabilities[{index}].capability", "capability is required", "required"))
        if _is_blank(item.reason):
            errors.append(_error(f"required_capabilities[{index}].reason", "reason is required", "required"))
        _validate_enum(
            f"required_capabilities[{index}].source",
            item.source,
            {"inferred", "user_requested", "system_required"},
            errors,
        )

    for index, item in enumerate(contract.required_artifacts):
        if not isinstance(item, MissionArtifactContract):
            errors.append(_error(f"required_artifacts[{index}]", "entry must be a mapping", "type"))
            continue
        if _is_blank(item.artifact_type):
            errors.append(_error(f"required_artifacts[{index}].artifact_type", "artifact_type is required", "required"))
        else:
            _validate_enum(
                f"required_artifacts[{index}].artifact_type",
                item.artifact_type,
                {"report", "patch", "document", "media", "dataset", "decision_card", "other"},
                errors,
            )
        if _is_blank(item.name):
            errors.append(_error(f"required_artifacts[{index}].name", "name is required", "required"))
        if _is_blank(item.description):
            errors.append(_error(f"required_artifacts[{index}].description", "description is required", "required"))

    for index, item in enumerate(contract.acceptance_gates):
        if not isinstance(item, MissionAcceptanceGate):
            errors.append(_error(f"acceptance_gates[{index}]", "entry must be a mapping", "type"))
            continue
        if _is_blank(item.gate_id):
            errors.append(_error(f"acceptance_gates[{index}].gate_id", "gate_id is required", "required"))
        if _is_blank(item.description):
            errors.append(_error(f"acceptance_gates[{index}].description", "description is required", "required"))
        if _is_blank(item.verification_method):
            errors.append(_error(f"acceptance_gates[{index}].verification_method", "verification_method is required", "required"))
        else:
            _validate_enum(
                f"acceptance_gates[{index}].verification_method",
                item.verification_method,
                {"test", "review", "artifact_exists", "citation_check", "manual_review", "other"},
                errors,
            )

    for index, item in enumerate(contract.risks):
        if not isinstance(item, MissionRisk):
            errors.append(_error(f"risks[{index}]", "entry must be a mapping", "type"))
            continue
        _validate_enum(f"risks[{index}].level", item.level, {"low", "medium", "high"}, errors)

    return errors


def load_mission_contract(path: Path | str) -> MissionContract:
    """Load a Mission Contract from YAML."""

    contract_path = Path(path)
    data = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("mission contract YAML must contain a mapping at the top level")
    return mission_contract_from_dict(data)


def write_mission_contract(contract: MissionContract, path: Path | str) -> None:
    """Write a Mission Contract to deterministic UTF-8 YAML."""

    contract_path = Path(path)
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    data = mission_contract_to_dict(contract)
    text = yaml.safe_dump(
        data,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    contract_path.write_text(text.rstrip() + "\n", encoding="utf-8")