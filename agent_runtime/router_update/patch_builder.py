from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agent_runtime.governance.models import ProviderRoutingRecommendation
from agent_runtime.router_update.models import RouterPatchOperation, RouterPolicyPatch, RouterUpdatePolicy
from agent_runtime.router_update.policy import is_external_provider, operation_path, provider_priority, providers_by_id


def build_router_policy_patch(
    recommendations: list[ProviderRoutingRecommendation],
    router_policy: dict,
    update_policy: RouterUpdatePolicy,
    output_dir: Path,
) -> RouterPolicyPatch:
    del output_dir
    providers = providers_by_id(router_policy)
    priorities = provider_priority(router_policy)
    operations: list[RouterPatchOperation] = []
    warnings: list[str] = []
    for index, recommendation in enumerate(recommendations, start=1):
        provider = providers.get(recommendation.provider_id)
        op_prefix = f"op_{index:03d}"
        if provider is None:
            warnings.append(f"provider not found in router policy: {recommendation.provider_id}")
            operations.append(_operation(op_prefix, recommendation, "no_op", "", None, None, ["provider not found in router policy"], False))
            continue
        if recommendation.recommendation == "require_manual_approval":
            operations.extend(_manual_approval_ops(op_prefix, recommendation, provider))
        elif recommendation.recommendation == "quarantine":
            operations.extend(_quarantine_ops(op_prefix, recommendation, provider, priorities))
        elif recommendation.recommendation == "downgrade":
            operations.extend(_priority_ops(op_prefix, recommendation, provider, priorities, direction="down"))
        elif recommendation.recommendation == "prefer":
            operations.extend(_prefer_ops(op_prefix, recommendation, provider, priorities))
        elif recommendation.recommendation in {"watchlist", "insufficient_data"}:
            note = "insufficient_data_watchlist_note" if recommendation.recommendation == "insufficient_data" else "watchlist_recommended_by_governance"
            operations.append(_note_op(op_prefix, recommendation, provider, note, requires_approval=recommendation.recommendation == "watchlist"))
        else:
            operations.append(_operation(op_prefix, recommendation, "no_op", operation_path(recommendation.provider_id, "none"), None, None, ["recommendation keeps current policy"], False))
    non_noop = [item for item in operations if item.operation_type != "no_op"]
    return RouterPolicyPatch(
        patch_id=f"router_patch_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        source_recommendations_path="",
        router_policy_path="",
        operations=operations,
        apply_automatically=False,
        requires_human_approval=bool(non_noop) and update_policy.safety.get("require_human_approval", True) is True,
        created_at=datetime.now(timezone.utc).isoformat(),
        warnings=warnings,
    )


def _manual_approval_ops(prefix: str, recommendation: ProviderRoutingRecommendation, provider: dict) -> list[RouterPatchOperation]:
    if provider.get("requires_approval") is True:
        return [_operation(prefix, recommendation, "no_op", operation_path(recommendation.provider_id, "requires_approval"), True, True, ["provider already requires approval"], False)]
    return [_operation(prefix, recommendation, "set_requires_approval", operation_path(recommendation.provider_id, "requires_approval"), provider.get("requires_approval", False), True, recommendation.reason or ["governance requires manual approval"], True)]


def _quarantine_ops(prefix: str, recommendation: ProviderRoutingRecommendation, provider: dict, priorities: dict[str, list[str]]) -> list[RouterPatchOperation]:
    operations = _manual_approval_ops(prefix + "_approval", recommendation, provider)
    operations.append(_note_op(prefix + "_note", recommendation, provider, "quarantine_recommended_by_governance", True, operation_type="add_quarantine_note"))
    operations.extend(_priority_ops(prefix + "_priority", recommendation, provider, priorities, direction="down", reason=["quarantine recommendation downgrades priority without disabling provider"]))
    return operations


def _prefer_ops(prefix: str, recommendation: ProviderRoutingRecommendation, provider: dict, priorities: dict[str, list[str]]) -> list[RouterPatchOperation]:
    if provider.get("enabled") is not True:
        return [_operation(prefix, recommendation, "no_op", operation_path(recommendation.provider_id, "provider_priority"), None, None, ["disabled provider cannot be promoted"], False)]
    if is_external_provider(provider) and not (provider.get("requires_approval") is True and provider.get("execution_mode") == "manual_handoff_only"):
        return [_operation(prefix, recommendation, "no_op", operation_path(recommendation.provider_id, "provider_priority"), None, None, ["external provider cannot be promoted without approval and manual handoff mode"], False)]
    return _priority_ops(prefix, recommendation, provider, priorities, direction="up")


def _priority_ops(
    prefix: str,
    recommendation: ProviderRoutingRecommendation,
    provider: dict,
    priorities: dict[str, list[str]],
    direction: str,
    reason: list[str] | None = None,
) -> list[RouterPatchOperation]:
    operations: list[RouterPatchOperation] = []
    provider_id = recommendation.provider_id
    for task_type, order in priorities.items():
        if provider_id not in order:
            continue
        current = list(order)
        idx = current.index(provider_id)
        if direction == "up":
            new_idx = max(0, idx - 1)
        else:
            new_idx = min(len(current) - 1, idx + 1)
        if new_idx == idx:
            operations.append(_operation(f"{prefix}_{task_type}", recommendation, "no_op", f"executor_router.provider_priority.{task_type}", current, current, ["provider priority already at boundary"], False))
            continue
        patched = list(current)
        patched.pop(idx)
        patched.insert(new_idx, provider_id)
        if not patched:
            operations.append(_operation(f"{prefix}_{task_type}", recommendation, "no_op", f"executor_router.provider_priority.{task_type}", current, current, ["blocked: provider priority cannot be emptied"], True))
            continue
        operations.append(
            _operation(
                f"{prefix}_{task_type}",
                recommendation,
                "adjust_priority",
                f"executor_router.provider_priority.{task_type}",
                current,
                patched,
                reason or recommendation.reason or [f"governance recommends priority {direction}"],
                True,
            )
        )
    if not operations:
        operations.append(_operation(prefix, recommendation, "no_op", operation_path(provider_id, "provider_priority"), None, None, ["provider not present in provider_priority"], False))
    return operations


def _note_op(
    prefix: str,
    recommendation: ProviderRoutingRecommendation,
    provider: dict,
    note: str,
    requires_approval: bool,
    operation_type: str = "add_watchlist_note",
) -> RouterPatchOperation:
    notes = [str(item) for item in provider.get("notes") or []]
    if note in notes:
        return _operation(prefix, recommendation, "no_op", operation_path(recommendation.provider_id, "notes"), notes, notes, ["governance note already present"], False)
    return _operation(prefix, recommendation, operation_type, operation_path(recommendation.provider_id, "notes"), notes, [*notes, note], recommendation.reason or [f"add governance note: {note}"], requires_approval)


def _operation(
    operation_id: str,
    recommendation: ProviderRoutingRecommendation,
    operation_type: str,
    target_path: str,
    old_value: object | None,
    new_value: object | None,
    reason: list[str],
    requires_approval: bool,
) -> RouterPatchOperation:
    return RouterPatchOperation(
        operation_id=operation_id,
        provider_id=recommendation.provider_id,
        operation_type=operation_type,
        target_path=target_path,
        old_value=old_value,
        new_value=new_value,
        reason=[str(item) for item in reason],
        source_recommendation=recommendation.recommendation,
        safety_level="approval_required" if requires_approval else "safe_noop",
        requires_approval=requires_approval,
    )
