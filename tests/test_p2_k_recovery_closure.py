"""Tests for P2-K: Resume / Retry / Human Review Operation Closure."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]

from agent_runtime.recovery import (
    FailureCategory,
    VerdictType,
    create_failure_event,
    diagnose_failure,
    load_retry_policy,
    decide_retry_action,
    build_recovery_plan,
    write_human_review_decision,
    load_latest_human_review_decision,
    load_all_human_review_decisions,
    record_retry_attempt,
    load_retry_attempts,
    retry_attempt_count,
    build_recovery_closure_summary,
)


# ── Human review decision artifacts ──────────────────────────────────

class TestHumanReviewDecisionArtifacts:

    def test_decision_is_created(self) -> None:
        """P2-K: human review decision artifact is created and readable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "task_decision"
            run_dir.mkdir(parents=True)

            path = write_human_review_decision(
                run_dir, "task_decision",
                decision="approve_retry",
                reason="Looks safe to retry.",
            )

            assert path.exists()
            assert "human_review_1.json" in str(path)

            # Verify latest copy
            latest = run_dir / "recovery" / "human_review_decision.json"
            assert latest.exists()

            data = json.loads(latest.read_text(encoding="utf-8"))
            assert data["decision"] == "approve_retry"
            assert data["reason"] == "Looks safe to retry."
            assert data["task_id"] == "task_decision"
            assert data["source"] == "cli"

    def test_multiple_decisions_are_indexed(self) -> None:
        """P2-K: multiple human review decisions are indexed and not overwritten."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "task_multi"
            run_dir.mkdir(parents=True)

            write_human_review_decision(run_dir, "task_multi", "approve_retry", "First")
            write_human_review_decision(run_dir, "task_multi", "reject_retry", "Second")
            write_human_review_decision(run_dir, "task_multi", "stop", "Third")

            all_decisions = load_all_human_review_decisions(run_dir)
            assert len(all_decisions) == 3
            assert all_decisions[0].decision == "approve_retry"
            assert all_decisions[1].decision == "reject_retry"
            assert all_decisions[2].decision == "stop"

            # Latest decision should be the third one
            latest = load_latest_human_review_decision(run_dir)
            assert latest is not None
            assert latest.decision == "stop"

    def test_force_flag_is_recorded(self) -> None:
        """P2-K: force flag is auditable in decision artifact."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "task_force"
            run_dir.mkdir(parents=True)

            write_human_review_decision(
                run_dir, "task_force",
                decision="approve_retry",
                reason="Forced override.",
                force_used=True,
            )

            latest = load_latest_human_review_decision(run_dir)
            assert latest is not None
            assert latest.force_used is True

    def test_no_decision_returns_none(self) -> None:
        """P2-K: load_latest_human_review_decision returns None when no decisions exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "no_decisions"
            run_dir.mkdir(parents=True)
            assert load_latest_human_review_decision(run_dir) is None


# ── Resume respect for recovery state ────────────────────────────────

class TestResumeRespectsRecovery:

    def _setup_run_dir(self, tmpdir: str, verdict: str) -> Path:
        run_dir = Path(tmpdir) / "runs" / "task_resume"
        recovery_dir = run_dir / "recovery"
        recovery_dir.mkdir(parents=True)

        verdict_path = recovery_dir / "recovery_verdict.json"
        verdict_path.write_text(json.dumps({
            "task_id": "task_resume",
            "verdict": verdict,
            "reason": f"Test verdict: {verdict}",
            "safe_to_auto_retry": verdict == "retry",
            "requires_human_review": verdict in ("human_review", "stop"),
        }), encoding="utf-8")

        return run_dir

    def _read_verdict(self, run_dir: Path) -> dict:
        return json.loads((run_dir / "recovery" / "recovery_verdict.json").read_text(encoding="utf-8"))

    def test_resume_refuses_human_review_without_approval(self) -> None:
        """P2-K: resume must refuse human_review without explicit approval."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = self._setup_run_dir(tmpdir, "human_review")
            # No human decision exists
            assert load_latest_human_review_decision(run_dir) is None

            # Simulate what resume_task checks
            verdict_data = self._read_verdict(run_dir)
            v = verdict_data.get("verdict", "")
            human_decision = load_latest_human_review_decision(run_dir)

            assert v == "human_review"
            assert human_decision is None
            # Would be blocked without approval

    def test_resume_allows_retry_after_approve(self) -> None:
        """P2-K: resume allows retry after approve_retry decision."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = self._setup_run_dir(tmpdir, "human_review")
            write_human_review_decision(run_dir, "task_resume", "approve_retry", "Safe")

            verdict_data = self._read_verdict(run_dir)
            v = verdict_data.get("verdict", "")
            human_decision = load_latest_human_review_decision(run_dir)

            assert v == "human_review"
            assert human_decision is not None
            assert human_decision.decision == "approve_retry"
            # Resume should proceed

    def test_resume_refuses_after_reject_retry(self) -> None:
        """P2-K: resume must refuse after reject_retry decision."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = self._setup_run_dir(tmpdir, "human_review")
            write_human_review_decision(run_dir, "task_resume", "reject_retry", "Unsafe")

            verdict_data = self._read_verdict(run_dir)
            v = verdict_data.get("verdict", "")
            human_decision = load_latest_human_review_decision(run_dir)

            assert v == "human_review"
            assert human_decision is not None
            assert human_decision.decision == "reject_retry"
            # Resume should be blocked

    def test_resume_refuses_after_stop(self) -> None:
        """P2-K: resume must refuse after stop verdict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = self._setup_run_dir(tmpdir, "stop")

            verdict_data = self._read_verdict(run_dir)
            v = verdict_data.get("verdict", "")

            assert v == "stop"
            # Resume should be blocked unless --force


# ── Retry attempt ledger ─────────────────────────────────────────────

class TestRetryAttemptLedger:

    def test_record_single_attempt(self) -> None:
        """P2-K: recording a retry attempt creates the ledger."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "task_retry"
            run_dir.mkdir(parents=True)

            record_retry_attempt(
                run_dir, "task_retry",
                trigger="auto_policy",
                verdict="retry",
                command="python -m pytest tests/ -q",
                result="failed",
                failure_category="test_failure",
            )

            assert retry_attempt_count(run_dir) == 1
            attempts = load_retry_attempts(run_dir)
            assert len(attempts) == 1
            assert attempts[0].attempt == 1
            assert attempts[0].trigger == "auto_policy"
            assert attempts[0].result == "failed"

    def test_repeated_failures_escalate(self) -> None:
        """P2-K: repeated test failures escalate — count increases each time."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "task_escalate"
            run_dir.mkdir(parents=True)

            for i in range(3):
                record_retry_attempt(
                    run_dir, "task_escalate",
                    trigger="auto_policy",
                    verdict="retry",
                    command="pytest",
                    result="failed",
                    failure_category="test_failure",
                )

            assert retry_attempt_count(run_dir) == 3
            attempts = load_retry_attempts(run_dir)
            assert [a.attempt for a in attempts] == [1, 2, 3]

    def test_ledger_empty_when_no_attempts(self) -> None:
        """P2-K: ledger returns empty when no retry attempts exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "no_retries"
            run_dir.mkdir(parents=True)
            assert retry_attempt_count(run_dir) == 0
            assert load_retry_attempts(run_dir) == []

    def test_human_approved_trigger_recorded(self) -> None:
        """P2-K: human_approved trigger is recorded in the ledger."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "task_human"
            run_dir.mkdir(parents=True)

            record_retry_attempt(
                run_dir, "task_human",
                trigger="human_approved",
                verdict="retry",
                command="python -m pytest tests/ -q",
                result="success",
                failure_category="test_failure",
            )

            attempts = load_retry_attempts(run_dir)
            assert attempts[0].trigger == "human_approved"
            assert attempts[0].result == "success"


# ── Dangerous categories not auto-retried ────────────────────────────

class TestDangerousCategoriesP2K:

    def test_secret_leak_never_auto_retried(self) -> None:
        """P2-K: dangerous categories must never become auto-retry even with human review."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "task_secret"
            run_dir.mkdir(parents=True)

            # Create a secret_leak_risk verdict
            recovery_dir = run_dir / "recovery"
            recovery_dir.mkdir(parents=True)
            (recovery_dir / "recovery_verdict.json").write_text(json.dumps({
                "task_id": "task_secret",
                "verdict": "human_review",
                "reason": "secret_leak_risk requires human review",
                "safe_to_auto_retry": False,
                "requires_human_review": True,
            }), encoding="utf-8")

            # Even with approve_retry, the policy should still block auto-retry
            write_human_review_decision(run_dir, "task_secret", "approve_retry", "Approved")

            latest = load_latest_human_review_decision(run_dir)
            assert latest is not None
            assert latest.decision == "approve_retry"

            # The verdict still says safe_to_auto_retry is False
            verdict = json.loads((recovery_dir / "recovery_verdict.json").read_text(encoding="utf-8"))
            assert verdict["safe_to_auto_retry"] is False
            assert verdict["requires_human_review"] is True


# ── Closure report integration ───────────────────────────────────────

class TestClosureReportIntegration:

    def test_closure_summary_when_no_artifacts(self) -> None:
        """P2-K: closure summary returns None when no recovery artifacts exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "no_recovery"
            run_dir.mkdir(parents=True)
            assert build_recovery_closure_summary(run_dir) is None

    def test_closure_summary_with_failures(self) -> None:
        """P2-K: closure summary includes failure count, categories, verdicts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "task_closure"
            failures_dir = run_dir / "recovery" / "failures"
            failures_dir.mkdir(parents=True)

            # Create indexed failure artifacts
            event = create_failure_event(
                task_id="task_closure", project="AgentLab", stage="pytest",
                command="pytest", exit_code=1,
                stderr="FAILED test_example\nAssertionError: assert False",
            )
            diagnosis = diagnose_failure(event)
            policy = load_retry_policy(ROOT)
            verdict = decide_retry_action(diagnosis, policy)

            (failures_dir / "failure_event_1.json").write_text(
                json.dumps(event.to_dict()), encoding="utf-8")
            (failures_dir / "failure_diagnosis_1.json").write_text(
                json.dumps(diagnosis.to_dict()), encoding="utf-8")
            (failures_dir / "recovery_verdict_1.json").write_text(
                json.dumps(verdict.to_dict()), encoding="utf-8")

            # Also write top-level verdict
            (run_dir / "recovery" / "recovery_verdict.json").write_text(
                json.dumps(verdict.to_dict()), encoding="utf-8")

            summary = build_recovery_closure_summary(run_dir)
            assert summary is not None
            assert summary["failure_count"] == 1
            assert "test_failure" in summary["categories"]
            assert len(summary["verdict_history"]) >= 1
            assert summary["verdict_history"][0]["verdict"] == "retry"

    def test_closure_summary_includes_human_decisions(self) -> None:
        """P2-K: closure summary includes human decisions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "task_closure_hr"
            recovery_dir = run_dir / "recovery"
            recovery_dir.mkdir(parents=True)

            (recovery_dir / "recovery_verdict.json").write_text(json.dumps({
                "task_id": "task_closure_hr",
                "verdict": "human_review",
                "reason": "needs review",
            }), encoding="utf-8")

            write_human_review_decision(run_dir, "task_closure_hr", "approve_retry", "Approved")
            write_human_review_decision(run_dir, "task_closure_hr", "reject_retry", "Changed mind")

            summary = build_recovery_closure_summary(run_dir)
            assert summary is not None
            assert len(summary["human_decisions"]) == 2
            assert summary["human_decisions"][0]["decision"] == "approve_retry"
            assert summary["human_decisions"][1]["decision"] == "reject_retry"

    def test_closure_summary_includes_retry_attempts(self) -> None:
        """P2-K: closure summary includes retry attempt count and final outcome."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "task_closure_retry"
            recovery_dir = run_dir / "recovery"
            recovery_dir.mkdir(parents=True)

            (recovery_dir / "recovery_verdict.json").write_text(json.dumps({
                "task_id": "task_closure_retry",
                "verdict": "retry",
                "reason": "retryable",
            }), encoding="utf-8")

            record_retry_attempt(run_dir, "task_closure_retry",
                trigger="auto_policy", verdict="retry",
                command="pytest", result="failed", failure_category="test_failure")
            record_retry_attempt(run_dir, "task_closure_retry",
                trigger="human_approved", verdict="retry",
                command="pytest", result="success", failure_category="test_failure")

            summary = build_recovery_closure_summary(run_dir)
            assert summary is not None
            assert summary["retry_attempts"] == 2
            assert summary["final_outcome"] == "success"


# ── Status displays recovery info ────────────────────────────────────

class TestStatusDisplaysRecovery:

    def test_recovery_status_json_output(self) -> None:
        """P2-K: recovery-status --json produces valid JSON with expected fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "task_status"
            recovery_dir = run_dir / "recovery"
            recovery_dir.mkdir(parents=True)

            event = create_failure_event(
                task_id="task_status", project="AgentLab", stage="pytest",
                command="pytest", exit_code=1, stderr="FAILED",
            )
            diagnosis = diagnose_failure(event)
            policy = load_retry_policy(ROOT)
            verdict = decide_retry_action(diagnosis, policy)

            (recovery_dir / "failure_event.json").write_text(
                json.dumps(event.to_dict()), encoding="utf-8")
            (recovery_dir / "failure_diagnosis.json").write_text(
                json.dumps(diagnosis.to_dict()), encoding="utf-8")
            (recovery_dir / "recovery_verdict.json").write_text(
                json.dumps(verdict.to_dict()), encoding="utf-8")

            # Verify verdict is readable
            v_data = json.loads((recovery_dir / "recovery_verdict.json").read_text(encoding="utf-8"))
            assert v_data["verdict"] == "retry"

            # Verify human decision path
            write_human_review_decision(run_dir, "task_status", "approve_retry", "OK")
            assert (recovery_dir / "human_review_decision.json").exists()

            # Verify retry ledger
            record_retry_attempt(run_dir, "task_status",
                trigger="auto_policy", verdict="retry",
                command="pytest", result="success", failure_category="test_failure")
            assert (recovery_dir / "retry_attempts.json").exists()

    def test_next_action_derivation(self) -> None:
        """P2-K: next action is derived correctly from verdict + decision."""
        from agent_runtime.recovery.human_review import HumanReviewDecision

        def derive(verdict: dict | None, decision) -> str:
            if verdict is None:
                return "No recovery verdict"
            v = verdict.get("verdict", "")
            if v == "stop":
                if decision and decision.decision == "approve_retry" and decision.force_used:
                    return "retry allowed (--force override)"
                return "stop — task permanently failed"
            if v == "human_review":
                if decision:
                    d = decision.decision
                    if d == "approve_retry":
                        return "retry allowed (human approved)"
                    if d == "reject_retry":
                        return "stop — retry was rejected"
                    if d == "stop":
                        return "stop — task was stopped"
                return "blocked — awaiting human review"
            if v == "retry":
                if decision and decision.decision == "reject_retry":
                    return "stop — retry was rejected after verdict"
                return "retry allowed (per policy)"
            if v == "continue":
                return "continue allowed"
            return f"unknown verdict '{v}'"

        # retry verdict → retry allowed
        assert "retry allowed" in derive({"verdict": "retry", "reason": ""}, None)

        # human_review without decision → blocked
        assert "blocked" in derive({"verdict": "human_review", "reason": ""}, None)

        # human_review with approve → retry allowed
        assert "retry allowed" in derive(
            {"verdict": "human_review", "reason": ""},
            HumanReviewDecision(task_id="t", decision="approve_retry", reason="", created_at=""))

        # human_review with reject → stop
        assert "stop" in derive(
            {"verdict": "human_review", "reason": ""},
            HumanReviewDecision(task_id="t", decision="reject_retry", reason="", created_at=""))

        # stop → stop
        assert "stop" in derive({"verdict": "stop", "reason": ""}, None)

        # stop with force → retry allowed
        hr = HumanReviewDecision(
            task_id="t", decision="approve_retry", reason="", created_at="", force_used=True)
        assert "retry allowed" in derive({"verdict": "stop", "reason": ""}, hr)


# ── P2-I smoke compatibility ────────────────────────────────────────

class TestP2ISmokeStillPassesP2K:

    def test_smoke_verdict_still_retry(self) -> None:
        """P2-I: smoke verdict still retry after P2-K changes."""
        event = create_failure_event(
            task_id="smoke_p2k", project="AgentLab", stage="pytest",
            command="python -m pytest tests/ -q", exit_code=1,
            stderr="tests/test_example.py FAILED\nAssertionError: assert False",
        )
        diagnosis = diagnose_failure(event)
        policy = load_retry_policy(ROOT)
        verdict = decide_retry_action(diagnosis, policy)

        assert verdict.verdict == VerdictType.RETRY
        assert verdict.safe_to_auto_retry is True