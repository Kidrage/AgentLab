"""S9 permission decisions for capability selection."""

from __future__ import annotations

from dataclasses import dataclass

from .capability_contract import CapabilityStatus, RiskLevel
from .registry import CapabilityRegistry


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    capability_id: str
    allowed: bool
    reason: str
    requires_approval: bool = False


class PermissionGate:
    def __init__(
        self,
        registry: CapabilityRegistry,
        *,
        disabled_capabilities: set[str] | None = None,
        approved_capabilities: set[str] | None = None,
    ) -> None:
        self.registry = registry
        self.disabled_capabilities = disabled_capabilities or set()
        self.approved_capabilities = approved_capabilities or set()

    def evaluate(self, capability_id: str) -> PermissionDecision:
        record = self.registry.get(capability_id)
        if capability_id in self.disabled_capabilities or record.status == CapabilityStatus.DISABLED:
            return PermissionDecision(capability_id, False, "capability_disabled")
        if record.status == CapabilityStatus.MISSING_BACKEND:
            return PermissionDecision(capability_id, False, "missing_backend")
        needs_approval = (
            record.status == CapabilityStatus.REQUIRES_APPROVAL
            or record.risk_level == RiskLevel.HIGH
            or bool({"external", "network", "shell", "write"}.intersection(record.permissions))
        )
        if needs_approval and capability_id not in self.approved_capabilities:
            return PermissionDecision(capability_id, False, "approval_required", requires_approval=True)
        return PermissionDecision(capability_id, True, "allowed", requires_approval=False)
