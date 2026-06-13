from __future__ import annotations

from agent_runtime.executors.models import (
    EXECUTION_MODES,
    EXTERNAL_PROVIDER_TYPES,
    PROVIDER_TYPES,
    ExecutionRequest,
    ExecutorProvider,
)
from agent_runtime.executors.policy import ExecutorRouterPolicy


def load_executor_providers(policy: ExecutorRouterPolicy) -> list[ExecutorProvider]:
    seen: set[str] = set()
    providers: list[ExecutorProvider] = []
    for raw in policy.providers:
        provider_id = str(raw.get("provider_id") or "")
        if not provider_id:
            raise ValueError("executor provider missing provider_id")
        if provider_id in seen:
            raise ValueError(f"duplicate executor provider_id: {provider_id}")
        seen.add(provider_id)

        provider_type = str(raw.get("provider_type") or "")
        if provider_type not in PROVIDER_TYPES:
            raise ValueError(f"invalid provider_type for {provider_id}: {provider_type}")
        execution_mode = str(raw.get("execution_mode") or "disabled")
        if execution_mode not in EXECUTION_MODES:
            raise ValueError(f"invalid execution_mode for {provider_id}: {execution_mode}")

        requires_approval = bool(raw.get("requires_approval", False))
        if provider_type in EXTERNAL_PROVIDER_TYPES:
            requires_approval = True
        if (
            str(raw.get("expected_cost_tier") or "unknown") == "unknown"
            and policy.budget.get("unknown_cost_requires_approval", True) is True
        ):
            requires_approval = True

        supports_auto_execution = bool(raw.get("supports_auto_execution", False))
        if execution_mode == "approved_auto" and not supports_auto_execution:
            raise ValueError(f"{provider_id} uses approved_auto but supports_auto_execution=false")

        providers.append(
            ExecutorProvider(
                provider_id=provider_id,
                provider_type=provider_type,
                display_name=str(raw.get("display_name") or provider_id),
                enabled=raw.get("enabled", False) is True,
                execution_mode=execution_mode,
                capabilities=[str(item) for item in raw.get("capabilities") or []],
                suitable_task_types=[str(item) for item in raw.get("suitable_task_types") or []],
                risk_level=str(raw.get("risk_level") or "medium"),
                requires_approval=requires_approval,
                cost_mode=str(raw.get("cost_mode") or "unknown"),
                expected_cost_tier=str(raw.get("expected_cost_tier") or "unknown"),
                supports_auto_execution=supports_auto_execution,
                supports_manual_handoff=raw.get("supports_manual_handoff", False) is True,
                notes=[str(item) for item in raw.get("notes") or []],
            )
        )
    return providers


def get_enabled_providers(providers: list[ExecutorProvider]) -> list[ExecutorProvider]:
    return [provider for provider in providers if provider.enabled and provider.execution_mode != "disabled"]


def filter_providers_for_request(
    request: ExecutionRequest,
    providers: list[ExecutorProvider],
) -> tuple[list[ExecutorProvider], list[dict[str, object]]]:
    selected: list[ExecutorProvider] = []
    rejected: list[dict[str, object]] = []
    required = set(request.required_capabilities or [request.task_type])
    for provider in providers:
        reasons: list[str] = []
        if not provider.enabled:
            reasons.append("provider disabled")
        if provider.execution_mode == "disabled":
            reasons.append("execution mode disabled")
        if provider.suitable_task_types and request.task_type not in provider.suitable_task_types:
            reasons.append(f"task_type mismatch: {request.task_type}")
        if required and not required.issubset(set(provider.capabilities)):
            reasons.append("required capability mismatch")
        if reasons:
            rejected.append({"provider_id": provider.provider_id, "reasons": reasons})
        else:
            selected.append(provider)
    return selected, rejected
