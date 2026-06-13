from __future__ import annotations

from pathlib import Path

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.router_update.models import RouterPolicyPatch, to_plain_data
from agent_runtime.router_update.policy import provider_priority


def write_router_patch_artifacts(output_dir: Path, patch: RouterPolicyPatch, router_policy: dict) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "patch_yml": output_dir / "router_policy_patch.yml",
        "patch_md": output_dir / "router_policy_patch.md",
        "diff_md": output_dir / "router_policy_diff.md",
    }
    atomic_write_yaml(paths["patch_yml"], to_plain_data(patch))
    atomic_write_text(paths["patch_md"], render_router_policy_patch_markdown(patch))
    atomic_write_text(paths["diff_md"], render_router_policy_diff(router_policy, patch))
    return paths


def render_router_policy_patch_markdown(patch: RouterPolicyPatch) -> str:
    lines = [
        "# Router Policy Patch",
        "",
        f"- Patch ID: {patch.patch_id}",
        f"- Apply Automatically: {patch.apply_automatically}",
        f"- Requires Human Approval: {patch.requires_human_approval}",
        "",
        "## Operations",
    ]
    for op in patch.operations:
        lines.append(f"- {op.operation_id}: {op.operation_type} {op.target_path} ({'; '.join(op.reason)})")
    if patch.warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in patch.warnings)
    return "\n".join(lines) + "\n"


def render_router_policy_diff(router_policy: dict, patch: RouterPolicyPatch) -> str:
    priority_ops = [op for op in patch.operations if op.operation_type == "adjust_priority"]
    field_ops = [op for op in patch.operations if op.operation_type in {"set_requires_approval", "set_enabled", "set_execution_mode", "add_watchlist_note", "add_quarantine_note"}]
    blocked_ops = [op for op in patch.operations if op.operation_type == "no_op" and any("blocked" in reason.lower() or "cannot" in reason.lower() for reason in op.reason)]
    lines = [
        "# Router Policy Patch Diff",
        "",
        "## Summary",
        f"- operations: {len(patch.operations)}",
        f"- priority changes: {len(priority_ops)}",
        f"- provider field changes: {len(field_ops)}",
        f"- provider priority task types currently configured: {len(provider_priority(router_policy))}",
        "",
        "## Operations",
    ]
    for op in patch.operations:
        lines.append(f"- {op.operation_id}: {op.operation_type} for {op.provider_id}; approval={op.requires_approval}")
    lines.extend(["", "## Provider Priority Changes"])
    if priority_ops:
        for op in priority_ops:
            lines.append(f"- {op.target_path}: {op.old_value} -> {op.new_value}")
    else:
        lines.append("- None")
    lines.extend(["", "## Provider Field Changes"])
    if field_ops:
        for op in field_ops:
            lines.append(f"- {op.target_path}: {op.old_value} -> {op.new_value}")
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Safety Invariants",
            "- production router policy not modified",
            "- human approval required",
            "- rollback plan generated",
            "- auto execution not enabled",
            "- disabled external providers not enabled",
            "- safety constraints retained",
            "",
            "## Blocked Operations",
        ]
    )
    if blocked_ops:
        for op in blocked_ops:
            lines.append(f"- {op.operation_id}: {'; '.join(op.reason)}")
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"
