"""P2-F Provider Feedback tests.

Covers the spec-required provider feedback scenarios:
11. Review pass → provider outcome success
12. Review fail → provider outcome failed / needs_retry
13. Unknown provider does not crash
14. Feedback ledger is writable and readable
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_runtime.p2_closure.evidence import write_provider_feedback
from agent_runtime.p2_closure.models import ProviderFeedback


class TestProviderFeedbackOnPass:
    """Test 11: Review pass → provider outcome success."""

    def test_pass_review_sets_success(self, tmp_path: Path):
        output_path = tmp_path / "provider_feedback.yml"
        write_provider_feedback(
            task_id="test_pass",
            delivery_id="delivery_001",
            provider_id="deepseek-v4-pro",
            executor="deepseek",
            review_verdict="accepted",
            scores={"overall": 0.95, "artifact_completeness": 1.0, "test_confidence": 0.8, "safety_confidence": 1.0},
            failure_reasons=[],
            evidence_files=[str(tmp_path / "review_verdict.yml")],
            output_path=output_path,
        )
        assert output_path.exists()
        data = yaml.safe_load(output_path.read_text())
        assert data["retry_recommended"] is False
        assert data["governance_recommendation"] == "prefer"

    def test_pass_with_high_score_sets_prefer(self, tmp_path: Path):
        output_path = tmp_path / "provider_feedback.yml"
        write_provider_feedback(
            task_id="test_high",
            delivery_id="delivery_001",
            provider_id="qwen-max",
            executor="codex",
            review_verdict="accepted",
            scores={"overall": 0.9, "artifact_completeness": 1.0, "test_confidence": 1.0, "safety_confidence": 1.0},
            failure_reasons=[],
            evidence_files=[],
            output_path=output_path,
        )
        data = yaml.safe_load(output_path.read_text())
        assert data["governance_recommendation"] == "prefer"

    def test_pass_with_low_score_sets_neutral(self, tmp_path: Path):
        output_path = tmp_path / "provider_feedback.yml"
        write_provider_feedback(
            task_id="test_low_pass",
            delivery_id="delivery_001",
            provider_id="local_mock",
            executor="supervisor",
            review_verdict="accepted",
            scores={"overall": 0.5, "artifact_completeness": 0.5, "test_confidence": 0.3, "safety_confidence": 0.8},
            failure_reasons=[],
            evidence_files=[],
            output_path=output_path,
        )
        data = yaml.safe_load(output_path.read_text())
        assert data["governance_recommendation"] == "neutral"


class TestProviderFeedbackOnFail:
    """Test 12: Review fail → provider outcome failed / needs_retry."""

    def test_fail_review_sets_retry(self, tmp_path: Path):
        output_path = tmp_path / "provider_feedback.yml"
        write_provider_feedback(
            task_id="test_fail",
            delivery_id="delivery_001",
            provider_id="codex",
            executor="codex",
            review_verdict="needs_revision",
            scores={"overall": 0.2, "artifact_completeness": 0.3, "test_confidence": 0.0, "safety_confidence": 0.5},
            failure_reasons=["Missing required artifact: task_card.yml"],
            evidence_files=[],
            output_path=output_path,
        )
        data = yaml.safe_load(output_path.read_text())
        assert data["retry_recommended"] is True
        assert data["governance_recommendation"] == "watchlist"

    def test_needs_revision_sets_watchlist(self, tmp_path: Path):
        output_path = tmp_path / "provider_feedback.yml"
        write_provider_feedback(
            task_id="test_revision",
            delivery_id="delivery_001",
            provider_id="qwen",
            executor="supervisor",
            review_verdict="needs_revision",
            scores={"overall": 0.4, "artifact_completeness": 0.5, "test_confidence": 0.2, "safety_confidence": 0.7},
            failure_reasons=["Missing evidence"],
            evidence_files=[],
            output_path=output_path,
        )
        data = yaml.safe_load(output_path.read_text())
        assert data["retry_recommended"] is True
        assert data["governance_recommendation"] == "watchlist"

    def test_unsafe_sets_quarantine(self, tmp_path: Path):
        output_path = tmp_path / "provider_feedback.yml"
        write_provider_feedback(
            task_id="test_unsafe",
            delivery_id="delivery_001",
            provider_id="unknown",
            executor="unknown",
            review_verdict="unsafe",
            scores={"overall": 0.0, "artifact_completeness": 0.0, "test_confidence": 0.0, "safety_confidence": 0.0},
            failure_reasons=["Secret-like token found"],
            evidence_files=[],
            output_path=output_path,
        )
        data = yaml.safe_load(output_path.read_text())
        assert data["governance_recommendation"] == "quarantine"


class TestProviderFeedbackUnknownProvider:
    """Test 13: Unknown provider does not crash."""

    def test_unknown_provider_does_not_crash(self, tmp_path: Path):
        output_path = tmp_path / "provider_feedback.yml"
        write_provider_feedback(
            task_id="test_unknown",
            delivery_id="delivery_001",
            provider_id="unknown",
            executor="unknown",
            review_verdict="needs_revision",
            scores={"overall": 0.3},
            failure_reasons=[],
            evidence_files=[],
            output_path=output_path,
        )
        assert output_path.exists()
        data = yaml.safe_load(output_path.read_text())
        assert data["provider_id"] == "unknown"

    def test_empty_provider_id_does_not_crash(self, tmp_path: Path):
        output_path = tmp_path / "provider_feedback.yml"
        write_provider_feedback(
            task_id="test_empty",
            delivery_id="delivery_001",
            provider_id="",
            executor="",
            review_verdict="accepted",
            scores={"overall": 0.7},
            failure_reasons=[],
            evidence_files=[],
            output_path=output_path,
        )
        assert output_path.exists()


class TestProviderFeedbackLedger:
    """Test 14: Feedback ledger is writable and readable."""

    def test_feedback_file_is_valid_yaml(self, tmp_path: Path):
        output_path = tmp_path / "provider_feedback.yml"
        write_provider_feedback(
            task_id="test_yaml",
            delivery_id="delivery_001",
            provider_id="deepseek",
            executor="deepseek",
            review_verdict="accepted",
            scores={"overall": 0.8},
            failure_reasons=[],
            evidence_files=[],
            output_path=output_path,
        )
        # Should be valid YAML
        data = yaml.safe_load(output_path.read_text())
        assert isinstance(data, dict)
        assert "task_id" in data
        assert "created_at" in data

    def test_feedback_has_all_required_fields(self, tmp_path: Path):
        output_path = tmp_path / "provider_feedback.yml"
        write_provider_feedback(
            task_id="test_fields",
            delivery_id="delivery_001",
            provider_id="qwen",
            executor="codex",
            review_verdict="accepted",
            scores={"overall": 0.9, "artifact_completeness": 1.0, "test_confidence": 0.8, "safety_confidence": 1.0},
            failure_reasons=[],
            evidence_files=["evidence1", "evidence2"],
            output_path=output_path,
        )
        data = yaml.safe_load(output_path.read_text())
        required = [
            "task_id", "delivery_id", "provider_id", "executor",
            "review_verdict", "quality_score", "artifact_completeness",
            "test_confidence", "safety_confidence", "retry_recommended",
            "failure_reasons", "governance_recommendation", "created_at",
        ]
        for field in required:
            assert field in data, f"Missing field: {field}"

    def test_multiple_feedbacks_can_be_written(self, tmp_path: Path):
        """Verify we can write multiple feedback files without conflict."""
        for i in range(3):
            output_path = tmp_path / f"provider_feedback_{i}.yml"
            write_provider_feedback(
                task_id=f"test_{i}",
                delivery_id=f"delivery_{i}",
                provider_id=f"provider_{i}",
                executor="mock",
                review_verdict="accepted",
                scores={"overall": 0.8},
                failure_reasons=[],
                evidence_files=[],
                output_path=output_path,
            )
            assert output_path.exists()
