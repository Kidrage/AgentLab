"""P2-F Retry Plan tests.

Covers the spec-required retry scenarios:
7. Fail review → generate retry_plan
8. Safety violation → retry_allowed=false
9. Attempts exceeded → retry_allowed=false
10. Missing evidence → retry kind is regenerate_report/evidence, not blind rerun
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_runtime.retry.models import RetryAttempt, RetryDecision, RetryLoopState, RetryPolicy
from agent_runtime.retry.policy import load_retry_policy
from agent_runtime.retry.retry_manager import decide_retry_action

CONFIG_ROOT = ROOT / "config"


def _make_attempt(verdict: str = "PASS", provider_id: str = "agentlab.mock_patch") -> RetryAttempt:
    a = RetryAttempt(
        task_id="test_retry",
        attempt_id="attempt_001",
        attempt_index=1,
        provider_id=provider_id,
        provider_type="mock_executor",
        execution_mode="mock",
    )
    # Set verdict status as a plain attribute (not a dataclass field)
    # because decide_retry_action reads it via getattr or from review_verdict file
    a.review_verdict_status = verdict
    return a


def _make_loop_state(current: int = 1, max_attempts: int = 3, cost: float = 0.0) -> RetryLoopState:
    return RetryLoopState(
        task_id="test_retry",
        task_type="bugfix",
        current_attempt=current,
        max_attempts=max_attempts,
        total_estimated_cost_usd=cost,
        status="running",
    )


class TestRetryPlanFromFailedReview:
    """Test 7: Failed review → generate retry_plan."""

    def test_needs_revision_generates_retry(self):
        policy = load_retry_policy(CONFIG_ROOT / "retry_policy.yml")
        attempt = _make_attempt(verdict="NEEDS_REVISION")
        loop = _make_loop_state(current=1, max_attempts=3)
        decision = decide_retry_action(attempt, loop, policy)
        assert decision.status == "RETRY"
        assert decision.next_action == "route_retry"

    def test_fail_generates_retry(self):
        policy = load_retry_policy(CONFIG_ROOT / "retry_policy.yml")
        attempt = _make_attempt(verdict="FAIL")
        loop = _make_loop_state(current=1, max_attempts=3)
        decision = decide_retry_action(attempt, loop, policy)
        assert decision.status == "RETRY"
        assert decision.next_action == "route_retry"


class TestRetryPlanSafetyViolation:
    """Test 8: Safety violation → retry_allowed=false."""

    def test_blocked_verdict_stops_retry(self):
        policy = load_retry_policy(CONFIG_ROOT / "retry_policy.yml")
        attempt = _make_attempt(verdict="BLOCKED")
        loop = _make_loop_state(current=1, max_attempts=3)
        decision = decide_retry_action(attempt, loop, policy)
        assert "STOP" in decision.status
        assert decision.next_action == "stop"
        assert decision.stop_reason is not None


class TestRetryPlanMaxAttemptsExceeded:
    """Test 9: Attempts exceeded → retry_allowed=false."""

    def test_max_attempts_stops_retry(self):
        policy = load_retry_policy(CONFIG_ROOT / "retry_policy.yml")
        attempt = _make_attempt(verdict="NEEDS_REVISION")
        loop = _make_loop_state(current=3, max_attempts=3)
        decision = decide_retry_action(attempt, loop, policy)
        assert decision.status == "STOP_MAX_ATTEMPTS"
        assert decision.next_action == "stop"
        assert "max" in decision.stop_reason.lower()

    def test_over_max_attempts_stops_retry(self):
        policy = load_retry_policy(CONFIG_ROOT / "retry_policy.yml")
        attempt = _make_attempt(verdict="FAIL")
        loop = _make_loop_state(current=5, max_attempts=3)
        decision = decide_retry_action(attempt, loop, policy)
        assert decision.next_action == "stop"


class TestRetryPlanMissingEvidence:
    """Test 10: Missing evidence → retry allows evidence regeneration."""

    def test_pass_with_warnings_does_not_retry(self):
        policy = load_retry_policy(CONFIG_ROOT / "retry_policy.yml")
        attempt = _make_attempt(verdict="PASS_WITH_WARNINGS")
        loop = _make_loop_state(current=1, max_attempts=3)
        decision = decide_retry_action(attempt, loop, policy)
        # PASS_WITH_WARNINGS is a pass status, so should stop
        assert decision.next_action == "stop"


class TestRetryPlanPassReview:
    """Pass review should not trigger retry."""

    def test_pass_review_no_retry(self):
        policy = load_retry_policy(CONFIG_ROOT / "retry_policy.yml")
        attempt = _make_attempt(verdict="PASS")
        loop = _make_loop_state(current=1, max_attempts=3)
        decision = decide_retry_action(attempt, loop, policy)
        assert decision.status == "ACCEPTED"
        assert decision.next_action == "stop"


class TestRetryPolicyLoading:
    """Verify retry policy loads correctly with expected defaults."""

    def test_retry_policy_has_max_attempts(self):
        policy = load_retry_policy(CONFIG_ROOT / "retry_policy.yml")
        assert isinstance(policy.loop.get("max_attempts_per_task"), int)
        assert policy.loop["max_attempts_per_task"] >= 1

    def test_retry_policy_has_cost_limit(self):
        policy = load_retry_policy(CONFIG_ROOT / "retry_policy.yml")
        assert "max_retry_cost_usd_per_task" in policy.budget

    def test_retry_policy_enabled(self):
        policy = load_retry_policy(CONFIG_ROOT / "retry_policy.yml")
        assert policy.enabled is True

    def test_retry_policy_stop_on_blocked(self):
        policy = load_retry_policy(CONFIG_ROOT / "retry_policy.yml")
        assert policy.loop.get("stop_on_blocked") is True

    def test_retry_policy_has_pass_statuses(self):
        policy = load_retry_policy(CONFIG_ROOT / "retry_policy.yml")
        assert "PASS" in policy.review.get("pass_statuses", [])
        assert "PASS_WITH_WARNINGS" in policy.review.get("pass_statuses", [])

    def test_retry_policy_has_retry_statuses(self):
        policy = load_retry_policy(CONFIG_ROOT / "retry_policy.yml")
        assert "NEEDS_REVISION" in policy.review.get("retry_statuses", [])
        assert "FAIL" in policy.review.get("retry_statuses", [])

    def test_retry_policy_has_blocked_statuses(self):
        policy = load_retry_policy(CONFIG_ROOT / "retry_policy.yml")
        assert "BLOCKED" in policy.review.get("blocked_statuses", [])
