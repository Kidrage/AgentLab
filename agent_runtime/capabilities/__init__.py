"""S9 capability fabric public API."""

from .audio_contract import write_audio_contract
from .capability_contract import CapabilityRecord, CapabilityStatus, RiskLevel
from .document_contract import write_document_contract
from .gap_card import write_capability_gap_card
from .permission_gate import PermissionDecision, PermissionGate
from .registry import CapabilityRegistry, create_builtin_registry
from .vision_contract import write_vision_contract

# M2-2 extensions
from .capability_schema import CapabilityDefinition, CapabilitySchema
from .role_requirements import RoleRequirementDefinition, RoleRequirementsRegistry
from .compatibility import WorkerCapabilityRegistry, CompatibilityChecker
from .risk_tags import is_high_risk, is_approval_required_for_role_capability

__all__ = [
    "CapabilityRecord",
    "CapabilityRegistry",
    "CapabilityStatus",
    "PermissionDecision",
    "PermissionGate",
    "RiskLevel",
    "create_builtin_registry",
    "write_audio_contract",
    "write_capability_gap_card",
    "write_document_contract",
    "write_vision_contract",
    
    # M2-2 exports
    "CapabilityDefinition",
    "CapabilitySchema",
    "RoleRequirementDefinition",
    "RoleRequirementsRegistry",
    "WorkerCapabilityRegistry",
    "CompatibilityChecker",
    "is_high_risk",
    "is_approval_required_for_role_capability",
]

