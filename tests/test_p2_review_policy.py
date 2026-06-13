from __future__ import annotations

from pathlib import Path

from agent_runtime.review import load_review_policy


ROOT = Path(__file__).resolve().parents[1]


def test_review_policy_loads_required_rules() -> None:
    policy = load_review_policy(ROOT / "config" / "review_policy.yml")
    assert policy.enabled is True
    assert policy.verdict_thresholds["critical_finding"] == "BLOCKED"
    assert "external_handoff.md" in policy.required_artifacts
    assert "skill_usage_ledger.yml" in policy.required_artifacts
    assert policy.safety_checks["forbid_remote_clone"] is True
    assert ".env" in policy.forbidden_paths
    assert "agent_runtime/" in policy.high_risk_paths
    assert "Safety Evidence" in policy.required_report_sections
    assert policy.retry_handoff["enabled"] is True
