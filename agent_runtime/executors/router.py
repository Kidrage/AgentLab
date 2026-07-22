from __future__ import annotations

from agent_runtime.approvals.approval_policy import ApprovalPolicy
from agent_runtime.approvals.policy_engine import ApprovalDecision, decide_approval
from agent_runtime.executors.authorization import build_executor_plan_binding
from agent_runtime.executors.models import (
    EXTERNAL_PROVIDER_TYPES,
    ExecutionRequest,
    ExecutorDecision,
    ExecutorProvider,
    to_plain_data,
)
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
        blocked = _policy_rejections(request, provider, policy)
        if blocked:
            rejected.append({"provider_id": provider.provider_id, "reasons": blocked})
            continue

        approval = _evaluate_provider_approval(request, provider, policy, approval_policy)
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

    forbidden_reasons = [
        reason
        for item in rejected
        for reason in item.get("reasons", [])
        if str(reason).startswith("forbidden:")
    ]
    return ExecutorDecision(
        status="BLOCKED_BY_POLICY" if forbidden_reasons else "NO_PROVIDER",
        selected_provider_id=None,
        rejected_providers=rejected,
        reason=forbidden_reasons or ["no provider matched request and policy"],
        approval_required=False,
        approval_mode="forbidden" if forbidden_reasons else "not_required",
    )


def _policy_rejections(
    request: ExecutionRequest,
    provider: ExecutorProvider,
    policy: ExecutorRouterPolicy,
) -> list[str]:
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
    executes_external = (
        provider.provider_type in EXTERNAL_PROVIDER_TYPES
        and provider.execution_mode not in {"manual_handoff_only", "dry_run"}
    )
    if executes_external and policy.safety.get("forbid_network_execution", False) is True:
        reasons.append("forbidden: network execution disabled by executor safety policy")
    capabilities = set(request.required_capabilities).union(provider.capabilities)
    if (
        capabilities.intersection({"remote_clone", "git_clone"})
        and policy.safety.get("forbid_remote_clone", True) is True
    ):
        reasons.append("forbidden: remote clone disabled by executor safety policy")
    if (
        capabilities.intersection({"external_script_execution", "shell_execution"})
        and policy.safety.get("forbid_external_script_execution", True) is True
    ):
        reasons.append("forbidden: external script execution disabled by executor safety policy")
    if request.contains_secrets and policy.safety.get("forbid_secret_exposure", True) is True:
        reasons.append("forbidden: secret exposure disabled by executor safety policy")
    if (
        executes_external
        and "subscription" in provider.cost_mode
        and policy.safety.get("forbid_subscription_misuse", True) is True
    ):
        reasons.append("forbidden: subscription-backed auto execution disabled by executor safety policy")
    if (
        request.approval_action in {"merge", "production_promotion"}
        and not request.requires_review
        and policy.safety.get("forbid_unreviewed_result_merge", True) is True
    ):
        reasons.append("forbidden: unreviewed merge disabled by executor safety policy")
    return reasons


def _evaluate_provider_approval(
    request: ExecutionRequest,
    provider: ExecutorProvider,
    router_policy: ExecutorRouterPolicy,
    approval_policy: ApprovalPolicy,
) -> ApprovalDecision:
    if request.contains_secrets:
        action = "secret_exposure"
    elif request.contains_private_data:
        action = "private_data_egress"
    else:
        action = request.approval_action
    cost_known = provider.expected_cost_tier == "free" or request.estimated_cost_usd is not None
    estimated_cost = 0.0 if provider.expected_cost_tier == "free" else request.estimated_cost_usd
    capabilities = list(request.required_capabilities)
    if provider.provider_type in EXTERNAL_PROVIDER_TYPES:
        capabilities.extend(["external_execution", "network_access"])
    plan_binding = build_executor_plan_binding(request, provider, router_policy)
    return decide_approval(
        {
            "action": action,
            "task_id": request.task_id,
            "provider_id": provider.provider_id,
            "capabilities": capabilities,
            "bounded_scope": request.bounded_scope,
            "reversible": request.reversible,
            "cost_visibility": "known" if cost_known else "unknown_external_provider_cost",
            "estimated_cost_usd": estimated_cost,
            "max_cost_usd": request.max_cost_usd,
            "router_max_cost_usd": router_policy.budget.get("max_cost_usd_per_task"),
            "allowed_files": request.allowed_files,
            "forbidden_files": request.forbidden_files,
            "execution_request": to_plain_data(request),
            "plan_binding": plan_binding,
            "output_dir": plan_binding["output_dir"],
            "runtime_recheck_required": request.output_dir is None,
        },
        approval_policy,
    )
