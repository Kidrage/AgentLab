from __future__ import annotations

from pathlib import Path

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.router_update.models import RouterPatchApproval, RouterPatchApprovalRequest, RouterPolicyPatch, RouterUpdatePolicy, to_plain_data


def create_router_patch_approval_request(
    patch: RouterPolicyPatch,
    update_policy: RouterUpdatePolicy,
    output_dir: Path,
) -> RouterPatchApprovalRequest:
    approval = update_policy.approval
    request = RouterPatchApprovalRequest(
        patch_id=patch.patch_id,
        required=patch.requires_human_approval,
        reason=["router policy patch changes require human approval"] if patch.requires_human_approval else ["patch contains no policy-changing operations"],
        approval_method=str(approval.get("method") or "file_token"),
        approval_token_hint=f"{approval.get('token_file_name', 'APPROVE_ROUTER_PATCH')}={approval.get('token_value', 'APPROVED')}",
        allowed_apply_targets=["copy"] + (["production"] if update_policy.safety.get("allow_apply_to_production") is True else []),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(output_dir / "approval_request.yml", to_plain_data(request))
    atomic_write_text(output_dir / "approval_request.md", _approval_markdown(request, patch, update_policy))
    return request


def load_router_patch_approval(patch: RouterPolicyPatch, update_policy: RouterUpdatePolicy, approval_dir: Path) -> RouterPatchApproval:
    token_file = approval_dir / str(update_policy.approval.get("token_file_name") or "APPROVE_ROUTER_PATCH")
    expected = str(update_policy.approval.get("token_value") or "APPROVED")
    if not token_file.exists():
        return RouterPatchApproval(patch.patch_id, False, reason=["approval token file missing"])
    content = token_file.read_text(encoding="utf-8").strip()
    if content != expected:
        return RouterPatchApproval(patch.patch_id, False, reason=["approval token content mismatch"])
    return RouterPatchApproval(patch.patch_id, True, reason=["approval token accepted"])


def _approval_markdown(request: RouterPatchApprovalRequest, patch: RouterPolicyPatch, update_policy: RouterUpdatePolicy) -> str:
    token_name = update_policy.approval.get("token_file_name", "APPROVE_ROUTER_PATCH")
    token_value = update_policy.approval.get("token_value", "APPROVED")
    lines = [
        "# Router Patch Approval Request",
        "",
        "## Patch ID",
        request.patch_id,
        "",
        "## Why Approval Is Required",
    ]
    lines.extend(f"- {reason}" for reason in request.reason)
    lines.extend(["", "## Operations Requiring Approval"])
    approving = [op for op in patch.operations if op.requires_approval and op.operation_type != "no_op"]
    lines.extend(f"- {op.operation_id}: {op.operation_type} {op.target_path}" for op in approving)
    if not approving:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Safety Constraints",
            "- Production router config is not modified by staging.",
            "- Disabled external providers cannot be enabled.",
            "- Auto execution cannot be enabled.",
            "- Rollback plan is required before apply.",
            "",
            "## How To Approve",
            f"Create a file named {token_name} containing {token_value} in the output directory.",
            "",
            "## Allowed Apply Targets",
        ]
    )
    lines.extend(f"- {target}" for target in request.allowed_apply_targets)
    return "\n".join(lines) + "\n"
