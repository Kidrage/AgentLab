"""Brain-layer contracts for AgentLab mainline foundations."""

from .acceptance_builder import build_acceptance_gates, gate_descriptions_for_task_type
from .artifact_builder import artifact_names_for_task_type, build_required_artifacts
from .domain_signals import DomainClassification, classify_task_type
from .domain_workflows import (
    DomainWorkflowCatalog,
    DomainWorkflowTemplate,
    load_domain_workflow_templates,
    select_domain_workflow,
)
from .mission_contract import (
    MissionAcceptanceGate,
    MissionArtifactContract,
    MissionAssumption,
    MissionCapabilityRequirement,
    MissionConstraint,
    MissionContract,
    MissionHumanApproval,
    MissionPriority,
    MissionRisk,
    MissionTaskType,
    load_mission_contract,
    mission_contract_from_dict,
    mission_contract_to_dict,
    validate_mission_contract,
    write_mission_contract,
)
from .task_compiler import (
    TaskCompilationError,
    TaskCompilationResult,
    compile_task_packet,
    compile_task_to_contract,
)

__all__ = [
    "DomainClassification",
    "DomainWorkflowCatalog",
    "DomainWorkflowTemplate",
    "MissionAcceptanceGate",
    "MissionArtifactContract",
    "MissionAssumption",
    "MissionCapabilityRequirement",
    "MissionConstraint",
    "MissionContract",
    "MissionHumanApproval",
    "MissionPriority",
    "MissionRisk",
    "MissionTaskType",
    "TaskCompilationError",
    "TaskCompilationResult",
    "artifact_names_for_task_type",
    "build_acceptance_gates",
    "build_required_artifacts",
    "classify_task_type",
    "compile_task_packet",
    "compile_task_to_contract",
    "gate_descriptions_for_task_type",
    "load_domain_workflow_templates",
    "load_mission_contract",
    "mission_contract_from_dict",
    "mission_contract_to_dict",
    "select_domain_workflow",
    "validate_mission_contract",
    "write_mission_contract",
]