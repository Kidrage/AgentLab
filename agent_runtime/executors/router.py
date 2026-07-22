from __future__ import annotations

from agent_runtime.approvals.approval_policy import ApprovalPolicy
from agent_runtime.approvals.policy_engine import ApprovalDecision, decide_approval
from agent_runtime.executors.models import EXTERNAL_PROVIDER_TYPES, ExecutionRequest, ExecutorDecision, ExecutorProvider
from agent_runtime.executors.policy import ExecutorRouterPolicy
from agent_runtime.executors.provider_registry import filter_providers_for_request


def route_execution_request(
    request: ExecutionRequest,
    providers: list[ExecutorProvider],
    policy: ExecutorRouterPolicy,
    approval_policy: ApprovalPolicy | None = None,
) -> ExecutorDecision:
    approval_policy = approval_policy or policy.approval_policy
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

        approval = _evaluate_provider_approval(request, provider, approval_policy)
        if approval.mode == "forbidden":
            return ExecutorDecision(
                status="BLOCKED_BY_POLICY",
                selected_provider_id=provider.provider_id,
                rejected_providers=rejected,
                reason=list(approval.reasons),
                approval_required=False,
                approval_mode=approval.mode,
            )
        if approval.requires_human:
            return ExecutorDecision(
                status="NEEDS_APPROVAL",
                selected_provider_id=provider.provider_id,
                rejected_providers=rejected,
                reason=list(approval.reasons),
                approval_required=True,
                approval_mode=approval.mode,
            )

        if provider.provider_type == "mock_executor":
            if policy.routing.get("allow_mock_executor", True) is True:
                return ExecutorDecision(
                    status="ROUTED",
                    selected_provider_id=provider.provider_id,
                    rejected_providers=rejected,
                    reason=["mock executor allowed by policy"],
                    approval_required=False,
                    approval_mode=approval.mode,
                    approval_grant=approval.grant,
                )
            rejected.append({"provider_id": provider.provider_id, "reasons": ["mock executor disabled by policy"]})
            continue

        if provider.execution_mode == "dry_run":
            return ExecutorDecision(
                status="DRY_RUN_ONLY",
                selected_provider_id=provider.provider_id,
                rejected_providers=rejected,
                reason=["provider is available for dry-run planning only"],
                approval_required=False,
                approval_mode=approval.mode,
                approval_grant=approval.grant,
            )

        return ExecutorDecision(
            status="ROUTED",
            selected_provider_id=provider.provider_id,
            rejected_providers=rejected,
            reason=["provider matched request and policy"],
            approval_required=False,
            approval_mode=approval.mode,
            approval_grant=approval.grant,
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


def _evaluate_provider_approval(
    request: ExecutionRequest,
    provider: ExecutorProvider,
    approval_policy: ApprovalPolicy,
) -> ApprovalDecision:
    action = "private_data_egress" if request.contains_private_data else request.approval_action
    cost_known = provider.expected_cost_tier == "free" or request.estimated_cost_usd is not None
    estimated_cost = 0.0 if provider.expected_cost_tier == "free" else request.estimated_cost_usd
    capabilities = list(request.required_capabilities)
    if provider.provider_type in EXTERNAL_PROVIDER_TYPES:
        capabilities.extend(["external_execution", "network_access"])
    return decide_approval(
        {
            "action": action,
            "task_id": request.task_id,
            "provider_id": provider.provider_id,
            "capabilities": capabilities,
            "bounded_scope": request.bounded_scope,
            "reversible": provider.execution_mode in {"mock", "dry_run", "manual_handoff_only"},
            "cost_visibility": "known" if cost_known else "unknown_external_provider_cost",
            "estimated_cost_usd": estimated_cost or 0.0,
            "max_cost_usd": request.max_cost_usd,
            "allowed_files": request.allowed_files,
            "forbidden_files": request.forbidden_files,
        },
        approval_policy,
    )
