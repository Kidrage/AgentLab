"""Approval gate for high-risk worker assignments."""

from __future__ import annotations

from agent_runtime.capabilities.compatibility import CompatibilityChecker
from agent_runtime.workers.worker_card import WorkerCard


class ApprovalGate:
    def __init__(self, checker: CompatibilityChecker) -> None:
        self.checker = checker

    def evaluate(
        self,
        worker: WorkerCard,
        role: str,
        *,
        approved_workers: set[str] | None = None,
    ) -> tuple[bool, list[str]]:
        approved = approved_workers or set()
        if worker.worker_id in approved:
            return False, []
        required, capabilities = self.checker.requires_approval_for_assignment(worker.worker_id, role)
        reasons = [f"high-risk capability: {capability}" for capability in capabilities]
        if worker.risk_level == "high":
            required = True
            reasons.append("worker risk level is high")
        if worker.approval_required:
            required = True
            reasons.append("worker policy requires approval")
        return required, sorted(set(reasons))
