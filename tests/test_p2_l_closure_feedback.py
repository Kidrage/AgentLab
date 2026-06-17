"""Tests for P2-L: Recovery History → Closure Quality Feedback."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from agent_runtime.recovery.closure_feedback import (
    ClosureQualityFeedback,
    RecoveryHistoryEntry,
    derive_closure_quality_feedback,
    load_recovery_history,
    write_closure_feedback_json,
    write_closure_feedback_report,
    main as closure_feedback_main,
)


# ── Helpers ─────────────────────────────────────────────────────────────

def _make_recovery_dir(base: Path, task_id: str) -> Path:
    """Create a run directory with a recovery subdirectory."""
    run_dir = base / "runs" / task_id
    recovery_dir = run_dir / "recovery"
    recovery_dir.mkdir(parents=True)
    return run_dir


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── Test 1: Missing/empty run dir returns warning ───────────────────────

class TestLoadRecoveryHistoryMissing:
    def test_missing_dir_returns_warning(self) -> None:
        """load_recovery_history on a missing directory returns warning, no crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "nonexistent"
            entries, warnings = load_recovery_history(missing)
            assert entries == []
            assert "no_recovery_directory" in warnings

    def test_empty_recovery_dir_returns_warning(self) -> None:
        """load_recovery_history on a directory with no recovery subdir returns warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "task_empty"
            run_dir.mkdir(parents=True)
            entries, warnings = load_recovery_history(run_dir)
            assert entries == []
            assert "no_recovery_directory" in warnings


# ── Test 2: No recovery history feedback ───────────────────────────────

class TestDeriveFeedbackNoHistory:
    def test_no_recovery_history(self) -> None:
        """derive_closure_quality_feedback with empty history returns no_recovery."""
        feedback = derive_closure_quality_feedback(
            task_id="task_none",
            recovery_history=[],
        )
        assert feedback.recovery_used is False
        assert feedback.recovery_successful is None
        assert feedback.retry_count == 0
        assert feedback.human_review_required is False
        assert "no_action" in feedback.recommended_actions
        assert any("No recovery history found" in l for l in feedback.lessons)


# ── Test 3: Successful recovery ────────────────────────────────────────

class TestDeriveFeedbackSuccessfulRecovery:
    def test_successful_recovery(self) -> None:
        """Recovery was used and closure passed → recovery_successful=true."""
        history = [
            RecoveryHistoryEntry(
                task_id="task_ok",
                event_type="failure_captured",
                status="captured",
                category="test_failure",
            ),
            RecoveryHistoryEntry(
                task_id="task_ok",
                event_type="failure_diagnosed",
                status="diagnosed",
                category="test_failure",
            ),
            RecoveryHistoryEntry(
                task_id="task_ok",
                event_type="recovery_verdict",
                status="verdict",
                verdict="retry",
            ),
            RecoveryHistoryEntry(
                task_id="task_ok",
                event_type="retry_attempt",
                status="success",
            ),
        ]
        feedback = derive_closure_quality_feedback(
            task_id="task_ok",
            recovery_history=history,
            closure_artifacts={"verdict": "passed"},
        )
        assert feedback.verdict == "passed"
        assert feedback.recovery_used is True
        assert feedback.recovery_successful is True
        assert feedback.quality_score is not None
        assert feedback.quality_score > 0.5  # better than baseline failed
        assert any(
            "Recovery was required before closure" in l for l in feedback.lessons
        )


# ── Test 4: Failed recovery ────────────────────────────────────────────

class TestDeriveFeedbackFailedRecovery:
    def test_failed_recovery(self) -> None:
        """Closure failed/blocked and recovery was used → recovery_successful=false."""
        history = [
            RecoveryHistoryEntry(
                task_id="task_fail",
                event_type="failure_captured",
                status="captured",
                category="timeout",
            ),
            RecoveryHistoryEntry(
                task_id="task_fail",
                event_type="recovery_verdict",
                status="verdict",
                verdict="stop",
            ),
            RecoveryHistoryEntry(
                task_id="task_fail",
                event_type="human_review",
                status="reject_retry",
                verdict="reject_retry",
            ),
        ]
        feedback = derive_closure_quality_feedback(
            task_id="task_fail",
            recovery_history=history,
            closure_artifacts={"verdict": "failed"},
        )
        assert feedback.verdict == "failed"
        assert feedback.recovery_used is True
        assert feedback.recovery_successful is False
        assert feedback.human_review_required is True
        assert feedback.blocked_reason is not None
        assert any(
            "keep_recovery_gate_enabled" in a or "route_similar_failures_to_human_review" in a
            for a in feedback.recommended_actions
        )


# ── Test 5: Retry count deterministic ──────────────────────────────────

class TestRetryCountDeterministic:
    def test_retry_count_is_deterministic(self) -> None:
        """Multiple retry/resume signals are counted correctly."""
        history = [
            RecoveryHistoryEntry(
                task_id="task_retry",
                event_type="recovery_verdict",
                verdict="retry",
            ),
            RecoveryHistoryEntry(
                task_id="task_retry",
                event_type="retry_attempt",
                status="retry",
                next_action="retry with smaller batch",
            ),
            RecoveryHistoryEntry(
                task_id="task_retry",
                event_type="retry_attempt",
                status="success",
                next_action="resume from checkpoint",
            ),
            RecoveryHistoryEntry(
                task_id="task_retry",
                event_type="recovery_verdict",
                verdict="rerun",
            ),
        ]
        feedback = derive_closure_quality_feedback(
            task_id="task_retry",
            recovery_history=history,
            closure_artifacts={"verdict": "passed"},
        )
        assert feedback.retry_count == 4
        assert feedback.recovery_used is True

    def test_no_retry_when_none_present(self) -> None:
        """No retry signals → retry_count=0."""
        history = [
            RecoveryHistoryEntry(
                task_id="task_none",
                event_type="failure_captured",
                status="captured",
                category="syntax_error",
            ),
        ]
        feedback = derive_closure_quality_feedback(
            task_id="task_none",
            recovery_history=history,
        )
        assert feedback.retry_count == 0


# ── Test 6: Human review required detection ────────────────────────────

class TestHumanReviewRequired:
    def test_human_review_detected_via_status(self) -> None:
        """human_review / rejected / stopped / blocked signals set flag."""
        history = [
            RecoveryHistoryEntry(
                task_id="task_hr",
                event_type="human_review",
                status="stopped",
            ),
        ]
        feedback = derive_closure_quality_feedback(
            task_id="task_hr",
            recovery_history=history,
        )
        assert feedback.human_review_required is True

    def test_human_review_detected_via_verdict(self) -> None:
        """blocked verdict sets human_review_required."""
        history = [
            RecoveryHistoryEntry(
                task_id="task_blk",
                event_type="recovery_verdict",
                verdict="blocked",
            ),
        ]
        feedback = derive_closure_quality_feedback(
            task_id="task_blk",
            recovery_history=history,
        )
        assert feedback.human_review_required is True

    def test_no_human_review_when_absent(self) -> None:
        history = [
            RecoveryHistoryEntry(
                task_id="task_clean",
                event_type="failure_captured",
                status="captured",
                category="test_failure",
            ),
        ]
        feedback = derive_closure_quality_feedback(
            task_id="task_clean",
            recovery_history=history,
        )
        assert feedback.human_review_required is False


# ── Test 7: Write JSON and Markdown ────────────────────────────────────

class TestWriteFeedbackArtifacts:
    def test_write_json_and_markdown(self) -> None:
        """JSON and MD files are created; JSON round-trips."""
        feedback = ClosureQualityFeedback(
            task_id="task_write",
            verdict="passed",
            quality_score=0.85,
            recovery_used=True,
            recovery_successful=True,
            failure_categories=["test_failure"],
            retry_count=1,
            human_review_required=False,
            blocked_reason=None,
            lessons=["Recovery was required before closure."],
            recommended_actions=["increase_test_evidence_requirement"],
            evidence_artifacts=["/fake/path/evidence.json"],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "feedback_output"

            json_path = write_closure_feedback_json(feedback, out)
            md_path = write_closure_feedback_report(feedback, out)

            assert json_path.exists()
            assert md_path.exists()
            assert json_path.name == "closure_quality_feedback.json"
            assert md_path.name == "closure_quality_feedback.md"

            # JSON round-trip
            data = json.loads(json_path.read_text(encoding="utf-8"))
            assert data["task_id"] == "task_write"
            assert data["verdict"] == "passed"
            assert data["quality_score"] == 0.85
            assert data["recovery_used"] is True
            assert data["recovery_successful"] is True
            assert data["retry_count"] == 1
            assert "test_failure" in data["failure_categories"]
            assert "increase_test_evidence_requirement" in data["recommended_actions"]

            # Markdown includes key fields
            md_content = md_path.read_text(encoding="utf-8")
            assert "task_write" in md_content
            assert "passed" in md_content
            assert "increase_test_evidence_requirement" in md_content
            assert "Recovery was required before closure." in md_content


# ── Test 8: Corrupt artifact skipped with warning ──────────────────────

class TestCorruptArtifactSkipped:
    def test_corrupt_json_is_skipped_with_warning(self) -> None:
        """A malformed failure_event.json does not crash feedback generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = _make_recovery_dir(Path(tmpdir), "task_corrupt")
            recovery_dir = run_dir / "recovery"

            # Write corrupt JSON
            (recovery_dir / "failure_event.json").write_text(
                "this is not json {{{", encoding="utf-8"
            )

            # Write a valid diagnosis
            _write_json(recovery_dir / "failure_diagnosis.json", {
                "primary_category": "test_failure",
                "recommended_next_action": "retry",
            })

            entries, warnings = load_recovery_history(run_dir)

            # Should not crash
            assert len(entries) >= 1  # at least the diagnosis loaded
            # The corrupt file should produce no entry (silently skipped)
            failure_entries = [e for e in entries if e.event_type == "failure_captured"]
            assert len(failure_entries) == 0

            # Derive feedback should still work
            feedback = derive_closure_quality_feedback(
                task_id="task_corrupt",
                recovery_history=entries,
            )
            assert feedback is not None
            assert feedback.verdict in ("unknown", "retry")

    def test_mixed_valid_and_invalid_artifacts(self) -> None:
        """Mixed valid/corrupt artifacts still produce partial feedback with warnings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = _make_recovery_dir(Path(tmpdir), "task_mixed")
            recovery_dir = run_dir / "recovery"

            # Valid event
            _write_json(recovery_dir / "failure_event.json", {
                "error_type": "timeout",
                "created_at": "2025-01-01T00:00:00Z",
            })

            # Corrupt diagnoses
            failures_dir = recovery_dir / "failures"
            failures_dir.mkdir(parents=True)
            (failures_dir / "failure_diagnosis_1.json").write_text(
                "garbage}}}", encoding="utf-8"
            )

            # Valid verdict
            _write_json(recovery_dir / "recovery_verdict.json", {
                "verdict": "retry",
                "primary_category": "timeout",
            })

            entries, warnings = load_recovery_history(run_dir)

            assert len(entries) >= 2
            assert any("corrupt_diagnosis" in w for w in warnings)

            feedback = derive_closure_quality_feedback(
                task_id="task_mixed",
                recovery_history=entries,
            )
            assert feedback.verdict == "retry"
            assert feedback.recovery_used is True


# ── Test 9: CLI smoke test ─────────────────────────────────────────────

class TestFeedbackCLISmoke:
    def test_cli_runs_on_fixture_and_writes_artifacts(self) -> None:
        """CLI runs on a fixture directory and writes expected artifacts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = _make_recovery_dir(Path(tmpdir), "task_cli")
            recovery_dir = run_dir / "recovery"

            # Create minimal recovery artifacts
            _write_json(recovery_dir / "failure_event.json", {
                "error_type": "test_failure",
                "created_at": "2025-01-01T00:00:00Z",
            })
            _write_json(recovery_dir / "failure_diagnosis.json", {
                "primary_category": "test_failure",
                "recommended_next_action": "retry",
            })
            _write_json(recovery_dir / "recovery_verdict.json", {
                "verdict": "retry",
            })

            output_dir = Path(tmpdir) / "output"
            rc = closure_feedback_main([
                "--task-run-dir", str(run_dir),
                "--output-dir", str(output_dir),
            ])

            assert rc == 0

            json_path = output_dir / "closure_quality_feedback.json"
            md_path = output_dir / "closure_quality_feedback.md"
            assert json_path.exists()
            assert md_path.exists()

            data = json.loads(json_path.read_text(encoding="utf-8"))
            assert data["task_id"] == "task_cli"
            assert data["recovery_used"] is True

    def test_cli_missing_dir_returns_nonzero(self) -> None:
        """CLI exits non-zero when run dir does not exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "does_not_exist"
            rc = closure_feedback_main(["--task-run-dir", str(missing)])
            assert rc == 1


# ── Test 10: No context_governance runtime dependency ──────────────────

class TestNoContextGovernanceDependency:
    def test_closure_feedback_does_not_import_context_governance_redaction(self) -> None:
        """P2-L module must not import agent_runtime.context_governance.redaction."""
        import ast
        import sys

        module_path = ROOT / "agent_runtime" / "recovery" / "closure_feedback.py"
        source = module_path.read_text(encoding="utf-8")

        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom) and node.module:
                    module_name = node.module
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        module_name = alias.name
                else:
                    continue

                if "context_governance" in str(module_name) and "redaction" in str(module_name):
                    pytest.fail(
                        f"closure_feedback.py imports context_governance.redaction "
                        f"via: {ast.dump(node)}"
                    )

    def test_init_does_not_import_context_governance_redaction(self) -> None:
        """P2-L __init__ exports must not pull in context_governance.redaction."""
        import ast

        module_path = (
            ROOT / "agent_runtime" / "recovery" / "__init__.py"
        )
        source = module_path.read_text(encoding="utf-8")

        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom) and node.module:
                    module_name = node.module
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        module_name = alias.name
                else:
                    continue

                if "context_governance" in str(module_name):
                    pytest.fail(
                        f"recovery/__init__.py imports context_governance: "
                        f"{ast.dump(node)}"
                    )


# ── Quality score heuristic tests ──────────────────────────────────────

class TestQualityScoreHeuristic:
    def test_passed_no_recovery_scores_1_0(self) -> None:
        """Passed verdict with no recovery → 1.0."""
        feedback = derive_closure_quality_feedback(
            task_id="task_q1",
            recovery_history=[],
            closure_artifacts={"verdict": "passed"},
        )
        assert feedback.verdict == "passed"
        assert feedback.quality_score == 1.0

    def test_failed_with_retries_scores_low(self) -> None:
        """Failed verdict with retries scores at or near 0.0."""
        history = [
            RecoveryHistoryEntry(
                task_id="task_fail", event_type="recovery_verdict", verdict="retry",
            ),
            RecoveryHistoryEntry(
                task_id="task_fail", event_type="retry_attempt",
                status="retry", next_action="retry",
            ),
            RecoveryHistoryEntry(
                task_id="task_fail", event_type="human_review", status="stopped",
            ),
        ]
        feedback = derive_closure_quality_feedback(
            task_id="task_fail",
            recovery_history=history,
            closure_artifacts={"verdict": "failed"},
        )
        assert feedback.verdict == "failed"
        assert feedback.quality_score == 0.0  # floor at 0.0

    def test_unknown_scores_around_0_5(self) -> None:
        """Unknown verdict scores ~0.5."""
        feedback = derive_closure_quality_feedback(
            task_id="task_unk",
            recovery_history=[],
        )
        assert feedback.verdict == "unknown"
        assert feedback.quality_score == 0.5

    def test_recovery_bonus_capped_at_1_0(self) -> None:
        """Recovery bonus does not exceed 1.0."""
        history = [
            RecoveryHistoryEntry(
                task_id="task_cap", event_type="failure_captured",
                status="captured", category="test_failure",
            ),
        ]
        feedback = derive_closure_quality_feedback(
            task_id="task_cap",
            recovery_history=history,
            closure_artifacts={"verdict": "passed"},
        )
        assert feedback.quality_score is not None
        assert feedback.quality_score <= 1.0


# ── Load from disk integration tests ────────────────────────────────────

class TestLoadFromDisk:
    def test_load_full_recovery_artifacts(self) -> None:
        """Load a complete set of recovery artifacts from disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = _make_recovery_dir(Path(tmpdir), "task_full")
            recovery_dir = run_dir / "recovery"

            _write_json(recovery_dir / "failure_event.json", {
                "error_type": "timeout",
                "created_at": "2025-06-01T10:00:00Z",
            })
            _write_json(recovery_dir / "failure_diagnosis.json", {
                "primary_category": "timeout",
                "recommended_next_action": "retry",
                "created_at": "2025-06-01T10:01:00Z",
            })
            (recovery_dir / "recovery_plan.md").write_text(
                "# Recovery Plan\nRetry with longer timeout.", encoding="utf-8"
            )
            _write_json(recovery_dir / "recovery_verdict.json", {
                "verdict": "retry",
                "reason": "Timeout is transient",
            })
            _write_json(recovery_dir / "retry_attempts.json", {
                "attempts": [
                    {"attempt": 1, "result": "success", "verdict": "retry",
                     "command": "retry pipeline", "trigger": "auto",
                     "task_id": "task_full", "created_at": "2025-06-01T10:05:00Z"},
                ]
            })

            entries, warnings = load_recovery_history(run_dir)

            assert len(entries) >= 5  # event + diagnosis + plan + verdict + retry
            assert len(warnings) == 0

            # Verify event types present
            event_types = {e.event_type for e in entries}
            assert "failure_captured" in event_types
            assert "failure_diagnosed" in event_types
            assert "recovery_plan_generated" in event_types
            assert "recovery_verdict" in event_types
            assert "retry_attempt" in event_types

    def test_load_includes_indexed_failures(self) -> None:
        """Indexed failures directory is scanned for entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = _make_recovery_dir(Path(tmpdir), "task_idx")
            recovery_dir = run_dir / "recovery"
            failures_dir = recovery_dir / "failures"
            failures_dir.mkdir(parents=True)

            _write_json(failures_dir / "failure_event_1.json", {
                "error_type": "syntax_error",
            })
            _write_json(failures_dir / "failure_diagnosis_1.json", {
                "primary_category": "syntax_error",
            })

            entries, warnings = load_recovery_history(run_dir)

            assert len(entries) >= 2
            categories = {e.category for e in entries if e.category}
            assert "syntax_error" in categories
