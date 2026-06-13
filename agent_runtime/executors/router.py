from __future__ import annotations

from agent_runtime.executors.models import EXTERNAL_PROVIDER_TYPES, ExecutionRequest, ExecutorDecision, ExecutorProvider
from agent_runtime.executors.policy import ExecutorRouterPolicy
from agent_runtime.executors.provider_registry import filter_providers_for_request


def route_execution_request(
    request: ExecutionRequest,
    providers: list[ExecutorProvider],
    policy: ExecutorRouterPolicy,
) -> ExecutorDecision:
    if not policy.enabled:
        return ExecutorDecision(
            status="BLOCKED_BY_POLICY",
            reason=["executor router policy is disabled"],
            approval_required=False,
        )

    candidates, rejected = filter_providers_for_request(request, providers)
    priority = policy.provider_priority.get(request.task_type, [])
    by_id = {provider.provider_id: provider for provider in candidates}
    ordered = [by_id[item] for item in priority if item in by_id]
    ordered.extend(provider for provider in candidates if provider.provider_id not in set(priority))

    for provider in ordered:
        blocked = _policy_rejections(provider, policy)
        if blocked:
            rejected.append({"provider_id": provider.provider_id, "reasons": blocked})
            continue

        if provider.provider_type == "mock_executor":
            if policy.routing.get("allow_mock_executor", True) is True:
                return ExecutorDecision(
                    status="ROUTED",
                    selected_provider_id=provider.provider_id,
                    rejected_providers=rejected,
                    reason=["mock executor allowed by policy"],
                    approval_required=False,
                )
            rejected.append({"provider_id": provider.provider_id, "reasons": ["mock executor disabled by policy"]})
            continue

        approval_required = _requires_approval(provider, policy)
        if approval_required:
            return ExecutorDecision(
                status="NEEDS_APPROVAL",
                selected_provider_id=provider.provider_id,
                rejected_providers=rejected,
                reason=["external or unknown-cost provider requires approval"],
                approval_required=True,
            )

        if provider.execution_mode == "dry_run":
            return ExecutorDecision(
                status="DRY_RUN_ONLY",
                selected_provider_id=provider.provider_id,
                rejected_providers=rejected,
                reason=["provider is available for dry-run planning only"],
                approval_required=False,
            )

        return ExecutorDecision(
            status="ROUTED",
            selected_provider_id=provider.provider_id,
            rejected_providers=rejected,
            reason=["provider matched request and policy"],
            approval_required=False,
        )

    return ExecutorDecision(
        status="NO_PROVIDER",
        selected_provider_id=None,
        rejected_providers=rejected,
        reason=["no provider matched request and policy"],
        approval_required=False,
    )


def _policy_rejections(provider: ExecutorProvider, policy: ExecutorRouterPolicy) -> list[str]:
    reasons: list[str] = []
    if provider.execution_mode == "approved_auto" and policy.routing.get("allow_auto_execution", False) is not True:
        reasons.append("auto execution disabled by policy")
    if (
        provider.execution_mode not in {"mock", "manual_handoff_only", "dry_run"}
        and provider.provider_type != "mock_executor"
        and policy.routing.get("allow_auto_execution", False) is not True
    ):
        reasons.append("non-mock auto execution forbidden")
    if provider.execution_mode == "mock" and provider.provider_type != "mock_executor":
        reasons.append("mock execution mode limited to mock_executor providers")
    return reasons


def _requires_approval(provider: ExecutorProvider, policy: ExecutorRouterPolicy) -> bool:
    if provider.requires_approval:
        return True
    if (
        provider.provider_type in EXTERNAL_PROVIDER_TYPES
        and policy.routing.get("require_approval_for_external", True) is True
    ):
        return True
    if (
        provider.expected_cost_tier == "unknown"
        and policy.budget.get("unknown_cost_requires_approval", True) is True
    ):
        return True
    return False
