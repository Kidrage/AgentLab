from __future__ import annotations

from pathlib import Path

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.router_update.models import RouterPolicyPatch, RouterRollbackPlan, to_plain_data


def create_router_rollback_plan(
    original_router_policy: dict,
    patched_router_policy: dict,
    patch: RouterPolicyPatch,
    output_dir: Path,
) -> RouterRollbackPlan:
    affected_providers = sorted({op.provider_id for op in patch.operations if op.operation_type != "no_op"})
    affected_task_types = sorted(
        {
            op.target_path.rsplit(".", 1)[-1]
            for op in patch.operations
            if op.target_path.startswith("executor_router.provider_priority.") and op.operation_type != "no_op"
        }
    )
    plan = RouterRollbackPlan(
        patch_id=patch.patch_id,
        restore_method="Replace the patched copy with original_router_policy from rollback_plan.yml, or reapply listed original values manually.",
        affected_providers=affected_providers,
        affected_task_types=affected_task_types,
        operations=[
            {
                "operation_id": op.operation_id,
                "target_path": op.target_path,
                "restore_value": op.old_value,
                "patched_value": op.new_value,
            }
            for op in patch.operations
            if op.operation_type != "no_op"
        ],
        original_router_policy=original_router_policy,
        patched_router_policy=patched_router_policy,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(output_dir / "rollback_plan.yml", to_plain_data(plan))
    atomic_write_text(output_dir / "rollback_plan.md", _rollback_markdown(plan))
    return plan


def _rollback_markdown(plan: RouterRollbackPlan) -> str:
    lines = [
        "# Router Patch Rollback Plan",
        "",
        f"- Patch ID: {plan.patch_id}",
        f"- Restore Method: {plan.restore_method}",
        "",
        "## Affected Providers",
    ]
    lines.extend(f"- {item}" for item in plan.affected_providers)
    if not plan.affected_providers:
        lines.append("- None")
    lines.extend(["", "## Affected Task Types"])
    lines.extend(f"- {item}" for item in plan.affected_task_types)
    if not plan.affected_task_types:
        lines.append("- None")
    lines.extend(["", "## Restore Operations"])
    for op in plan.operations:
        lines.append(f"- {op['operation_id']}: restore {op['target_path']} to {op['restore_value']}")
    if not plan.operations:
        lines.append("- None")
    return "\n".join(lines) + "\n"
