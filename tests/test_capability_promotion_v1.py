from __future__ import annotations

from copy import deepcopy

from agent_runtime.capability_promotion import (
    evaluate_capability_promotion,
    evaluate_capability_rollback,
)


def _manifest(*, risky: bool = False) -> dict:
    return {
        "schema_version": "capability-package/v1",
        "package_id": "example.reader",
        "package_type": "skill",
        "version": "1.2.0",
        "source": {
            "uri": "https://example.invalid/repository",
            "revision": "abc123",
            "digest": "a" * 64,
            "license": "MIT",
        },
        "capability_tags": ["read"],
        "compatible_environments": ["darwin"],
        "inputs": {"schema": "input/v1"},
        "outputs": {"schema": "output/v1"},
        "dependencies": [],
        "permissions": {
            "filesystem_write": "none",
            "shell": "none",
            "credentials": ["TOKEN"] if risky else [],
        },
        "network_boundary": {"mode": "https" if risky else "none"},
        "data_boundary": {"external_transfer": risky},
        "installation": {"executes_code": risky, "method": "none"},
        "health_probe": {"command": ["/usr/bin/true"]},
        "tests": ["fixture-suite"],
        "risks": [],
        "rollback_version": "1.1.0",
        "project_allowlist": ["Crown_of_Ash"],
    }


def _bound(schema: str, status: str = "pass") -> dict:
    return {
        "schema_version": schema,
        "status": status,
        "package_id": "example.reader",
        "version": "1.2.0",
        "source_digest": "a" * 64,
    }


def _fixtures() -> list[dict]:
    return [
        {
            "domain": domain,
            "status": "pass",
            "security_contract": "pass",
            "baseline_delta": 0.0,
        }
        for domain in ("safety", "code", "agents", "narrative", "research")
    ]


def test_low_risk_candidate_can_enter_canary_after_evidence_review() -> None:
    result = evaluate_capability_promotion(
        _manifest(),
        current_status="supervisor_reviewed",
        target_status="canary",
        static_audit=_bound("capability-static-audit/v1"),
        audition=_bound("capability-audition/v1"),
        supervisor_review=_bound("capability-supervisor-review/v1"),
        fixture_results=_fixtures(),
    )

    assert result["status"] == "approved"
    assert result["transition"] == {
        "from": "supervisor_reviewed",
        "to": "canary",
    }
    assert result["approval"]["user_approval_required"] is False
    assert result["fixture_summary"]["non_regressing_count"] == 5


def test_high_risk_candidate_requires_explicit_user_approval() -> None:
    result = evaluate_capability_promotion(
        _manifest(risky=True),
        current_status="supervisor_reviewed",
        target_status="canary",
        static_audit=_bound("capability-static-audit/v1"),
        audition=_bound("capability-audition/v1"),
        supervisor_review=_bound("capability-supervisor-review/v1"),
        fixture_results=_fixtures(),
    )

    assert result["status"] == "blocked"
    assert result["blocking_findings"] == ["user_approval_required"]

    approved = evaluate_capability_promotion(
        _manifest(risky=True),
        current_status="supervisor_reviewed",
        target_status="canary",
        static_audit=_bound("capability-static-audit/v1"),
        audition=_bound("capability-audition/v1"),
        supervisor_review=_bound("capability-supervisor-review/v1"),
        fixture_results=_fixtures(),
        user_approval_receipt={
            "schema_version": "capability-user-approval/v1",
            "package_id": "example.reader",
            "version": "1.2.0",
            "source_digest": "a" * 64,
            "approved": True,
        },
    )
    assert approved["status"] == "approved"


def test_promotion_blocks_regression_bad_security_and_digest_substitution() -> None:
    fixtures = _fixtures()
    fixtures[0]["security_contract"] = "fail"
    fixtures[1]["baseline_delta"] = -0.1
    fixtures[2]["baseline_delta"] = -0.1
    audition = _bound("capability-audition/v1")
    audition["source_digest"] = "b" * 64

    result = evaluate_capability_promotion(
        _manifest(),
        current_status="supervisor_reviewed",
        target_status="canary",
        static_audit=_bound("capability-static-audit/v1"),
        audition=audition,
        supervisor_review=_bound("capability-supervisor-review/v1"),
        fixture_results=fixtures,
    )

    assert result["status"] == "blocked"
    assert "audition:source_digest_mismatch" in result["blocking_findings"]
    assert "fixture_security_contract_failed:safety" in result["blocking_findings"]
    assert "fixture_non_regressing_below_four" in result["blocking_findings"]


def test_active_requires_healthy_hash_bound_canary() -> None:
    health = _bound("capability-canary-health/v1")
    result = evaluate_capability_promotion(
        _manifest(),
        current_status="canary",
        target_status="active",
        static_audit=_bound("capability-static-audit/v1"),
        audition=_bound("capability-audition/v1"),
        supervisor_review=_bound("capability-supervisor-review/v1"),
        fixture_results=_fixtures(),
        canary_health=health,
    )
    assert result["status"] == "approved"

    stale = deepcopy(health)
    stale["source_digest"] = "f" * 64
    blocked = evaluate_capability_promotion(
        _manifest(),
        current_status="canary",
        target_status="active",
        static_audit=_bound("capability-static-audit/v1"),
        audition=_bound("capability-audition/v1"),
        supervisor_review=_bound("capability-supervisor-review/v1"),
        fixture_results=_fixtures(),
        canary_health=stale,
    )
    assert blocked["status"] == "blocked"
    assert "canary_health:source_digest_mismatch" in blocked["blocking_findings"]


def test_health_failure_or_source_drift_rolls_back_to_declared_version() -> None:
    failed = evaluate_capability_rollback(
        _manifest(),
        current_status="active",
        health_receipt=_bound("capability-health/v1", status="failed"),
    )
    assert failed["status"] == "approved"
    assert failed["rollback"]["from_version"] == "1.2.0"
    assert failed["rollback"]["to_version"] == "1.1.0"
    assert failed["trigger"] == "health_failure"

    drifted_health = _bound("capability-health/v1")
    drifted_health["source_digest"] = "c" * 64
    drifted = evaluate_capability_rollback(
        _manifest(),
        current_status="canary",
        health_receipt=drifted_health,
    )
    assert drifted["status"] == "approved"
    assert drifted["trigger"] == "source_digest_drift"


def test_rollback_refuses_healthy_unchanged_or_non_deployed_package() -> None:
    healthy = evaluate_capability_rollback(
        _manifest(),
        current_status="active",
        health_receipt=_bound("capability-health/v1"),
    )
    assert healthy["status"] == "blocked"
    assert healthy["blocking_findings"] == ["rollback_trigger_not_present"]

    undiscovered = evaluate_capability_rollback(
        _manifest(),
        current_status="discovered",
        health_receipt=_bound("capability-health/v1", status="failed"),
    )
    assert undiscovered["status"] == "blocked"
    assert "rollback_requires_canary_or_active" in undiscovered["blocking_findings"]
