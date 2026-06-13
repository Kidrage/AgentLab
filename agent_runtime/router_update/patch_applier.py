from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.router_update.approval import load_router_patch_approval
from agent_runtime.router_update.ledger import record_router_update_event
from agent_runtime.router_update.models import RouterPatchOperation, RouterPatchResult, RouterPolicyPatch, to_plain_data
from agent_runtime.router_update.policy import is_external_provider, provider_priority, providers_by_id, router_root
from agent_runtime.router_update.recommendation_loader import load_router_policy, load_router_update_policy
from agent_runtime.router_update.rollback import create_router_rollback_plan


def apply_router_policy_patch(
    router_policy_path: Path,
    patch_path: Path,
    update_policy_path: Path,
    output_path: Path,
    approval_dir: Path,
) -> RouterPatchResult:
    output_dir = output_path.parent
    ledger_path = output_dir / "router_update_ledger.yml"
    update_policy = load_router_update_policy(update_policy_path)
    original = load_router_policy(router_policy_path)
    patch = _load_patch(patch_path)
    if output_path.resolve() == router_policy_path.resolve() and update_policy.safety.get("allow_apply_to_production") is not True:
        result = _result(patch.patch_id, False, None, "BLOCKED", ["production router overwrite blocked by policy"])
        _write_result(output_dir, result)
        record_router_update_event(ledger_path, "patch_blocked", patch.patch_id, result.status, result.reasons, [output_dir / "patch_result.yml"])
        return result
    if patch.requires_human_approval:
        approval = load_router_patch_approval(patch, update_policy, approval_dir)
        if not approval.approved:
            result = _result(patch.patch_id, False, None, "APPROVAL_REQUIRED", approval.reason)
            _write_result(output_dir, result)
            record_router_update_event(ledger_path, "approval_missing", patch.patch_id, result.status, result.reasons, [output_dir / "patch_result.yml"])
            return result
        record_router_update_event(ledger_path, "approval_granted", patch.patch_id, "APPROVED", approval.reason, [])
    patched = apply_operations_to_policy(original, patch.operations)
    errors = validate_router_policy(patched, original)
    if errors:
        result = _result(patch.patch_id, False, None, "VALIDATION_FAILED", errors)
        _write_result(output_dir, result)
        record_router_update_event(ledger_path, "validation_failed", patch.patch_id, result.status, result.reasons, [output_dir / "patch_result.yml"])
        return result
    rollback = create_router_rollback_plan(original, patched, patch, output_dir)
    record_router_update_event(ledger_path, "rollback_plan_created", patch.patch_id, "CREATED", ["rollback plan generated"], [output_dir / "rollback_plan.yml", output_dir / "rollback_plan.md"])
    atomic_write_yaml(output_path, patched)
    status = "APPLIED_TO_TARGET" if output_path.resolve() == router_policy_path.resolve() else "APPLIED_TO_COPY"
    result = RouterPatchResult(
        patch_id=patch.patch_id,
        applied=True,
        applied_to=str(output_path),
        status=status,
        operations_applied=len([op for op in patch.operations if op.operation_type != "no_op"]),
        rollback_plan_path=str(output_dir / "rollback_plan.yml"),
        reasons=["router patch applied to copy" if status == "APPLIED_TO_COPY" else "router patch applied to allowed target"],
    )
    _write_result(output_dir, result)
    record_router_update_event(ledger_path, "patch_applied_to_copy" if status == "APPLIED_TO_COPY" else "patch_applied_to_target", patch.patch_id, result.status, result.reasons, [output_path, output_dir / "patch_result.yml"])
    return result


def apply_operations_to_policy(router_policy: dict, operations: list[RouterPatchOperation]) -> dict:
    patched = deepcopy(router_policy)
    root = router_root(patched)
    providers = providers_by_id(patched)
    priorities = root.setdefault("provider_priority", {})
    for op in operations:
        if op.operation_type == "no_op":
            continue
        provider = providers.get(op.provider_id)
        if op.operation_type == "set_requires_approval" and provider is not None:
            provider["requires_approval"] = bool(op.new_value)
        elif op.operation_type == "set_enabled" and provider is not None:
            provider["enabled"] = bool(op.new_value)
        elif op.operation_type == "set_execution_mode" and provider is not None:
            provider["execution_mode"] = str(op.new_value)
        elif op.operation_type in {"add_watchlist_note", "add_quarantine_note"} and provider is not None:
            provider["notes"] = [str(item) for item in op.new_value or []]
        elif op.operation_type == "adjust_priority":
            task_type = op.target_path.rsplit(".", 1)[-1]
            priorities[task_type] = [str(item) for item in op.new_value or []]
    return patched


def validate_router_policy(policy: dict, original_policy: dict | None = None) -> list[str]:
    errors: list[str] = []
    root = router_root(policy)
    if not root:
        return ["missing executor_router policy"]
    providers = root.get("providers") or []
    provider_ids = [str(item.get("provider_id")) for item in providers if isinstance(item, dict)]
    if len(provider_ids) != len(set(provider_ids)):
        errors.append("provider_id values must be unique")
    priorities = provider_priority(policy)
    if not priorities:
        errors.append("provider_priority must not be empty")
    for task_type, order in priorities.items():
        if not order:
            errors.append(f"provider_priority for {task_type} must not be empty")
    routing = root.get("routing") or {}
    if routing.get("allow_auto_execution") is True:
        errors.append("auto execution must not be enabled")
    safety = root.get("safety") or {}
    if original_policy is not None:
        original_safety = router_root(original_policy).get("safety") or {}
        for key, value in original_safety.items():
            if key not in safety or safety.get(key) != value:
                errors.append(f"safety policy removed or changed: {key}")
        original_providers = providers_by_id(original_policy)
        current_providers = providers_by_id(policy)
        for provider_id, original_provider in original_providers.items():
            current = current_providers.get(provider_id)
            if not current:
                continue
            if is_external_provider(original_provider) and original_provider.get("enabled") is not True and current.get("enabled") is True:
                errors.append(f"disabled external provider enabled: {provider_id}")
            if original_provider.get("supports_auto_execution") is not True and current.get("supports_auto_execution") is True:
                errors.append(f"auto execution support enabled: {provider_id}")
            if original_provider.get("execution_mode") != "approved_auto" and current.get("execution_mode") == "approved_auto":
                errors.append(f"approved auto execution enabled: {provider_id}")
    else:
        for provider in providers:
            if isinstance(provider, dict) and is_external_provider(provider) and provider.get("enabled") is True and provider.get("execution_mode") == "approved_auto":
                errors.append(f"external provider has approved auto execution: {provider.get('provider_id')}")
    return errors


def _load_patch(path: Path) -> RouterPolicyPatch:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    ops = [
        RouterPatchOperation(
            operation_id=str(item.get("operation_id") or ""),
            provider_id=str(item.get("provider_id") or ""),
            operation_type=str(item.get("operation_type") or "no_op"),
            target_path=str(item.get("target_path") or ""),
            old_value=item.get("old_value"),
            new_value=item.get("new_value"),
            reason=[str(reason) for reason in item.get("reason") or []],
            source_recommendation=str(item.get("source_recommendation") or ""),
            safety_level=str(item.get("safety_level") or "approval_required"),
            requires_approval=item.get("requires_approval") is True,
        )
        for item in data.get("operations") or []
        if isinstance(item, dict)
    ]
    return RouterPolicyPatch(
        patch_id=str(data.get("patch_id") or "router_patch"),
        source_recommendations_path=str(data.get("source_recommendations_path") or ""),
        router_policy_path=str(data.get("router_policy_path") or ""),
        operations=ops,
        apply_automatically=False,
        requires_human_approval=data.get("requires_human_approval") is True,
        created_at=data.get("created_at"),
        warnings=[str(item) for item in data.get("warnings") or []],
    )


def _result(patch_id: str, applied: bool, applied_to: str | None, status: str, reasons: list[str]) -> RouterPatchResult:
    return RouterPatchResult(patch_id=patch_id, applied=applied, applied_to=applied_to, status=status, operations_applied=0, rollback_plan_path=None, reasons=reasons)


def _write_result(output_dir: Path, result: RouterPatchResult) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(output_dir / "patch_result.yml", to_plain_data(result))
