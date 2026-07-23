"""Runtime verification for policy-approved executor plans."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agent_runtime.approvals.policy_engine import verify_approval_grant
from agent_runtime.executors.models import (
    ExecutionPlan,
    ExecutionRequest,
    ExecutorProvider,
    to_plain_data,
)
from agent_runtime.executors.policy import ExecutorRouterPolicy
from agent_runtime.executors.provider_registry import load_executor_providers


def build_executor_plan_binding(
    request: ExecutionRequest,
    provider: ExecutorProvider,
    policy: ExecutorRouterPolicy,
) -> dict[str, object]:
    """Return the route, provider, budget, review, and output facts to authorize."""
    return {
        "task_id": request.task_id,
        "provider_id": provider.provider_id,
        "provider_type": provider.provider_type,
        "execution_mode": provider.execution_mode,
        "estimated_cost_usd": executor_estimated_cost(request, provider),
        "estimated_risk": provider.risk_level,
        "review_required": (
            request.requires_review
            or policy.routing.get("require_review_for_all_external_results", True) is True
        ),
        "output_dir": _resolved_path(request.output_dir),
        "executor_policy_hash": executor_policy_hash(policy, provider),
    }


def executor_estimated_cost(
    request: ExecutionRequest,
    provider: ExecutorProvider | None,
) -> float | None:
    if provider is None:
        return None
    if provider.cost_mode == "none" or provider.expected_cost_tier == "free":
        return 0.0
    return request.estimated_cost_usd


def executor_policy_hash(
    policy: ExecutorRouterPolicy,
    provider: ExecutorProvider,
) -> str:
    payload = {
        "enabled": policy.enabled,
        "routing": policy.routing,
        "budget": policy.budget,
        "safety": policy.safety,
        "provider": to_plain_data(provider),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def assert_execution_plan_authorized(
    request: ExecutionRequest,
    plan: ExecutionPlan,
    output_dir: Path,
    router_policy: ExecutorRouterPolicy,
    *,
    now: str | None = None,
) -> None:
    """Fail closed unless the current request matches a valid execution grant."""
    if plan.approval_mode != "auto_approved":
        raise PermissionError(f"execution_not_auto_approved:{plan.approval_mode}")
    if not plan.approval_grant or not plan.approval_request:
        raise PermissionError("missing_execution_approval_grant")
    if plan.approval_grant.get("authorizes_execution") is not True:
        raise PermissionError("grant_does_not_authorize_execution")
    expected_request = plan.approval_request.get("execution_request")
    if expected_request != to_plain_data(request):
        raise PermissionError("execution_request_mismatch")
    current_provider = next(
        (
            item
            for item in load_executor_providers(router_policy)
            if item.provider_id == plan.selected_provider_id
        ),
        None,
    )
    if current_provider is None:
        raise PermissionError("approved_provider_missing")
    expected_binding = plan.approval_request.get("plan_binding")
    actual_binding = {
        "task_id": plan.task_id,
        "provider_id": plan.selected_provider_id,
        "provider_type": plan.selected_provider_type,
        "execution_mode": plan.execution_mode,
        "estimated_cost_usd": plan.estimated_cost_usd,
        "estimated_risk": plan.estimated_risk,
        "review_required": plan.review_required,
        "output_dir": _resolved_path(output_dir),
        "executor_policy_hash": executor_policy_hash(router_policy, current_provider),
    }
    if expected_binding != actual_binding:
        raise PermissionError("execution_plan_binding_mismatch")
    if expected_binding != build_executor_plan_binding(request, current_provider, router_policy):
        raise PermissionError("executor_policy_or_request_changed")
    validation = verify_approval_grant(
        plan.approval_grant,
        plan.approval_request,
        router_policy.approval_policy,
        now=now,
    )
    if not validation.valid:
        raise PermissionError(f"invalid_execution_approval_grant:{','.join(validation.reasons)}")


def _resolved_path(value: Path | str | None) -> str:
    if value is None:
        return ""
    return str(Path(value).resolve())
