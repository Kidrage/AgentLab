from __future__ import annotations

from pathlib import Path

from agent_runtime.retry import RetryAttempt, RetryLoopState, decide_retry_action, load_retry_policy


ROOT = Path(__file__).resolve().parents[1]


def _policy():
    return load_retry_policy(ROOT / "config" / "retry_policy.yml")


def _attempt(verdict: str | None = "NEEDS_REVISION", index: int = 1) -> RetryAttempt:
    attempt = RetryAttempt(
        task_id="task",
        attempt_id=f"attempt_{index:03d}",
        attempt_index=index,
        provider_id="agentlab.mock_patch",
        provider_type="mock_executor",
        execution_mode="mock",
        status="review_failed",
        failure_reasons=["MEDIUM tests: No claimed tests were found in the delivery evidence."],
    )
    setattr(attempt, "review_verdict_status", verdict)
    return attempt


def test_load_retry_policy():
    policy = _policy()
    assert policy.enabled is True
    assert policy.routing["allow_auto_external_retry"] is False


def test_retry_policy_max_attempts():
    assert _policy().loop["max_attempts_per_task"] == 3


def test_retry_policy_requires_review_each_attempt():
    assert _policy().review["require_p2_review_each_attempt"] is True


def test_decide_accept_on_pass():
    attempt = _attempt("PASS")
    state = RetryLoopState("task", "repo_patch", 1, 3, attempts=[attempt])
    assert decide_retry_action(attempt, state, _policy()).status == "ACCEPTED"


def test_decide_retry_on_needs_revision():
    attempt = _attempt("NEEDS_REVISION")
    state = RetryLoopState("task", "repo_patch", 1, 3, attempts=[attempt])
    assert decide_retry_action(attempt, state, _policy()).status == "RETRY"


def test_decide_stop_on_blocked():
    attempt = _attempt("BLOCKED")
    state = RetryLoopState("task", "repo_patch", 1, 3, attempts=[attempt])
    assert decide_retry_action(attempt, state, _policy()).status == "STOP_SAFETY_BLOCKED"


def test_decide_stop_on_max_attempts():
    attempt = _attempt("FAIL", 3)
    state = RetryLoopState("task", "repo_patch", 3, 3, attempts=[attempt])
    assert decide_retry_action(attempt, state, _policy()).status == "STOP_MAX_ATTEMPTS"


def test_decide_stop_on_budget():
    attempt = _attempt("FAIL")
    state = RetryLoopState("task", "repo_patch", 1, 3, total_estimated_cost_usd=1.0, attempts=[attempt])
    assert decide_retry_action(attempt, state, _policy()).status == "STOP_BUDGET"


def test_decide_escalate_on_repeated_same_failure():
    first = _attempt("FAIL", 1)
    first.failure_reasons = ["HIGH evidence: Required artifact is missing."]
    second = _attempt("FAIL", 2)
    second.failure_reasons = list(first.failure_reasons)
    state = RetryLoopState("task", "repo_patch", 2, 3, attempts=[first, second])
    assert decide_retry_action(second, state, _policy()).status == "ESCALATE_TO_HUMAN"
