"""Compatibility and validation rules between workers, roles, and capabilities."""

from pathlib import Path
from typing import Dict, List, Optional, Tuple
import yaml

from agent_runtime.capabilities.capability_schema import CapabilitySchema
from agent_runtime.capabilities.role_requirements import RoleRequirementDefinition, RoleRequirementsRegistry
from agent_runtime.capabilities.risk_tags import is_approval_required_for_role_capability


class WorkerCapabilityRegistry:
    def __init__(self, worker_capabilities: dict[str, list[str]]) -> None:
        self._worker_capabilities = worker_capabilities

    @classmethod
    def load_from_file(cls, config_path: Path) -> "WorkerCapabilityRegistry":
        if not config_path.exists():
            return cls({})
        try:
            content = config_path.read_text(encoding="utf-8")
            data = yaml.safe_load(content) or {}
            workers_data = data.get("workers", {})
            
            worker_caps = {}
            for worker_id, worker_info in workers_data.items():
                worker_caps[worker_id] = worker_info.get("supported_capabilities") or []
            return cls(worker_caps)
        except Exception:
            return cls({})

    def get_supported_capabilities(self, worker_id: str) -> list[str]:
        return self._worker_capabilities.get(worker_id, [])

    def get_all(self) -> dict[str, list[str]]:
        return self._worker_capabilities


class CompatibilityChecker:
    def __init__(
        self,
        schema: CapabilitySchema,
        roles_registry: RoleRequirementsRegistry,
        workers_registry: WorkerCapabilityRegistry,
    ) -> None:
        self.schema = schema
        self.roles_registry = roles_registry
        self.workers_registry = workers_registry

    def is_compatible(self, worker_id: str, role_name: str) -> tuple[bool, str]:
        """Check if a worker is compatible with a role.
        
        Returns:
            (is_compatible, reason_or_success_message)
        """
        role_req = self.roles_registry.get_role_requirements(role_name)
        if not role_req:
            return False, f"Unknown role: {role_name}"

        supported = self.workers_registry.get_supported_capabilities(worker_id)
        if not supported:
            # Fallback check if worker isn't in yml defaults but exists
            return False, f"Worker '{worker_id}' has no registered capabilities."

        # 1. Check required capabilities
        for req_cap in role_req.required_capabilities:
            if req_cap not in supported:
                return False, f"Worker '{worker_id}' lacks required capability '{req_cap}' for role '{role_name}'."

        # 2. Check forbidden capabilities
        for forbidden_cap in role_req.forbidden_capabilities:
            if forbidden_cap in supported:
                return False, f"Worker '{worker_id}' supports forbidden capability '{forbidden_cap}' for role '{role_name}'."

        return True, "Compatible"

    def requires_approval_for_assignment(self, worker_id: str, role_name: str) -> tuple[bool, list[str]]:
        """Check if assigning a worker to a role requires human approval.
        
        Approval is required if the worker supports any capability that is high-risk,
        or if the capability is explicitly listed as requiring human approval for the role.
        """
        role_req = self.roles_registry.get_role_requirements(role_name)
        if not role_req:
            return True, ["unknown_role"]

        supported = self.workers_registry.get_supported_capabilities(worker_id)
        reasons = []

        for cap_id in supported:
            # Check if high-risk capability
            cap_def = self.schema.get_capability(cap_id)
            if cap_def and cap_def.risk_level.lower() == "high":
                reasons.append(cap_id)
            # Check if explicitly requires approval for this role
            elif cap_id in role_req.human_approval_required_for:
                reasons.append(cap_id)

        return len(reasons) > 0, sorted(list(set(reasons)))
