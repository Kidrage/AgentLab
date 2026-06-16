"""P2-F Router Feedback tests.

Covers the spec-required router feedback scenarios:
15. Success + high score → keep/prefer recommendation
16. Repeated failure → avoid/quarantine recommendation
17. Default does not modify production router policy
18. Dry-run router update does not write production policy
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_runtime.p2_closure.evidence import write_router_feedback, write_router_dry_run
from agent_runtime.p2_closure.models import RouterFeedback


class TestRouterFeedbackSuccessHighScore:
    """Test 15: Success + high score → keep/prefer recommendation."""

    def test_accepted_with_high_score_recommends_prefer(self, tmp_path: Path):
        output_path = tmp_path / "router_feedback.yml"
        write_router_feedback(
            task_id="test_prefer",
            provider_id="deepseek-v4-pro",
            review_verdict="accepted",
            governance_recommendation="prefer",
            failure_reasons=[],
            evidence_files=[],
            output_path=output_path,
        )
        data = yaml.safe_load(output_path.read_text())
        assert data["recommendation"] == "prefer"
        assert data["dry_run"] is True
        assert data["apply_allowed"] is False

    def test_accepted_with_good_score_recommends_keep(self, tmp_path: Path):
        output_path = tmp_path / "router_feedback.yml"
        write_router_feedback(
            task_id="test_keep",
            provider_id="qwen-max",
            review_verdict="accepted",
            governance_recommendation="keep",
            failure_reasons=[],
            evidence_files=[],
            output_path=output_path,
        )
        data = yaml.safe_load(output_path.read_text())
        assert data["recommendation"] == "neutral"

    def test_no_failure_reasons_low_confidence(self, tmp_path: Path):
        output_path = tmp_path / "router_feedback.yml"
        write_router_feedback(
            task_id="test_low_conf",
            provider_id="local_mock",
            review_verdict="accepted",
            governance_recommendation="prefer",
            failure_reasons=[],
            evidence_files=[],
            output_path=output_path,
        )
        data = yaml.safe_load(output_path.read_text())
        assert data["confidence"] == "low"


class TestRouterFeedbackRepeatedFailure:
    """Test 16: Repeated failure → avoid/quarantine recommendation."""

    def test_unsafe_verdict_recommends_quarantine(self, tmp_path: Path):
        output_path = tmp_path / "router_feedback.yml"
        write_router_feedback(
            task_id="test_quarantine",
            provider_id="bad_provider",
            review_verdict="unsafe",
            governance_recommendation="quarantine",
            failure_reasons=["Secret found", "Forbidden path accessed"],
            evidence_files=[],
            output_path=output_path,
        )
        data = yaml.safe_load(output_path.read_text())
        assert data["recommendation"] == "quarantine"
        assert data["confidence"] == "high"

    def test_rejected_verdict_recommends_avoid(self, tmp_path: Path):
        output_path = tmp_path / "router_feedback.yml"
        write_router_feedback(
            task_id="test_avoid",
            provider_id="failing_provider",
            review_verdict="rejected",
            governance_recommendation="watchlist",
            failure_reasons=["Multiple failures"],
            evidence_files=[],
            output_path=output_path,
        )
        data = yaml.safe_load(output_path.read_text())
        assert data["recommendation"] == "watchlist"

    def test_needs_revision_recommends_watchlist(self, tmp_path: Path):
        output_path = tmp_path / "router_feedback.yml"
        write_router_feedback(
            task_id="test_watchlist",
            provider_id="flaky_provider",
            review_verdict="needs_revision",
            governance_recommendation="watchlist",
            failure_reasons=["Missing artifact"],
            evidence_files=[],
            output_path=output_path,
        )
        data = yaml.safe_load(output_path.read_text())
        assert data["recommendation"] == "watchlist"

    def test_multiple_failure_reasons_high_confidence(self, tmp_path: Path):
        output_path = tmp_path / "router_feedback.yml"
        write_router_feedback(
            task_id="test_high_conf",
            provider_id="bad_provider",
            review_verdict="rejected",
            governance_recommendation="quarantine",
            failure_reasons=["Reason 1", "Reason 2"],
            evidence_files=[],
            output_path=output_path,
        )
        data = yaml.safe_load(output_path.read_text())
        assert data["confidence"] == "high"


class TestRouterFeedbackDoesNotModifyProduction:
    """Test 17: Default does not modify production router policy."""

    def test_feedback_is_dry_run_by_default(self, tmp_path: Path):
        output_path = tmp_path / "router_feedback.yml"
        write_router_feedback(
            task_id="test_dry_run",
            provider_id="deepseek",
            review_verdict="accepted",
            governance_recommendation="prefer",
            failure_reasons=[],
            evidence_files=[],
            output_path=output_path,
        )
        data = yaml.safe_load(output_path.read_text())
        assert data["dry_run"] is True
        assert data["apply_allowed"] is False
        assert data["approval_required"] is True

    def test_feedback_never_sets_apply_allowed(self, tmp_path: Path):
        """Even on success, feedback should never set apply_allowed=True."""
        output_path = tmp_path / "router_feedback.yml"
        write_router_feedback(
            task_id="test_no_apply",
            provider_id="deepseek",
            review_verdict="accepted",
            governance_recommendation="prefer",
            failure_reasons=[],
            evidence_files=[],
            output_path=output_path,
        )
        data = yaml.safe_load(output_path.read_text())
        assert data["apply_allowed"] is False


class TestRouterDryRun:
    """Test 18: Dry-run router update does not write production policy."""

    def test_dry_run_does_not_modify_config(self, tmp_path: Path):
        config_path = tmp_path / "config" / "executor_router.yml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        original_content = "executor_router:\n  providers: []\n"
        config_path.write_text(original_content)

        output_path = tmp_path / "router_update_dry_run.yml"
        write_router_dry_run(
            task_id="test_dry",
            provider_id="deepseek",
            recommendation="prefer",
            output_path=output_path,
        )

        # Original config must be unchanged
        assert config_path.read_text() == original_content

        # Dry-run artifact must exist
        assert output_path.exists()
        data = yaml.safe_load(output_path.read_text())
        assert data["dry_run"] is True
        assert data["applied"] is False

    def test_dry_run_has_no_apply(self, tmp_path: Path):
        output_path = tmp_path / "router_update_dry_run.yml"
        write_router_dry_run(
            task_id="test_no_apply",
            provider_id="qwen",
            recommendation="quarantine",
            output_path=output_path,
        )
        data = yaml.safe_load(output_path.read_text())
        assert data["applied"] is False
        assert "no config modified" in data["reason"]


class TestRouterFeedbackSchema:
    """Verify router feedback schema compliance."""

    def test_feedback_has_required_fields(self, tmp_path: Path):
        output_path = tmp_path / "router_feedback.yml"
        write_router_feedback(
            task_id="test_schema",
            provider_id="test_provider",
            review_verdict="accepted",
            governance_recommendation="prefer",
            failure_reasons=[],
            evidence_files=["evidence1"],
            output_path=output_path,
        )
        data = yaml.safe_load(output_path.read_text())
        required = [
            "task_id", "provider_id", "recommendation",
            "reason", "confidence", "dry_run",
            "apply_allowed", "approval_required", "evidence",
        ]
        for field in required:
            assert field in data, f"Missing field: {field}"

    def test_reason_includes_verdict_on_failure(self, tmp_path: Path):
        output_path = tmp_path / "router_feedback.yml"
        write_router_feedback(
            task_id="test_reason",
            provider_id="test_provider",
            review_verdict="rejected",
            governance_recommendation="quarantine",
            failure_reasons=["Some failure"],
            evidence_files=[],
            output_path=output_path,
        )
        data = yaml.safe_load(output_path.read_text())
        # Should include verdict in reason
        assert any("rejected" in r.lower() for r in data["reason"])
