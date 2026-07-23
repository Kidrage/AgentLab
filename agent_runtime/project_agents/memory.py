"""Global, project, and physically private Agent memory bindings."""

from __future__ import annotations

from pathlib import Path

from agent_runtime.knowledge_system.models import validate_namespace
from agent_runtime.knowledge_system.storage import KnowledgeStore

from .contract import AgentContractViolation
from .registry import ProjectAgentRegistry


class ProjectAgentMemory:
    def __init__(
        self, knowledge_store: KnowledgeStore, registry: ProjectAgentRegistry
    ):
        self.knowledge_store = knowledge_store
        self.registry = registry

    def layers_for(self, agent_id: str, *, domain: str) -> tuple[str, ...]:
        manifest = self.registry.get(agent_id)
        project_id = self.registry.truth.current().project_id
        private = f"agent.{project_id}.{agent_id}"
        declared = str(manifest.knowledge_binding.get("namespace") or "")
        if declared != private:
            raise AgentContractViolation(
                f"agent {agent_id!r} knowledge namespace is not project-private"
            )
        return tuple(
            validate_namespace(item)
            for item in (
                "system.agentlab",
                f"domain.{domain}",
                f"project.{project_id}",
                private,
            )
        )

    def ensure_private_space(self, agent_id: str) -> Path:
        manifest = self.registry.get(agent_id)
        project_id = self.registry.truth.current().project_id
        expected = f"agent.{project_id}.{agent_id}"
        namespace = str(manifest.knowledge_binding.get("namespace") or "")
        if namespace != expected:
            raise AgentContractViolation(
                f"agent {agent_id!r} knowledge namespace is not project-private"
            )
        return self.knowledge_store.ensure_space(namespace)
