"""Tests for P2-G Autonomous Task Smoke end-to-end demo."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SMOKE_DIR = ROOT / "acceptance_runs" / "p2g_autonomous_task_smoke"


class TestP2GSmokeRunDirectory:
    """Verify the acceptance run directory exists and contains expected artifacts."""

    def test_acceptance_run_directory_exists(self):
        assert SMOKE_DIR.is_dir(), f"Smoke run directory missing: {SMOKE_DIR}"

    def test_input_task_exists_and_nonempty(self):
        path = SMOKE_DIR / "input_task.md"
        assert path.exists(), f"Missing: {path}"
        text = path.read_text(encoding="utf-8")
        assert len(text) > 50, "input_task.md is too short"
        assert "Task Description" in text or "task" in text.lower()

    def test_task_plan_exists(self):
        path = SMOKE_DIR / "task_plan.yml"
        assert path.exists(), f"Missing: {path}"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data is not None, "task_plan.yml is empty"
        assert "task_id" in data

    def test_run_commands_exists_and_nonempty(self):
        path = SMOKE_DIR / "run_commands.md"
        assert path.exists(), f"Missing: {path}"
        text = path.read_text(encoding="utf-8")
        assert len(text) > 50, "run_commands.md is too short"
        assert "Commands" in text or "command" in text.lower()


class TestP2GArtifactsManifest:
    """Verify artifacts_manifest.yml lists all key artifacts."""

    def test_artifacts_manifest_exists(self):
        path = SMOKE_DIR / "artifacts_manifest.yml"
        assert path.exists(), f"Missing: {path}"

    def test_artifacts_manifest_lists_key_artifacts(self):
        path = SMOKE_DIR / "artifacts_manifest.yml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data is not None
        assert "artifacts" in data, "artifacts_manifest.yml must have 'artifacts' key"
        artifacts = data["artifacts"]
        # Check closure and feedback sections exist
        assert "closure" in artifacts, "Must list closure artifacts"
        assert "feedback" in artifacts, "Must list feedback artifacts"

    def test_artifacts_completeness_scored(self):
        path = SMOKE_DIR / "artifacts_manifest.yml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "completeness" in data, "Must have completeness score"
        assert "score" in data["completeness"]


class TestP2GClosureReport:
    """Verify p2_closure_report.md exists and contains verdict."""

    def test_p2_closure_report_exists(self):
        path = SMOKE_DIR / "p2_closure_report.md"
        assert path.exists(), f"Missing: {path}"

    def test_p2_closure_report_has_verdict(self):
        path = SMOKE_DIR / "p2_closure_report.md"
        text = path.read_text(encoding="utf-8")
        # Must contain a verdict keyword
        verdicts = ["accepted", "needs_revision", "rejected", "unsafe", "BLOCKED", "PASS", "FAIL"]
        assert any(v.lower() in text.lower() for v in verdicts), \
            f"p2_closure_report.md must contain a verdict, found none of: {verdicts}"

    def test_p2_closure_report_has_pipeline_steps(self):
        path = SMOKE_DIR / "p2_closure_report.md"
        text = path.read_text(encoding="utf-8")
        # Must mention key pipeline stages
        assert "Review" in text or "review" in text, "Must mention review step"
        assert "Router" in text or "router" in text, "Must mention router feedback"
        assert "Governance" in text or "governance" in text, "Must mention governance"


class TestP2GFinalDeliveryReport:
    """Verify final_delivery_report.md exists and is user-readable."""

    def test_final_delivery_report_exists(self):
        path = SMOKE_DIR / "final_delivery_report.md"
        assert path.exists(), f"Missing: {path}"

    def test_final_delivery_report_has_user_summary(self):
        path = SMOKE_DIR / "final_delivery_report.md"
        text = path.read_text(encoding="utf-8")
        # Must have executive summary or similar user-readable section
        assert "Summary" in text or "summary" in text or "Overview" in text, \
            "final_delivery_report.md must have a summary section"

    def test_final_delivery_report_has_quality_assessment(self):
        path = SMOKE_DIR / "final_delivery_report.md"
        text = path.read_text(encoding="utf-8")
        # Must discuss quality or scores
        assert "quality" in text.lower() or "score" in text.lower() or "Score" in text, \
            "final_delivery_report.md must discuss quality/scores"

    def test_final_delivery_report_explain_verdict(self):
        path = SMOKE_DIR / "final_delivery_report.md"
        text = path.read_text(encoding="utf-8")
        # Must explain why verdict was what it was
        assert "rejected" in text.lower() or "accepted" in text.lower() or "revision" in text.lower(), \
            "final_delivery_report.md must explain the verdict"


class TestP2GRouterFeedback:
    """Verify router_feedback.yml exists and is valid YAML."""

    def test_router_feedback_exists(self):
        path = SMOKE_DIR / "router_feedback.yml"
        assert path.exists(), f"Missing: {path}"

    def test_router_feedback_is_valid_yaml(self):
        path = SMOKE_DIR / "router_feedback.yml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data is not None, "router_feedback.yml is empty"
        assert isinstance(data, dict), "router_feedback.yml must be a dict"

    def test_router_feedback_has_recommendation(self):
        path = SMOKE_DIR / "router_feedback.yml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "recommendation" in data, "router_feedback.yml must have recommendation"
        valid_recs = {"quarantine", "watchlist", "prefer", "neutral", "insufficient_data"}
        assert data["recommendation"] in valid_recs, \
            f"Invalid recommendation: {data['recommendation']}, expected one of {valid_recs}"

    def test_router_feedback_has_provider_info(self):
        path = SMOKE_DIR / "router_feedback.yml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "provider_id" in data, "router_feedback.yml must have provider_id"
        assert data["provider_id"] == "mock_executor"


class TestP2GGovernanceFeedback:
    """Verify governance_feedback.yml exists and is valid YAML."""

    def test_governance_feedback_exists(self):
        path = SMOKE_DIR / "governance_feedback.yml"
        assert path.exists(), f"Missing: {path}"

    def test_governance_feedback_is_valid_yaml(self):
        path = SMOKE_DIR / "governance_feedback.yml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data is not None, "governance_feedback.yml is empty"
        assert isinstance(data, dict), "governance_feedback.yml must be a dict"

    def test_governance_feedback_has_cost_compliance(self):
        path = SMOKE_DIR / "governance_feedback.yml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "cost_compliance" in data, "governance_feedback.yml must have cost_compliance"
        cost = data["cost_compliance"]
        assert "estimated_cost_usd" in cost or "within_budget" in cost, \
            "cost_compliance must have cost or budget info"

    def test_governance_feedback_has_governance_decision(self):
        path = SMOKE_DIR / "governance_feedback.yml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "governance_decision" in data, "governance_feedback.yml must have governance_decision"
        decision = data["governance_decision"]
        assert "status" in decision, "governance_decision must have status"
        assert "recommendation" in decision, "governance_decision must have recommendation"


class TestP2GKnownLimits:
    """Verify known_limits.md documents real external execution as disabled."""

    def test_known_limits_exists(self):
        path = SMOKE_DIR / "known_limits.md"
        assert path.exists(), f"Missing: {path}"

    def test_known_limits_mentions_external_execution(self):
        path = SMOKE_DIR / "known_limits.md"
        text = path.read_text(encoding="utf-8")
        assert "external execution" in text.lower() or "external agents" in text.lower() or "External Execution" in text, \
            "known_limits.md must mention real external execution is not enabled"

    def test_known_limits_mentions_api_or_network(self):
        path = SMOKE_DIR / "known_limits.md"
        text = path.read_text(encoding="utf-8")
        lower = text.lower()
        assert "api" in lower or "network" in lower or "model" in lower, \
            "known_limits.md must mention real API/network/model limitations"


class TestP2GTextIntegrity:
    """Verify P2-G artifacts pass text integrity checks."""

    def test_new_files_are_multiline(self):
        """All P2-G artifacts should have reasonable line counts."""
        files = [
            SMOKE_DIR / "input_task.md",
            SMOKE_DIR / "task_plan.yml",
            SMOKE_DIR / "run_commands.md",
            SMOKE_DIR / "artifacts_manifest.yml",
            SMOKE_DIR / "p2_closure_report.md",
            SMOKE_DIR / "revision_feedback.yml",
            SMOKE_DIR / "governance_feedback.yml",
            SMOKE_DIR / "router_feedback.yml",
            SMOKE_DIR / "final_delivery_report.md",
            SMOKE_DIR / "known_limits.md",
        ]
        for path in files:
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines()
            max_len = max((len(x) for x in lines), default=0)
            assert len(lines) >= 5, f"{path.name}: only {len(lines)} lines — suspicious"
            assert max_len < 2000, f"{path.name}: max line {max_len} chars — suspicious"

    def test_no_real_api_secrets_in_artifacts(self):
        """P2-G artifact files must not contain real API keys, secrets, or network calls."""
        import re
        # Patterns that indicate real secrets (avoid CLI flag false positives)
        secret_patterns = [
            (r"\bsk-[A-Za-z0-9]", "OpenAI-style API key"),
            (r"\bghp_[A-Za-z0-9]", "GitHub personal access token"),
        ]
        network_patterns = [
            "localhost:8080",
            "127.0.0.1",
        ]
        for path in SMOKE_DIR.iterdir():
            if not path.is_file():
                continue
            if path.name.startswith("test_"):
                continue
            text = path.read_text(encoding="utf-8")
            for pattern, desc in secret_patterns:
                match = re.search(pattern, text)
                assert match is None, \
                    f"{path.name} contains {desc}: {match.group() if match else pattern}"
            for pattern in network_patterns:
                assert pattern not in text, \
                    f"{path.name} contains {pattern}"


class TestP2GNoExternalDependencies:
    """Verify P2-G does not introduce real external dependencies."""

    def test_no_network_imports_in_test_file(self):
        """The test file itself must not import network libraries."""
        import ast
        test_file = Path(__file__)
        tree = ast.parse(test_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in ("requests", "httpx", "aiohttp"), \
                        f"Test file must not import {alias.name}"
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] in ("requests", "httpx", "aiohttp"):
                    assert False, f"Test file must not import from {node.module}"

    def test_no_subprocess_calls(self):
        """No subprocess calls in the test file."""
        import ast
        test_file = Path(__file__)
        tree = ast.parse(test_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if node.attr in ("run", "Popen", "call", "check_output"):
                    if isinstance(node.value, ast.Name) and node.value.id == "subprocess":
                        assert False, f"Test file must not call subprocess.{node.attr}"
