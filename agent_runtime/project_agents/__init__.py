"""Project Agent organization public interface."""

from .contract import (
    AgentContract,
    AgentContractViolation,
    effective_contract_hash,
    scope_matches,
)
from .factory import ProjectAgentFactory
from .lifecycle import AgentLifecycle
from .memory import ProjectAgentMemory
from .collaboration import (
    CollaborationNode,
    CollaborationPlan,
    ExpertCollaborationPlanner,
)
from .models import AgentManifest, AgentTeamProposal
from .registry import (
    AgentRegistryConflict,
    AgentRegistryError,
    ProjectAgentRegistry,
)

__all__ = [
    "AgentContract",
    "AgentContractViolation",
    "AgentLifecycle",
    "AgentManifest",
    "AgentRegistryConflict",
    "AgentRegistryError",
    "AgentTeamProposal",
    "CollaborationNode",
    "CollaborationPlan",
    "ExpertCollaborationPlanner",
    "ProjectAgentFactory",
    "ProjectAgentMemory",
    "ProjectAgentRegistry",
    "effective_contract_hash",
    "scope_matches",
]
