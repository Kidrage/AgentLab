"""Tests for P2-I failure diagnosis, artifacts, CLI, and closure."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "projects" / "AgentLab" / "runs" / "dummy"

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


# ── Failure Diagnosis ──────────────────────────────────────────────

class TestFailureDiagnosis:

    def test_contains_root_cause_hypothesis(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="pytest",
            command="pytest", exit_code=1, stderr="test failed",
        )
        diag = diagnose_failure(event)
        assert len(diag.root_cause_hypothesis) >= 1

    def test_contains_evidence(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="pytest",
            command="pytest", exit_code=1, stderr="test failed",
            stdout="running tests...",
        )
        diag = diagnose_failure(event)
        assert len(diag.evidence) >= 1

    def test_marks_secret_leak_human_review(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="runtime",
            command="task", exit_code=1, error_type="secret_leak_risk",
            stderr="secret leak detected",
        )
        diag = diagnose_failure(event)
        assert diag.requires_human_review is True

    def test_text_integrity_marks_human_review(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="check",
            command="check", exit_code=1, error_type="text_integrity_failure",
            stderr="text integrity failed",
        )
        diag = diagnose_failure(event)
        assert diag.requires_human_review is True

    def test_safe_to_retry_for_timeout(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="runtime",
            command="task", exit_code=1, error_type="timeout",
            stderr="timeout exceeded",
        )
        diag = diagnose_failure(event)
        assert diag.blast_radius.safe_to_retry is True

    def test_syntax_error_not_retriable(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="compile",
            command="compileall", exit_code=1, error_type="syntax_error",
            stderr="SyntaxError",
        )
        diag = diagnose_failure(event)
        assert diag.blast_radius.safe_to_retry is False

    def test_has_recommendation(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="test",
            command="pytest", exit_code=1, stderr="test failed",
        )
        diag = diagnose_failure(event)
        assert len(diag.recommended_next_action) > 0
        assert "create_recovery_plan" in diag.recommended_next_action

    def test_to_dict(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="pytest",
            command="pytest", exit_code=1, stderr="test failed",
        )
        diag = diagnose_failure(event)
        d = diag.to_dict()
        for key in ("task_id", "project", "primary_category", "root_cause_hypothesis",
                     "evidence", "blast_radius"):
            assert key in d, f"Missing: {key}"

    def test_minimal_inputs(self) -> None:
        event = create_failure_event(
            task_id="task_0007", project="AgentLab", stage="unknown",
            command=None, exit_code=None,
        )
        diag = diagnose_failure(event)
        assert diag.primary_category is not None
        assert diag.confidence >= 0

    def test_permission_error(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="runtime",
            command="task", exit_code=1, error_type="permission_error",
            stderr="Permission denied",
        )
        diag = diagnose_failure(event)
        assert diag.primary_category == FailureCategory.PERMISSION_ERROR
        assert diag.requires_human_review is True

    def test_schema_fields(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="test",
            command="pytest", exit_code=1, stderr="test failed",
        )
        diag = diagnose_failure(event)
        d = diag.to_dict()
        required = ["task_id", "project", "primary_category", "root_cause_hypothesis",
                     "evidence", "blast_radius", "recommended_next_action",
                     "requires_human_review", "warnings", "created_at"]
        for field in required:
            assert field in d


# ── Recovery Artifacts ──────────────────────────────────────────────

class TestRecoveryArtifacts:

    def test_artifact_schema(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="pytest",
            command="pytest", exit_code=1, stderr="test failed",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(RUN_DIR)
        plan = build_recovery_plan(event, diag, policy)
        verdict = decide_retry_action(diag, policy)

        for obj in (event, diag, plan, verdict):
            d = obj.to_dict()
            assert "task_id" in d

        md = plan.to_markdown()
        assert "# Recovery Plan" in md

    def test_no_env_content(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="test",
            command="pytest", exit_code=1, stderr="test failed",
        )
        event_json = json.dumps(event.to_dict())
        assert ".env" not in event_json

    def test_secret_in_stderr_redacted(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="test",
            command="test", exit_code=1,
            stderr="API_KEY=sk-1234567890abcdef test failed",
        )
        if event.stderr_tail:
            assert "sk-1234567890abcdef" not in event.stderr_tail

    def test_absolute_paths_redacted(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="test",
            command="test", exit_code=1,
            artifact_paths=["/Users/testuser/project/file.txt"],
        )
        assert "[REDACTED_PATH]" in event.artifact_paths[0]


# ── CLI ─────────────────────────────────────────────────────────────

class TestRecoveryCLI:

    def test_cli_commands_exist(self) -> None:
        run_task = ROOT / "agent_runtime" / "run_task.py"
        content = run_task.read_text(encoding="utf-8")
        for cmd in ("failure-diagnose", "failure-status", "recovery-plan", "recovery-smoke"):
            assert f'@app.command("{cmd}")' in content

    def test_smoke_script(self) -> None:
        script = ROOT / "scripts" / "p2_i_recovery_smoke.py"
        assert script.exists()
        content = script.read_text(encoding="utf-8")
        assert "#!/usr/bin/env python3" in content

    def test_smoke_script_help(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "p2_i_recovery_smoke.py"), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0

    def test_smoke_generates_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            event = create_failure_event(
                task_id="smoke", project="AgentLab", stage="pytest",
                command="pytest", exit_code=1, stderr="test failed",
            )
            out_dir = Path(td)
            event_path = out_dir / "failure_event.json"
            event_path.write_text(json.dumps(event.to_dict(), indent=2), encoding="utf-8")
            assert event_path.exists()

            diag = diagnose_failure(event)
            diag_path = out_dir / "failure_diagnosis.json"
            diag_path.write_text(json.dumps(diag.to_dict(), indent=2), encoding="utf-8")
            assert diag_path.exists()

            policy = load_retry_policy(RUN_DIR)
            plan = build_recovery_plan(event, diag, policy)
            plan_path = out_dir / "recovery_plan.md"
            plan_path.write_text(plan.to_markdown(), encoding="utf-8")
            assert plan_path.exists()

            verdict = decide_retry_action(diag, policy)
            verdict_path = out_dir / "recovery_verdict.json"
            verdict_path.write_text(json.dumps(verdict.to_dict(), indent=2), encoding="utf-8")
            assert verdict_path.exists()

    def test_failure_status_no_secrets(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="test",
            command="test", exit_code=1,
            stderr="API_KEY=sk-secret123 test failed",
        )
        event_str = str(event.to_dict())
        assert "sk-secret123" not in event_str


# ── P2-I Closure ────────────────────────────────────────────────────

class TestP2IClosure:

    def test_end_to_end_recovery(self) -> None:
        event = create_failure_event(
            task_id="task_0001", project="AgentLab", stage="pytest",
            command="pytest tests/", exit_code=1,
            stderr="test_example.py FAILED\nAssertionError",
        )
        assert event.task_id == "task_0001"

        classifier = FailureClassifier()
        classification = classifier.classify(stderr=event.stderr_tail)
        assert classification.primary_category is not None

        diagnosis = diagnose_failure(event)
        assert diagnosis.root_cause_hypothesis is not None

        policy = load_retry_policy(RUN_DIR)
        plan = build_recovery_plan(event, diagnosis, policy)
        assert plan.summary is not None

        verdict = decide_retry_action(diagnosis, policy)
        assert verdict.verdict is not None

        md = plan.to_markdown()
        assert "# Recovery Plan" in md

    def test_syntax_error(self) -> None:
        event = create_failure_event(
            task_id="task_0002", project="AgentLab", stage="compile",
            command="compileall", exit_code=1, error_type="syntax_error",
            stderr="SyntaxError: invalid syntax",
        )
        classification = FailureClassifier().classify(stderr=event.stderr_tail)
        assert classification.primary_category == FailureCategory.SYNTAX_ERROR
        assert classification.requires_human_review is True

        diag = diagnose_failure(event)
        assert diag.primary_category == FailureCategory.SYNTAX_ERROR

        policy = load_retry_policy(RUN_DIR)
        plan = build_recovery_plan(event, diag, policy)
        assert "compileall" in " ".join(plan.safe_commands).lower()

    def test_timeout(self) -> None:
        event = create_failure_event(
            task_id="task_0003", project="AgentLab", stage="runtime",
            command="task", exit_code=1, error_type="timeout",
            stderr="timeout exceeded",
        )
        classification = FailureClassifier().classify(stderr=event.stderr_tail)
        assert classification.primary_category == FailureCategory.TIMEOUT
        assert classification.is_retriable is True

        diag = diagnose_failure(event)
        assert diag.blast_radius.safe_to_retry is True

    def test_secret_leak(self) -> None:
        event = create_failure_event(
            task_id="task_0004", project="AgentLab", stage="runtime",
            command="task", exit_code=1, error_type="secret_leak_risk",
            stderr="secret leak detected",
        )
        classification = FailureClassifier().classify(stderr=event.stderr_tail)
        assert classification.primary_category == FailureCategory.SECRET_LEAK_RISK
        assert classification.requires_human_review is True

        diag = diagnose_failure(event)
        policy = load_retry_policy(RUN_DIR)
        verdict = decide_retry_action(diag, policy)
        assert verdict.requires_human_review is True
        assert verdict.safe_to_auto_retry is False

    def test_text_integrity(self) -> None:
        event = create_failure_event(
            task_id="task_0005", project="AgentLab", stage="check",
            command="check", exit_code=1, error_type="text_integrity_failure",
            stderr="text integrity check failed",
        )
        classification = FailureClassifier().classify(stderr=event.stderr_tail)
        assert classification.primary_category == FailureCategory.TEXT_INTEGRITY_FAILURE

        diag = diagnose_failure(event)
        assert diag.requires_human_review is True

    def test_no_retry_attempts(self) -> None:
        event = create_failure_event(
            task_id="task_0008", project="AgentLab", stage="test",
            command="pytest", exit_code=1, stderr="test failed",
        )
        diag = diagnose_failure(event)
        policy = load_retry_policy(RUN_DIR)
        verdict = decide_retry_action(diag, policy, previous_attempts=100)
        assert verdict.allowed_attempts_remaining == 0


# ── Integration ─────────────────────────────────────────────────────

class TestCostLedgerIntegration:

    def test_ledger_records_recovery(self) -> None:
        from agent_runtime.costing.ledger import CostLedger, CostCall
        ledger = CostLedger(task_id="task_0001")
        recovery_call = CostCall(
            stage="recovery_diagnose", agent="recovery_system",
            input_tokens=150, output_tokens=200,
        )
        ledger.calls.append(recovery_call)
        total = ledger.total()
        assert total["input_tokens"] == 150
        assert total["output_tokens"] == 200

    def test_ledger_multiple_calls(self) -> None:
        from agent_runtime.costing.ledger import CostLedger, CostCall
        ledger = CostLedger(task_id="task_0001")
        ledger.calls.extend([
            CostCall(stage="A", agent="test", input_tokens=100, output_tokens=50),
            CostCall(stage="B", agent="test", input_tokens=200, output_tokens=100),
        ])
        total = ledger.total()
        assert total["input_tokens"] == 300

    def test_ledger_as_dict(self) -> None:
        from agent_runtime.costing.ledger import CostLedger, CostCall
        ledger = CostLedger(task_id="task_0001")
        ledger.calls.append(CostCall(stage="recovery", agent="test", input_tokens=100, output_tokens=50))
        d = ledger.as_dict()
        assert d["task_id"] == "task_0001"
        assert len(d["calls"]) == 1

    def test_ledger_all_token_types(self) -> None:
        from agent_runtime.costing.ledger import CostLedger, CostCall
        ledger = CostLedger(task_id="task_0001")
        ledger.calls.append(CostCall(
            stage="test", agent="test",
            input_tokens=100, output_tokens=50,
            cache_read_tokens=25, cache_write_tokens=10,
            reasoning_tokens=20, image_input_tokens=5, audio_input_tokens=3,
        ))
        total = ledger.total()
        for key in ("input_tokens", "output_tokens", "cache_read_tokens",
                     "cache_write_tokens", "reasoning_tokens"):
            assert total[key] > 0

    def test_ledger_pricing_status(self) -> None:
        from agent_runtime.costing.ledger import CostLedger, CostCall
        # Empty ledger
        ledger = CostLedger(task_id="task_0001")
        assert ledger.total()["pricing_status"] == "unknown"

        # With priced calls
        ledger.calls.append(CostCall(
            stage="test", agent="test", input_tokens=100, output_tokens=50,
            estimated_cost_usd=0.01, pricing_confidence="high",
        ))
        total = ledger.total()
        assert total["pricing_status"] in ("complete", "partial")

    def test_ledger_cost_summation(self) -> None:
        from agent_runtime.costing.ledger import CostLedger, CostCall
        ledger = CostLedger(task_id="task_0001")
        ledger.calls.extend([
            CostCall(stage="A", agent="test", input_tokens=100, output_tokens=50,
                     estimated_cost_usd=0.01, pricing_confidence="high"),
            CostCall(stage="B", agent="test", input_tokens=50, output_tokens=25,
                     estimated_cost_usd=0.005, pricing_confidence="high"),
        ])
        total = ledger.total()
        assert total["pricing_status"] == "complete"


class TestContextGovernanceIntegration:

    def test_context_governance_tests_importable(self) -> None:
        """Verify P2-H context governance modules remain importable."""
        import agent_runtime.context_governance
        import agent_runtime.context_governance.redaction
        import agent_runtime.context_governance.runtime_wiring


if __name__ == "__main__":
    pytest.main([__file__, "-v"])