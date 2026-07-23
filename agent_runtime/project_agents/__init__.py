"""Project Agent organization public interface."""

from .contract import AgentContract, AgentContractViolation, scope_matches
from .factory import ProjectAgentFactory
from .lifecycle import AgentLifecycle
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
    "ProjectAgentFactory",
    "ProjectAgentRegistry",
    "scope_matches",
]
