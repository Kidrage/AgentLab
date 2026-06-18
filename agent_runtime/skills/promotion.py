"""S4 promotion eligibility gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


DEFAULT_PROMOTION_POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "skill_promotion_policy.yml"

DEFAULT_PROMOTION_POLICY: dict[str, Any] = {
    "schema_version": 1,
    "require_human_approval": True,
    "require_trust_pass": True,
    "require_permission_pass": True,
    "require_sandbox_pass": True,
}


def load_promotion_policy(path: Path | str | None = None) -> dict[str, Any]:
    policy_path = Path(path) if path is not None else DEFAULT_PROMOTION_POLICY_PATH
    policy = dict(DEFAULT_PROMOTION_POLICY)
    if policy_path.exists():
        data = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            policy.update(data)
    return policy


def build_promotion_eligibility(
    parsed_skill: dict[str, Any],
    trust_report: dict[str, Any],
    permission_report: dict[str, Any],
    sandbox_report: dict[str, Any],
    *,
    human_approval: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an active-dispatch eligibility report."""

    policy = policy or load_promotion_policy()
    approval_granted = bool((human_approval or {}).get("approved", False))
    blockers: list[str] = []
    if policy.get("require_trust_pass", True) and not trust_report.get("passed", False):
        blockers.append("trust_scan_failed")
    if policy.get("require_permission_pass", True) and not permission_report.get("passed", False):
        blockers.append("permission_validation_failed")
    if policy.get("require_sandbox_pass", True) and not sandbox_report.get("passed", False):
        blockers.append("mock_sandbox_failed")
    if policy.get("require_human_approval", True) and not approval_granted:
        blockers.append("human_approval_required")

    eligible = not blockers
    return {
        "schema_version": 1,
        "skill_id": parsed_skill.get("skill_id"),
        "promotion_eligible": eligible,
        "dispatch_eligible": eligible,
        "active_status_allowed": eligible,
        "human_approval": {
            "required": bool(policy.get("require_human_approval", True)),
            "approved": approval_granted,
        },
        "blockers": blockers,
        "next_action": "promote_or_dispatch_allowed" if eligible else "resolve_blockers_before_promotion",
    }
