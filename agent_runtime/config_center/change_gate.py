"""M3-4 Config Center — change gating for risky config modifications."""

from __future__ import annotations

from typing import Any

HIGH_RISK_KEY_PREFIXES = [
    "execution_policy.external_executor_enablement",
    "execution_policy.default_execution_mode",
    "ops_console_policy.public_bind_allowed",
    "ops_console_policy.bind_host",
    "budget_policy.max_task_cost_usd",
    "budget_policy.approval_threshold_usd",
    "evidence_integrity_policy.hard_fail_on",
]

DOUBLE_APPROVAL_KEYS = [
    "execution_policy.external_executor_enablement",
    "ops_console_policy.public_bind_allowed",
]


def gate_config_change(key: str, old_value: Any, new_value: Any) -> dict[str, Any]:
    """Evaluate whether a config change requires approval gates.

    Returns:
        {
            allowed: bool,
            requires_approval: bool,
            requires_double_approval: bool,
            risk_level: "low" | "high" | "critical",
            audit_event_type: str | None,
            reason: str,
        }
    """
    risk_level = _classify_risk(key)
    requires_approval = risk_level in ("high", "critical")
    requires_double = key in DOUBLE_APPROVAL_KEYS

    if old_value == new_value and new_value is not None:
        return {
            "allowed": True,
            "requires_approval": False,
            "requires_double_approval": False,
            "risk_level": "low",
            "audit_event_type": None,
            "reason": "no-change",
        }

    if risk_level == "critical":
        return {
            "allowed": False,
            "requires_approval": True,
            "requires_double_approval": requires_double,
            "risk_level": "critical",
            "audit_event_type": "config.critical_change_requested",
            "reason": f"critical config key '{key}' requires explicit policy + operator approval",
        }

    if risk_level == "high":
        return {
            "allowed": False,
            "requires_approval": True,
            "requires_double_approval": requires_double,
            "risk_level": "high",
            "audit_event_type": "config.risky_change_requested",
            "reason": f"high-risk config key '{key}' requires operator approval",
        }

    return {
        "allowed": True,
        "requires_approval": False,
        "requires_double_approval": False,
        "risk_level": "low",
        "audit_event_type": None,
        "reason": "low-risk change, auto-allowed",
    }


def _classify_risk(key: str) -> str:
    """Classify the risk level of a config key change."""
    for prefix in DOUBLE_APPROVAL_KEYS:
        if key.startswith(prefix):
            return "critical"
    for prefix in HIGH_RISK_KEY_PREFIXES:
        if key.startswith(prefix):
            return "high"
    return "low"


def is_external_execution_disabled_by_default(merged_config: dict[str, Any]) -> bool:
    """Verify external executor enablement is disabled (default safety)."""
    exec_policy = merged_config.get("execution_policy", {})
    if isinstance(exec_policy, dict):
        enabled = exec_policy.get("external_executor_enablement")
        if enabled is True:
            return False
    # also check ops_console_policy
    ops_policy = merged_config.get("ops_console_policy", {})
    if isinstance(ops_policy, dict):
        public_bind = ops_policy.get("public_bind_allowed")
        if public_bind is True:
            return False
    return True
