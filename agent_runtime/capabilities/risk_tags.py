"""Risk tag verification and approval rules for AgentLab capabilities."""

from typing import List, Optional
from agent_runtime.capabilities.capability_schema import CapabilityDefinition
from agent_runtime.capabilities.role_requirements import RoleRequirementDefinition


def is_high_risk(capability: CapabilityDefinition) -> bool:
    """Check if a capability is marked high-risk."""
    return capability.risk_level.lower() == "high"


def is_approval_required_for_role_capability(
    role_req: RoleRequirementDefinition,
    capability: CapabilityDefinition
) -> bool:
    """Determine if a specific capability requires human approval for a given role.
    
    Approval is required if:
    1. The capability is listed in the role's human_approval_required_for.
    2. Or the capability itself has high risk level.
    """
    if capability.capability_id in role_req.human_approval_required_for:
        return True
    if is_high_risk(capability):
        return True
    return False


def get_high_risk_capabilities(capabilities: list[CapabilityDefinition]) -> list[CapabilityDefinition]:
    """Filter capabilities that are high-risk."""
    return [cap for cap in capabilities if is_high_risk(cap)]
