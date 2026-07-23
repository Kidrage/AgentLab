"""Approval gate for high-risk worker assignments."""

from __future__ import annotations

from agent_runtime.capabilities.compatibility import CompatibilityChecker
from agent_runtime.approvals.approval_policy import ApprovalPolicy
from agent_runtime.approvals.policy_engine import ApprovalDecision, decide_approval
from agent_runtime.workers.worker_card import WorkerCard


class ApprovalGate:
    def __init__(
        self,
        checker: CompatibilityChecker,
        policy: ApprovalPolicy | None = None,
    ) -> None:
        self.checker = checker
        self.policy = policy or ApprovalPolicy()

    def evaluate_decision(
        self,
        worker: WorkerCard,
        role: str,
        *,
        approved_workers: set[str] | None = None,
        request_context: dict | None = None,
    ) -> ApprovalDecision:
        approved = approved_workers or set()
        if worker.worker_id in approved:
            return ApprovalDecision(
                mode="explicitly_approved",
                requires_human=False,
                reasons=("worker_preapproved",),
            )
        _, capabilities = self.checker.requires_approval_for_assignment(
            worker.worker_id,
            role,
        )
        request = {
            "action": "worker_assignment",
            "worker": worker.worker_id,
            "role": role,
            "capabilities": capabilities,
            "risk_level": worker.risk_level,
            "bounded_scope": True,
            "reversible": True,
            "estimated_cost_usd": 0.0,
            **(request_context or {}),
        }
        return decide_approval(request, self.policy)

    def evaluate(
        self,
        worker: WorkerCard,
        role: str,
        *,
        approved_workers: set[str] | None = None,
    ) -> tuple[bool, list[str]]:
        decision = self.evaluate_decision(
            worker,
            role,
            approved_workers=approved_workers,
        )
        return decision.requires_human, list(decision.reasons)
