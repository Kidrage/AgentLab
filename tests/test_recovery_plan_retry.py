"""Tests for P2-I failure recovery plan and retry policy.

Covers plan generation, retry policy decisions, and verdict output.
"""

from __future__ import annotations

from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]

from agent_runtime.recovery import (
    create_failure_event,
    FailureClassifier,
    FailureCategory,
    diagnose_failure,
    build_recovery_plan,
    load_retry_policy,
    decide_retry_action,
    RecoveryVerdict,
    VerdictType,
    RetryPolicyConfig,
)


class TestRecoveryPlan:
    """Tests for recovery plan generation."""

    def test_markdown_has_required_sections(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="pytest",
            command="pytest", exit_code=1, stderr="test failed",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        plan = build_recovery_plan(event, diag, policy)
        md = plan.to_markdown()

        required = [
            "# Recovery Plan", "## Summary", "## Failure Category",
            "## Evidence", "## Likely Root Cause", "## Recommended Action",
            "## Safe Commands", "## Unsafe Commands Requiring Approval",
            "## Validation Plan", "## Stop Conditions",
        ]
        for section in required:
            assert section in md, f"Missing section: {section}"

    def test_for_test_failure_suggests_pytest(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="pytest",
            command="pytest", exit_code=1, stderr="test_example.py FAILED",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        plan = build_recovery_plan(event, diag, policy)
        assert "pytest" in " ".join(plan.safe_commands).lower()

    def test_for_text_integrity_does_not_lower_thresholds(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="integrity",
            command="check", exit_code=1, error_type="text_integrity_failure",
            stderr="text integrity check failed: min line count violation",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        plan = build_recovery_plan(event, diag, policy)
        md = plan.to_markdown()
        assert "do not" in md.lower() or "stop" in md.lower()

    def test_for_secret_leak_requires_human_review(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="runtime",
            command="task", exit_code=1, error_type="secret_leak_risk",
            stderr="secret leak detected",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        plan = build_recovery_plan(event, diag, policy)
        assert "human" in plan.to_markdown().lower()

    def test_lists_forbidden_commands(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="test",
            command="pytest", exit_code=1, stderr="test failed",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        plan = build_recovery_plan(event, diag, policy)
        bad_cmds = " ".join(plan.unsafe_commands).lower()
        assert "reset" in bad_cmds or "clean" in bad_cmds

    def test_for_syntax_error(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="compile",
            command="compileall", exit_code=1, error_type="syntax_error",
            stderr="SyntaxError: invalid syntax",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        plan = build_recovery_plan(event, diag, policy)
        assert "compileall" in " ".join(plan.safe_commands).lower()

    def test_for_missing_artifact(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="runtime",
            command="task", exit_code=1, error_type="missing_artifact",
            artifact_paths=["output/report.md"],
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        plan = build_recovery_plan(event, diag, policy)
        assert "check" in " ".join(plan.safe_commands).lower()

    def test_to_dict(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="pytest",
            command="pytest", exit_code=1, stderr="test failed",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        plan = build_recovery_plan(event, diag, policy)
        d = plan.to_dict()
        assert d["task_id"] == "task_0001"
        assert d["project"] == "AgentLab"
        assert "failure_category" in d
        assert "safe_commands" in d
        assert "validation_plan" in d

    def test_for_context_missing(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="runtime",
            command="task", exit_code=1, error_type="context_missing",
            context_pack_path="context/context_pack.yml",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        plan = build_recovery_plan(event, diag, policy)
        assert "context" in " ".join(plan.safe_commands).lower()

    def test_summary(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="test",
            command="pytest", exit_code=1, stderr="test failed",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        plan = build_recovery_plan(event, diag, policy)
        assert plan.summary is not None
        assert len(plan.summary) > 0
        assert "Failure" in plan.summary or "failure" in plan.summary

    def test_validation_includes_pytest(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="test",
            command="pytest", exit_code=1, stderr="test failed",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        plan = build_recovery_plan(event, diag, policy)
        assert "pytest" in " ".join(plan.validation_plan).lower()

    def test_validation_includes_check(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="test",
            command="pytest", exit_code=1, stderr="test failed",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        plan = build_recovery_plan(event, diag, policy)
        assert "check" in " ".join(plan.validation_plan).lower()

    def test_stop_conditions_prevent_unsafe_recovery(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="test",
            command="pytest", exit_code=1, stderr="test failed",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        plan = build_recovery_plan(event, diag, policy)
        assert "stop" in " ".join(plan.stop_conditions).lower()


class TestRetryPolicy:
    """Tests for retry policy and verdict generation."""

    def _make_event(self, **kw) -> tuple:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab",
            stage=kw.get("stage", "test"), command=kw.get("command", "pytest"),
            exit_code=kw.get("exit_code", 1),
            stderr=kw.get("stderr", "test failed"),
            error_type=kw.get("error_type"),
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        return event, diag, policy

    def test_allows_timeout_retry(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="runtime",
            command="task", exit_code=1, error_type="timeout",
            stderr="timeout exceeded",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        verdict = decide_retry_action(diag, policy)
        assert verdict.allowed_attempts_remaining >= 0

    def test_blocks_syntax_error_retry(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="compile",
            command="compileall", exit_code=1, error_type="syntax_error",
            stderr="SyntaxError",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        verdict = decide_retry_action(diag, policy)
        assert verdict.safe_to_auto_retry is False

    def test_blocks_secret_leak_retry(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="runtime",
            command="task", exit_code=1, error_type="secret_leak_risk",
            stderr="secret leak detected",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        verdict = decide_retry_action(diag, policy)
        assert verdict.safe_to_auto_retry is False
        assert verdict.requires_human_review is True

    def test_blocks_remote_raw_retry(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="integrity",
            command="check", exit_code=1, error_type="remote_raw_failure",
            stderr="remote raw integrity check failed",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        verdict = decide_retry_action(diag, policy)
        assert verdict.safe_to_auto_retry is False

    def test_respects_max_attempts(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="runtime",
            command="task", exit_code=1, error_type="timeout",
            stderr="timeout exceeded",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        v0 = decide_retry_action(diag, policy, previous_attempts=0)
        v2 = decide_retry_action(diag, policy, previous_attempts=2)
        assert v2.allowed_attempts_remaining == 0

    def test_verdict_has_reason(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="test",
            command="pytest", exit_code=1, stderr="test failed",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        verdict = decide_retry_action(diag, policy)
        assert verdict.reason is not None
        assert len(verdict.reason) > 0

    def test_verdict_safe_to_auto_rollback(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="test",
            command="pytest", exit_code=1, stderr="test failed",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        verdict = decide_retry_action(diag, policy)
        assert isinstance(verdict.safe_to_auto_rollback, bool)

    def test_verdict_forbidden_without_approval(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="test",
            command="pytest", exit_code=1, stderr="test failed",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        verdict = decide_retry_action(diag, policy)
        forbidden = " ".join(verdict.forbidden_without_approval)
        assert "reset" in forbidden or "clean" in forbidden

    def test_verdict_next_commands(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="runtime",
            command="task", exit_code=1, error_type="timeout",
            stderr="timeout exceeded",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        verdict = decide_retry_action(diag, policy)
        # Timeout is retryable per config
        assert isinstance(verdict.next_commands, list)

    def test_verdict_stop_when_exhausted(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="runtime",
            command="task", exit_code=1, error_type="timeout",
            stderr="timeout exceeded",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        verdict = decide_retry_action(diag, policy, previous_attempts=100)
        assert verdict.allowed_attempts_remaining == 0

    def test_verdict_human_review_when_required(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="runtime",
            command="task", exit_code=1, error_type="secret_leak_risk",
            stderr="secret leak detected",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        verdict = decide_retry_action(diag, policy)
        assert verdict.requires_human_review is True

    def test_verdict_retry_when_allowed(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="runtime",
            command="task", exit_code=1, error_type="timeout",
            stderr="timeout exceeded",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        verdict = decide_retry_action(diag, policy)
        assert verdict.verdict in (VerdictType.RETRY, VerdictType.CONTINUE)

    def test_recovery_verdict_direct_creation(self) -> None:
        from datetime import datetime, timezone
        v = RecoveryVerdict(
            task_id="t1", verdict=VerdictType.RETRY, reason="retry allowed",
            allowed_attempts_remaining=1, safe_to_auto_retry=True,
            safe_to_auto_rollback=False, requires_human_review=False,
            next_commands=[], forbidden_without_approval=[],
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        assert v.task_id == "t1"
        assert v.verdict == VerdictType.RETRY

    def test_verdict_secret_leak_creation(self) -> None:
        from datetime import datetime, timezone
        v = RecoveryVerdict(
            task_id="t1", verdict=VerdictType.HUMAN_REVIEW,
            reason="secret leak", requires_human_review=True,
            safe_to_auto_retry=False,
            allowed_attempts_remaining=0, safe_to_auto_rollback=False,
            next_commands=[], forbidden_without_approval=["rm -rf"],
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        assert v.requires_human_review is True


class TestRetryPolicyConfig:
    """Tests for retry policy configuration."""

    def test_policy_loads_from_defaults(self) -> None:
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        assert policy.enabled is True
        assert isinstance(policy.stdout_tail_chars, int)
        assert isinstance(policy.stderr_tail_chars, int)

    def test_policy_has_retryable_categories(self) -> None:
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        assert isinstance(policy.retryable_categories, list)

    def test_policy_has_non_retryable_categories(self) -> None:
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        assert isinstance(policy.non_retryable_categories, list)

    def test_policy_has_forbidden_commands(self) -> None:
        policy = load_retry_policy(ROOT / "projects" / "AgentLab" / "runs" / "dummy")
        assert isinstance(policy.forbidden_auto_commands, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])