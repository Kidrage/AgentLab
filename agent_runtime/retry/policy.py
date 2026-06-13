from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_runtime.retry.models import RetryPolicy


DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "retry_policy.yml"


DEFAULT_RETRY_POLICY: dict[str, Any] = {
    "enabled": True,
    "loop": {
        "max_attempts_per_task": 3,
        "stop_on_blocked": True,
        "stop_on_critical_safety_finding": True,
        "stop_on_repeated_same_failure": True,
        "repeated_failure_window": 2,
    },
    "budget": {
        "max_retry_cost_usd_per_task": 0.50,
        "warn_retry_cost_usd_per_task": 0.20,
        "unknown_cost_requires_approval": True,
    },
    "routing": {
        "allow_same_provider_retry": True,
        "prefer_different_provider_after_failure": True,
        "require_approval_for_external_retry": True,
        "allow_mock_retry": True,
        "allow_manual_handoff_retry": True,
        "allow_auto_external_retry": False,
    },
    "review": {
        "require_p2_review_each_attempt": True,
        "pass_statuses": ["PASS", "PASS_WITH_WARNINGS"],
        "retry_statuses": ["NEEDS_REVISION", "FAIL"],
        "blocked_statuses": ["BLOCKED"],
    },
    "scorecard": {
        "enabled": True,
        "quality_score_pass": 1.0,
        "quality_score_pass_with_warnings": 0.75,
        "quality_score_needs_revision": 0.35,
        "quality_score_fail": 0.1,
        "quality_score_blocked": 0.0,
    },
    "artifacts": {
        "write_retry_loop_report": True,
        "write_attempt_ledger": True,
        "write_provider_scorecard": True,
        "write_final_acceptance_receipt": True,
    },
}


def load_retry_policy(path: Path | None = None) -> RetryPolicy:
    policy_path = path or DEFAULT_POLICY_PATH
    data = yaml.safe_load(policy_path.read_text(encoding="utf-8")) if policy_path.exists() else {}
    raw = data.get("retry_policy", data) if isinstance(data, dict) else {}
    merged = _deep_merge(DEFAULT_RETRY_POLICY, raw if isinstance(raw, dict) else {})
    return RetryPolicy(
        enabled=merged.get("enabled", True) is True,
        loop=dict(merged.get("loop") or {}),
        budget=dict(merged.get("budget") or {}),
        routing=dict(merged.get("routing") or {}),
        review=dict(merged.get("review") or {}),
        scorecard=dict(merged.get("scorecard") or {}),
        artifacts=dict(merged.get("artifacts") or {}),
    )


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {key: value.copy() if isinstance(value, dict) else value for key, value in base.items()}
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
