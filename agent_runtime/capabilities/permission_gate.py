"""S9 permission decisions for capability selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_runtime.approvals.approval_policy import ApprovalPolicy
from agent_runtime.approvals.policy_engine import decide_approval
from .capability_contract import CapabilityStatus, RiskLevel
from .registry import CapabilityRegistry


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    capability_id: str
    allowed: bool
    reason: str
    requires_approval: bool = False
    approval_mode: str = "not_required"
    approval_grant: dict[str, Any] | None = None


class PermissionGate:
    def __init__(
        self,
        registry: CapabilityRegistry,
        *,
        disabled_capabilities: set[str] | None = None,
        approved_capabilities: set[str] | None = None,
        approval_policy: ApprovalPolicy | None = None,
    ) -> None:
        self.registry = registry
        self.disabled_capabilities = disabled_capabilities or set()
        self.approved_capabilities = approved_capabilities or set()
        self.approval_policy = approval_policy or ApprovalPolicy()

    def evaluate(
        self,
        capability_id: str,
        *,
        request_context: dict[str, Any] | None = None,
    ) -> PermissionDecision:
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
        if capability_id in self.approved_capabilities and not request_context:
            return PermissionDecision(
                capability_id,
                True,
                "explicitly_approved",
                approval_mode="explicitly_approved",
            )
        if needs_approval or request_context:
            context = dict(request_context or {})
            contextual_capabilities = list(context.pop("capabilities", []))
            decision = decide_approval(
                {
                    "action": "capability_use",
                    "capabilities": [
                        capability_id,
                        *sorted(record.permissions),
                        *contextual_capabilities,
                    ],
                    "bounded_scope": True,
                    "scope_binding": "runtime_recheck",
                    "reversible": True,
                    "estimated_cost_usd": 0.0,
                    **context,
                },
                self.approval_policy,
            )
            if decision.mode == "forbidden":
                return PermissionDecision(
                    capability_id,
                    False,
                    "forbidden",
                    approval_mode=decision.mode,
                )
            if decision.requires_human:
                return PermissionDecision(
                    capability_id,
                    False,
                    "approval_required",
                    requires_approval=True,
                    approval_mode=decision.mode,
                )
            return PermissionDecision(
                capability_id,
                True,
                "policy_auto_approved",
                approval_mode=decision.mode,
                approval_grant=decision.grant,
            )
        return PermissionDecision(capability_id, True, "allowed", requires_approval=False)
