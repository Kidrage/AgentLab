"""Lifecycle transitions for registered project Agents."""

from __future__ import annotations

from typing import Any

from agent_runtime.project_truth import CanonicalCommitReceipt

from .contract import AgentContractViolation
from .registry import ProjectAgentRegistry


class AgentLifecycle:
    def __init__(self, registry: ProjectAgentRegistry):
        self.registry = registry

    def update(
        self,
        agent_id: str,
        *,
        expected_snapshot_id: str,
        actor_id: str,
        approved: bool = True,
        **changes: Any,
    ) -> CanonicalCommitReceipt:
        current = self.registry.get(agent_id)
        candidate = current.evolve(**changes)
        return self.registry.update(
            candidate,
            expected_snapshot_id=expected_snapshot_id,
            actor_id=actor_id,
            approved=approved,
            reason=f"Update project agent {agent_id}.",
        )

    def pause(
        self, agent_id: str, *, expected_snapshot_id: str, actor_id: str
    ) -> CanonicalCommitReceipt:
        current = self.registry.get(agent_id)
        if current.status != "active":
            raise AgentContractViolation("only active agents can be paused")
        return self.update(
            agent_id,
            status="paused",
            expected_snapshot_id=expected_snapshot_id,
            actor_id=actor_id,
        )

    def resume(
        self, agent_id: str, *, expected_snapshot_id: str, actor_id: str
    ) -> CanonicalCommitReceipt:
        current = self.registry.get(agent_id)
        if current.status != "paused":
            raise AgentContractViolation("only paused agents can be resumed")
        return self.update(
            agent_id,
            status="active",
            expected_snapshot_id=expected_snapshot_id,
            actor_id=actor_id,
        )

    def replace(
        self,
        agent_id: str,
        *,
        model_profile: str,
        expected_snapshot_id: str,
        actor_id: str,
        runtime_role: str | None = None,
    ) -> CanonicalCommitReceipt:
        changes: dict[str, Any] = {"model_profile": model_profile}
        if runtime_role is not None:
            changes["runtime_role"] = runtime_role
        return self.update(
            agent_id,
            expected_snapshot_id=expected_snapshot_id,
            actor_id=actor_id,
            **changes,
        )

    def archive(
        self, agent_id: str, *, expected_snapshot_id: str, actor_id: str
    ) -> CanonicalCommitReceipt:
        current = self.registry.get(agent_id)
        if current.status == "archived":
            raise AgentContractViolation("agent is already archived")
        return self.update(
            agent_id,
            status="archived",
            expected_snapshot_id=expected_snapshot_id,
            actor_id=actor_id,
        )
