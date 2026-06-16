"""Tests for P2-I recovery text integrity.

Verifies that recovery modules meet text integrity requirements.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RECOVERY_DIR = ROOT / "agent_runtime" / "recovery"

CORE_MODULES = [
    "failure_event.py",
    "failure_classifier.py",
    "diagnosis.py",
    "recovery_plan.py",
    "retry_policy.py",
    "verdict.py",
]

TEST_FILES = [
    "test_failure_event_capture.py",
    "test_failure_classifier.py",
    "test_recovery_plan_retry.py",
    "test_p2_i_recovery.py",
    "test_recovery_costledger_integration.py",
]


class TestRecoveryTextIntegrity:

    @pytest.mark.parametrize("rel_path", CORE_MODULES)
    def test_core_module_valid_python(self, rel_path: str) -> None:
        path = RECOVERY_DIR / rel_path
        assert path.exists(), f"{rel_path} should exist"
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))
        lines = source.split("\n")
        assert len(lines) >= 30, f"{rel_path} should have >= 30 lines, has {len(lines)}"

    def test_init_exports_all_modules(self) -> None:
        init_path = RECOVERY_DIR / "__init__.py"
        source = init_path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(init_path))
        assert "__all__" in source
        for key in ("FailureEvent", "FailureClassifier", "FailureDiagnosis",
                     "RecoveryPlan", "RetryPolicyConfig", "RecoveryVerdict"):
            assert key in source

    def test_failure_event_has_redaction(self) -> None:
        path = RECOVERY_DIR / "failure_event.py"
        source = path.read_text(encoding="utf-8")
        assert "redact" in source.lower()

    def test_failure_classifier_has_categories(self) -> None:
        path = RECOVERY_DIR / "failure_classifier.py"
        source = path.read_text(encoding="utf-8")
        assert "FailureCategory" in source
        for cat in ("syntax_error", "test_failure", "timeout", "secret_leak_risk"):
            assert cat in source

    def test_diagnosis_has_hypothesis(self) -> None:
        path = RECOVERY_DIR / "diagnosis.py"
        source = path.read_text(encoding="utf-8")
        assert "root_cause_hypothesis" in source
        assert "evidence" in source

    def test_recovery_plan_has_markdown(self) -> None:
        path = RECOVERY_DIR / "recovery_plan.py"
        source = path.read_text(encoding="utf-8")
        assert "to_markdown" in source
        assert "safe_commands" in source

    def test_retry_policy_has_verdict(self) -> None:
        path = RECOVERY_DIR / "retry_policy.py"
        source = path.read_text(encoding="utf-8")
        assert "decide_retry_action" in source
        assert "VerdictType" in source

    def test_verdict_module_has_types(self) -> None:
        path = RECOVERY_DIR / "verdict.py"
        source = path.read_text(encoding="utf-8")
        assert "Retry" in source or "retry" in source
        assert "human_review" in source

    @pytest.mark.parametrize("tname", TEST_FILES)
    def test_file_exists_and_valid(self, tname: str) -> None:
        path = ROOT / "tests" / tname
        assert path.exists(), f"{tname} should exist"
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))
        lines = source.split("\n")
        assert len(lines) >= 30, f"{tname} should have >= 30 lines, has {len(lines)}"

    def test_config_file(self) -> None:
        path = ROOT / "config" / "failure_recovery.yml"
        assert path.exists()
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data is not None
        assert "enabled" in data

    def test_smoke_script(self) -> None:
        path = ROOT / "scripts" / "p2_i_recovery_smoke.py"
        assert path.exists()
        source = path.read_text(encoding="utf-8")
        assert "#!/usr/bin/env python3" in source
        ast.parse(source, filename=str(path))
        lines = source.split("\n")
        assert len(lines) >= 50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])