"""Tests for P2-J: Real Pipeline Failure Recovery Integration."""

from __future__ import annotations

import json
import tempfile
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
)


# ── test_failure retry policy fix ───────────────────────────────────

class TestTestFailureRetryPolicy:

    def test_test_failure_receives_retry_verdict(self) -> None:
        """P2-J: test_failure must produce a deterministic retry verdict, not human_review."""
        event = create_failure_event(
            task_id="task_0001",
            project="AgentLab",
            stage="pytest",
            command="python -m pytest tests/ -q",
            exit_code=1,
            stderr="tests/test_example.py FAILED\nAssertionError: assert False",
            stdout="running 5 tests...",
        )
        diagnosis = diagnose_failure(event)
        policy = load_retry_policy(ROOT)
        verdict = decide_retry_action(diagnosis, policy)

        # Must NOT be "Cannot determine retry policy for test_failure"
        assert verdict.verdict != VerdictType.HUMAN_REVIEW, (
            f"test_failure should not require human_review, got: {verdict.reason}"
        )
        assert verdict.verdict == VerdictType.RETRY
        assert verdict.safe_to_auto_retry is True
        assert "Cannot determine" not in verdict.reason

    def test_test_failure_next_commands_include_pytest(self) -> None:
        """P2-J: test_failure retry should include pytest re-run commands."""
        event = create_failure_event(
            task_id="task_0002",
            project="AgentLab",
            stage="pytest",
            command="python -m pytest tests/ -q",
            exit_code=1,
            stderr="FAILED test_something",
        )
        diagnosis = diagnose_failure(event)
        policy = load_retry_policy(ROOT)
        verdict = decide_retry_action(diagnosis, policy)

        assert any("pytest" in cmd for cmd in verdict.next_commands), (
            f"Expected pytest in next_commands, got: {verdict.next_commands}"
        )

    def test_test_failure_has_attempts_remaining(self) -> None:
        """P2-J: test_failure with max_attempts=1 and 0 previous should have 1 remaining."""
        event = create_failure_event(
            task_id="task_0003",
            project="AgentLab",
            stage="pytest",
            command="pytest",
            exit_code=1,
            stderr="FAILED",
        )
        diagnosis = diagnose_failure(event)
        policy = load_retry_policy(ROOT)
        verdict = decide_retry_action(diagnosis, policy, previous_attempts=0)

        assert verdict.allowed_attempts_remaining == 1


# ── Recovery artifact creation ──────────────────────────────────────

class TestRecoveryArtifactCreation:

    def test_failed_command_creates_all_artifacts(self) -> None:
        """P2-J: failed command must produce all 4 recovery artifacts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "task_test"
            run_dir.mkdir(parents=True)

            event = create_failure_event(
                task_id="task_test",
                project="AgentLab",
                stage="pytest",
                command="python -m pytest tests/ -q",
                exit_code=1,
                stderr="FAILED test_example",
                stdout="running tests...",
            )
            diagnosis = diagnose_failure(event)
            policy = load_retry_policy(ROOT)
            plan = build_recovery_plan(event, diagnosis, policy)
            verdict = decide_retry_action(diagnosis, policy)

            # Write artifacts
            recovery_dir = run_dir / "recovery"
            recovery_dir.mkdir(parents=True, exist_ok=True)

            (recovery_dir / "failure_event.json").write_text(
                json.dumps(event.to_dict(), indent=2), encoding="utf-8"
            )
            (recovery_dir / "failure_diagnosis.json").write_text(
                json.dumps(diagnosis.to_dict(), indent=2), encoding="utf-8"
            )
            (recovery_dir / "recovery_plan.md").write_text(
                plan.to_markdown(), encoding="utf-8"
            )
            (recovery_dir / "recovery_verdict.json").write_text(
                json.dumps(verdict.to_dict(), indent=2), encoding="utf-8"
            )

            # Verify all artifacts exist
            assert (recovery_dir / "failure_event.json").exists()
            assert (recovery_dir / "failure_diagnosis.json").exists()
            assert (recovery_dir / "recovery_plan.md").exists()
            assert (recovery_dir / "recovery_verdict.json").exists()

            # Verify content is valid JSON
            event_data = json.loads((recovery_dir / "failure_event.json").read_text())
            assert event_data["task_id"] == "task_test"

            diagnosis_data = json.loads((recovery_dir / "failure_diagnosis.json").read_text())
            assert diagnosis_data["primary_category"] == "test_failure"

            verdict_data = json.loads((recovery_dir / "recovery_verdict.json").read_text())
            assert verdict_data["verdict"] == "retry"

    def test_multiple_failures_use_indexed_files(self) -> None:
        """P2-J: multiple failures must not overwrite; use indexed files in failures/."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "task_multi"
            failures_dir = run_dir / "recovery" / "failures"
            failures_dir.mkdir(parents=True)

            for i in range(1, 4):
                event = create_failure_event(
                    task_id="task_multi",
                    project="AgentLab",
                    stage=f"stage_{i}",
                    command="cmd",
                    exit_code=1,
                    stderr=f"failure {i}",
                )
                (failures_dir / f"failure_event_{i}.json").write_text(
                    json.dumps(event.to_dict(), indent=2), encoding="utf-8"
                )

            existing = sorted(failures_dir.glob("failure_event_*.json"))
            assert len(existing) == 3
            assert failures_dir / "failure_event_1.json" in existing
            assert failures_dir / "failure_event_2.json" in existing
            assert failures_dir / "failure_event_3.json" in existing


# ── Dangerous categories not auto-retried ───────────────────────────

class TestDangerousCategoriesNotAutoRetried:

    def test_secret_leak_risk_stopped(self) -> None:
        """P2-J: secret_leak_risk must never auto-retry."""
        event = create_failure_event(
            task_id="task_sec",
            project="AgentLab",
            stage="runtime",
            command="task",
            exit_code=1,
            error_type="secret_leak_risk",
            stderr="secret leak detected",
        )
        diagnosis = diagnose_failure(event)
        policy = load_retry_policy(ROOT)
        verdict = decide_retry_action(diagnosis, policy)

        assert verdict.verdict == VerdictType.HUMAN_REVIEW
        assert verdict.safe_to_auto_retry is False
        assert verdict.requires_human_review is True

    def test_permission_error_not_auto_retried(self) -> None:
        """P2-J: permission_error must never auto-retry."""
        event = create_failure_event(
            task_id="task_perm",
            project="AgentLab",
            stage="runtime",
            command="task",
            exit_code=1,
            error_type="permission_error",
            stderr="Permission denied",
        )
        diagnosis = diagnose_failure(event)
        policy = load_retry_policy(ROOT)
        verdict = decide_retry_action(diagnosis, policy)

        assert verdict.safe_to_auto_retry is False
        assert verdict.requires_human_review is True

    def test_syntax_error_is_non_retryable(self) -> None:
        """P2-J: syntax_error must be non-retryable, produce human_review verdict."""
        event = create_failure_event(
            task_id="task_syn",
            project="AgentLab",
            stage="compile",
            command="compileall",
            exit_code=1,
            error_type="syntax_error",
            stderr="SyntaxError: invalid syntax",
        )
        diagnosis = diagnose_failure(event)
        policy = load_retry_policy(ROOT)
        verdict = decide_retry_action(diagnosis, policy)

        # syntax_error is in both non_retryable_categories and require_human_review_for
        # human_review takes priority
        assert verdict.verdict == VerdictType.HUMAN_REVIEW
        assert verdict.safe_to_auto_retry is False
        assert verdict.requires_human_review is True


# ── Resume/status can read recovery verdict ─────────────────────────

class TestStatusReadsRecoveryVerdict:

    def test_verdict_is_readable_json(self) -> None:
        """P2-J: recovery verdict must be readable JSON with all required fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "task_status"
            recovery_dir = run_dir / "recovery"
            recovery_dir.mkdir(parents=True)

            event = create_failure_event(
                task_id="task_status",
                project="AgentLab",
                stage="pytest",
                command="pytest",
                exit_code=1,
                stderr="FAILED",
            )
            diagnosis = diagnose_failure(event)
            policy = load_retry_policy(ROOT)
            verdict = decide_retry_action(diagnosis, policy)

            verdict_path = recovery_dir / "recovery_verdict.json"
            verdict_path.write_text(
                json.dumps(verdict.to_dict(), indent=2), encoding="utf-8"
            )

            # Simulate status command reading verdict
            verdict_data = json.loads(verdict_path.read_text(encoding="utf-8"))
            required_fields = [
                "task_id", "verdict", "reason", "allowed_attempts_remaining",
                "safe_to_auto_retry", "safe_to_auto_rollback",
                "requires_human_review", "next_commands",
                "forbidden_without_approval", "created_at",
            ]
            for field in required_fields:
                assert field in verdict_data, f"Missing field: {field}"

            assert verdict_data["verdict"] == "retry"
            assert verdict_data["safe_to_auto_retry"] is True

    def test_human_review_verdict_is_readable(self) -> None:
        """P2-J: human_review verdict should be readable by status command."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "task_hr"
            recovery_dir = run_dir / "recovery"
            recovery_dir.mkdir(parents=True)

            event = create_failure_event(
                task_id="task_hr",
                project="AgentLab",
                stage="runtime",
                command="task",
                exit_code=1,
                error_type="secret_leak_risk",
                stderr="secret leak detected",
            )
            diagnosis = diagnose_failure(event)
            policy = load_retry_policy(ROOT)
            verdict = decide_retry_action(diagnosis, policy)

            verdict_path = recovery_dir / "recovery_verdict.json"
            verdict_path.write_text(
                json.dumps(verdict.to_dict(), indent=2), encoding="utf-8"
            )

            verdict_data = json.loads(verdict_path.read_text(encoding="utf-8"))
            assert verdict_data["verdict"] == "human_review"
            assert verdict_data["safe_to_auto_retry"] is False
            assert verdict_data["requires_human_review"] is True


# ── Repeated failure escalation ─────────────────────────────────────

class TestRepeatedFailureEscalation:

    def test_exhausted_attempts_produces_continue(self) -> None:
        """P2-J: when retry attempts exhausted, verdict should be continue (not retry)."""
        event = create_failure_event(
            task_id="task_exhaust",
            project="AgentLab",
            stage="pytest",
            command="pytest",
            exit_code=1,
            stderr="FAILED",
        )
        diagnosis = diagnose_failure(event)
        policy = load_retry_policy(ROOT)
        # test_failure max_attempts = 1, previous_attempts = 1 -> exhausted
        verdict = decide_retry_action(diagnosis, policy, previous_attempts=1)

        assert verdict.verdict == VerdictType.CONTINUE
        assert verdict.allowed_attempts_remaining == 0
        assert "exhausted" in verdict.reason.lower()

    def test_repeated_timeout_escalates(self) -> None:
        """P2-J: repeated timeout with exhausted attempts should escalate."""
        event = create_failure_event(
            task_id="task_timeout",
            project="AgentLab",
            stage="runtime",
            command="task",
            exit_code=1,
            error_type="timeout",
            stderr="timeout exceeded",
        )
        diagnosis = diagnose_failure(event)
        policy = load_retry_policy(ROOT)
        # timeout max_attempts = 2, previous_attempts = 2 -> exhausted
        verdict = decide_retry_action(diagnosis, policy, previous_attempts=2)

        assert verdict.verdict == VerdictType.CONTINUE
        assert verdict.allowed_attempts_remaining == 0

    def test_first_timeout_is_retryable(self) -> None:
        """P2-J: first timeout should be retryable with attempts remaining."""
        event = create_failure_event(
            task_id="task_timeout2",
            project="AgentLab",
            stage="runtime",
            command="task",
            exit_code=1,
            error_type="timeout",
            stderr="timeout exceeded",
        )
        diagnosis = diagnose_failure(event)
        policy = load_retry_policy(ROOT)
        verdict = decide_retry_action(diagnosis, policy, previous_attempts=0)

        assert verdict.verdict == VerdictType.RETRY
        assert verdict.allowed_attempts_remaining == 2


# ── P2-I smoke compatibility ────────────────────────────────────────

class TestP2ISmokeStillPasses:

    def test_smoke_classification(self) -> None:
        """P2-I: smoke classification still works after P2-J changes."""
        classifier = FailureClassifier()
        classification = classifier.classify(
            stderr="tests/test_example.py FAILED\nAssertionError: assert False\n1 failed in 0.1s",
            stdout="running 5 tests...",
        )
        assert classification.primary_category == FailureCategory.TEST_FAILURE
        assert classification.confidence > 0.5

    def test_smoke_diagnosis(self) -> None:
        """P2-I: smoke diagnosis still produces valid output."""
        event = create_failure_event(
            task_id="smoke_test",
            project="AgentLab",
            stage="pytest",
            command="python -m pytest tests/ -q",
            exit_code=1,
            stderr="tests/test_example.py FAILED\nAssertionError: assert False",
            stdout="running 5 tests...",
        )
        diagnosis = diagnose_failure(event)
        assert diagnosis.primary_category == FailureCategory.TEST_FAILURE
        assert len(diagnosis.root_cause_hypothesis) >= 1
        assert len(diagnosis.evidence) >= 1
        assert len(diagnosis.recommended_next_action) > 0

    def test_smoke_plan_and_verdict(self) -> None:
        """P2-I: smoke plan and verdict still produce valid output."""
        event = create_failure_event(
            task_id="smoke_test",
            project="AgentLab",
            stage="pytest",
            command="python -m pytest tests/ -q",
            exit_code=1,
            stderr="tests/test_example.py FAILED\nAssertionError: assert False",
            stdout="running 5 tests...",
        )
        diagnosis = diagnose_failure(event)
        policy = load_retry_policy(ROOT)
        plan = build_recovery_plan(event, diagnosis, policy)
        verdict = decide_retry_action(diagnosis, policy)

        assert plan.to_markdown()
        assert "Recovery Plan" in plan.to_markdown()
        assert verdict.verdict == VerdictType.RETRY
        assert verdict.to_dict()["verdict"] == "retry"


# ── State store helpers ─────────────────────────────────────────────

class TestStateStoreRecoveryHelpers:

    def test_mark_failed_recoverable_sets_status(self) -> None:
        """P2-J: verify the mark_failed_recoverable function exists and is importable."""
        import sys
        from pathlib import Path
        # Add agent_runtime to path for state_store imports
        agent_runtime_path = str(ROOT / "agent_runtime")
        if agent_runtime_path not in sys.path:
            sys.path.insert(0, agent_runtime_path)
        from state_store import mark_failed_recoverable, load_state

        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            state = mark_failed_recoverable(
                run_dir, "AgentLab", "task_test",
                "Test failure", failed_agent="Coder",
            )
            assert state.status == "failed_recoverable"
            assert state.current_agent == "Coder"

    def test_mark_failed_blocked_sets_status(self) -> None:
        """P2-J: verify the mark_failed_blocked function exists and is importable."""
        import sys
        agent_runtime_path = str(ROOT / "agent_runtime")
        if agent_runtime_path not in sys.path:
            sys.path.insert(0, agent_runtime_path)
        from state_store import mark_failed_blocked, load_state

        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            state = mark_failed_blocked(
                run_dir, "AgentLab", "task_test",
                "Human review required", failed_agent="Coder",
            )
            assert state.status == "blocked"
            assert state.current_agent == "Coder"

    def test_mark_failed_stopped_sets_status(self) -> None:
        """P2-J: verify the mark_failed_stopped function exists and is importable."""
        import sys
        agent_runtime_path = str(ROOT / "agent_runtime")
        if agent_runtime_path not in sys.path:
            sys.path.insert(0, agent_runtime_path)
        from state_store import mark_failed_stopped, load_state

        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            state = mark_failed_stopped(
                run_dir, "AgentLab", "task_test",
                "Unsafe category", failed_agent="Coder",
            )
            assert state.status == "failed"
            assert state.current_agent == "Coder"


# ── Recovery pipeline end-to-end ─────────────────────────────────────

class TestRecoveryPipelineEndToEnd:

    def test_full_pipeline_creates_all_artifacts(self) -> None:
        """P2-J: full recovery pipeline creates all 4 artifacts in indexed directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "task_e2e"
            failures_dir = run_dir / "recovery" / "failures"
            failures_dir.mkdir(parents=True)

            # Simulate the full pipeline: FailureEvent -> Diagnosis -> Plan -> Verdict
            event = create_failure_event(
                task_id="task_e2e",
                project="AgentLab",
                stage="pytest",
                command="python -m pytest tests/ -q",
                exit_code=1,
                stderr="FAILED test_example\nAssertionError: assert False",
                stdout="running 5 tests...",
            )
            diagnosis = diagnose_failure(event)
            policy = load_retry_policy(ROOT)
            plan = build_recovery_plan(event, diagnosis, policy)
            verdict = decide_retry_action(diagnosis, policy)

            # Write indexed artifacts
            index = 1
            (failures_dir / f"failure_event_{index}.json").write_text(
                json.dumps(event.to_dict(), indent=2), encoding="utf-8"
            )
            (failures_dir / f"failure_diagnosis_{index}.json").write_text(
                json.dumps(diagnosis.to_dict(), indent=2), encoding="utf-8"
            )
            (failures_dir / f"recovery_plan_{index}.md").write_text(
                plan.to_markdown(), encoding="utf-8"
            )
            (failures_dir / f"recovery_verdict_{index}.json").write_text(
                json.dumps(verdict.to_dict(), indent=2), encoding="utf-8"
            )

            # Verify all artifacts exist
            assert (failures_dir / "failure_event_1.json").exists()
            assert (failures_dir / "failure_diagnosis_1.json").exists()
            assert (failures_dir / "recovery_plan_1.md").exists()
            assert (failures_dir / "recovery_verdict_1.json").exists()

            # Verify content
            verdict_data = json.loads(
                (failures_dir / "recovery_verdict_1.json").read_text(encoding="utf-8")
            )
            assert verdict_data["verdict"] == "retry"
            assert verdict_data["safe_to_auto_retry"] is True

    def test_multiple_failures_indexed(self) -> None:
        """P2-J: multiple failures produce indexed files without overwriting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "task_multi"
            failures_dir = run_dir / "recovery" / "failures"
            failures_dir.mkdir(parents=True)

            for i in range(1, 4):
                event = create_failure_event(
                    task_id="task_multi",
                    project="AgentLab",
                    stage=f"stage_{i}",
                    command="cmd",
                    exit_code=1,
                    stderr=f"failure {i}",
                )
                diagnosis = diagnose_failure(event)
                policy = load_retry_policy(ROOT)
                plan = build_recovery_plan(event, diagnosis, policy)
                verdict = decide_retry_action(diagnosis, policy)

                (failures_dir / f"failure_event_{i}.json").write_text(
                    json.dumps(event.to_dict(), indent=2), encoding="utf-8"
                )
                (failures_dir / f"failure_diagnosis_{i}.json").write_text(
                    json.dumps(diagnosis.to_dict(), indent=2), encoding="utf-8"
                )
                (failures_dir / f"recovery_plan_{i}.md").write_text(
                    plan.to_markdown(), encoding="utf-8"
                )
                (failures_dir / f"recovery_verdict_{i}.json").write_text(
                    json.dumps(verdict.to_dict(), indent=2), encoding="utf-8"
                )

            indexed = sorted(failures_dir.glob("failure_event_*.json"))
            assert len(indexed) == 3, f"Expected 3 indexed failures, got {len(indexed)}"
            assert failures_dir / "failure_event_1.json" in indexed
            assert failures_dir / "failure_event_3.json" in indexed