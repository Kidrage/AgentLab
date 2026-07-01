"""M3-5 Cost System v2 — budget alerts."""

from __future__ import annotations

from typing import Any


def check_budget_alerts(
    total_cost_usd: float,
    total_tokens: int,
    policy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Check budget thresholds and generate alerts.

    Args:
        total_cost_usd: current total estimated cost
        total_tokens: current total token usage
        policy: budget policy dict (from load_budget_policy)

    Returns:
        list of alert dicts: [{level, message, threshold, current, pct_of_threshold}]
    """
    if policy is None:
        policy = _default_policy()

    alerts: list[dict[str, Any]] = []
    max_cost = float(policy.get("max_task_cost_usd", 0.20))
    approval_threshold = float(policy.get("approval_threshold_usd", 0.10))
    max_tokens = int(policy.get("max_task_tokens", 200_000))

    # check max cost
    if max_cost > 0:
        pct = round(total_cost_usd / max_cost * 100, 1)
        if total_cost_usd >= max_cost:
            alerts.append({
                "level": "critical",
                "message": f"Task cost ${total_cost_usd:.4f} exceeds max ${max_cost:.2f}",
                "threshold": max_cost,
                "current": total_cost_usd,
                "pct_of_threshold": pct,
            })
        elif total_cost_usd >= max_cost * 0.8:
            alerts.append({
                "level": "warning",
                "message": f"Task cost ${total_cost_usd:.4f} approaching max ${max_cost:.2f}",
                "threshold": max_cost,
                "current": total_cost_usd,
                "pct_of_threshold": pct,
            })

    # check approval threshold
    if approval_threshold > 0 and total_cost_usd >= approval_threshold:
        alerts.append({
            "level": "info",
            "message": f"Task cost ${total_cost_usd:.4f} exceeds approval threshold ${approval_threshold:.2f}",
            "threshold": approval_threshold,
            "current": total_cost_usd,
            "pct_of_threshold": round(total_cost_usd / approval_threshold * 100, 1),
        })

    # check token limit
    if max_tokens > 0:
        pct_tokens = round(total_tokens / max_tokens * 100, 1)
        if total_tokens >= max_tokens:
            alerts.append({
                "level": "critical",
                "message": f"Token usage {total_tokens} exceeds max {max_tokens}",
                "threshold": max_tokens,
                "current": total_tokens,
                "pct_of_threshold": pct_tokens,
            })
        elif total_tokens >= max_tokens * 0.8:
            alerts.append({
                "level": "warning",
                "message": f"Token usage {total_tokens} approaching max {max_tokens}",
                "threshold": max_tokens,
                "current": total_tokens,
                "pct_of_threshold": pct_tokens,
            })

    return alerts


def _default_policy() -> dict[str, Any]:
    return {
        "max_task_cost_usd": 0.20,
        "approval_threshold_usd": 0.10,
        "max_task_tokens": 200_000,
    }
