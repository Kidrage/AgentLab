"""Project-scoped agent identity, contract, runtime, and lifecycle schema."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any, Mapping


@dataclass(frozen=True)
class AgentManifest:
    id: str
    name: str
    version: str
    role: str
    description: str
    responsibilities: tuple[str, ...]
    runtime_role: str
    read_scope: tuple[str, ...]
    write_scope: tuple[str, ...]
    approval_scope: tuple[str, ...]
    knowledge_binding: Mapping[str, Any]
    model_profile: str
    tool_permission: tuple[str, ...]
    budget_profile: str
    status: str
    acceptance_rules: tuple[str, ...]
    collaboration: Mapping[str, Any] = field(default_factory=dict)
    manifest_revision: int = 1

    def __post_init__(self) -> None:
        for name in (
            "responsibilities",
            "read_scope",
            "write_scope",
            "approval_scope",
            "tool_permission",
            "acceptance_rules",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    def evolve(self, **changes: Any) -> "AgentManifest":
        """Create the next immutable manifest revision."""
        if "id" in changes and changes["id"] != self.id:
            raise ValueError("agent id is immutable")
        changes["manifest_revision"] = self.manifest_revision + 1
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "agent-manifest/v1",
            "identity": {
                "id": self.id,
                "name": self.name,
                "version": self.version,
                "manifest_revision": self.manifest_revision,
            },
            "role": {
                "name": self.role,
                "description": self.description,
                "responsibilities": list(self.responsibilities),
                "runtime_role": self.runtime_role,
            },
            "authority": {
                "read_scope": list(self.read_scope),
                "write_scope": list(self.write_scope),
                "approval_scope": list(self.approval_scope),
            },
            "knowledge": deepcopy(dict(self.knowledge_binding)),
            "runtime": {
                "model_profile": self.model_profile,
                "tool_permission": list(self.tool_permission),
                "budget_profile": self.budget_profile,
            },
            "lifecycle": {"status": self.status},
            "validation": {"acceptance_rules": list(self.acceptance_rules)},
            "collaboration": deepcopy(dict(self.collaboration)),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AgentManifest":
        identity = data.get("identity") or {}
        role = data.get("role") or {}
        authority = data.get("authority") or {}
        runtime = data.get("runtime") or {}
        lifecycle = data.get("lifecycle") or {}
        validation = data.get("validation") or {}
        return cls(
            id=str(identity["id"]),
            name=str(identity["name"]),
            version=str(identity["version"]),
            manifest_revision=int(identity.get("manifest_revision") or 1),
            role=str(role["name"]),
            description=str(role["description"]),
            responsibilities=tuple(role.get("responsibilities") or ()),
            runtime_role=str(role["runtime_role"]),
            read_scope=tuple(authority.get("read_scope") or ()),
            write_scope=tuple(authority.get("write_scope") or ()),
            approval_scope=tuple(authority.get("approval_scope") or ()),
            knowledge_binding=deepcopy(data.get("knowledge") or {}),
            model_profile=str(runtime["model_profile"]),
            tool_permission=tuple(runtime.get("tool_permission") or ()),
            budget_profile=str(runtime["budget_profile"]),
            status=str(lifecycle["status"]),
            acceptance_rules=tuple(validation.get("acceptance_rules") or ()),
            collaboration=deepcopy(data.get("collaboration") or {}),
        )


@dataclass(frozen=True)
class AgentTeamProposal:
    project_id: str
    manifests: tuple[AgentManifest, ...]
    source: str
    requires_approval: bool
    rationale: str
