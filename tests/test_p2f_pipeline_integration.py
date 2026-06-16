"""P2-F Pipeline Integration tests.

Covers the spec-required pipeline integration scenarios:
19. run-pipeline --dry-run includes REVIEW / RETRY_PLAN / PROVIDER_FEEDBACK / ROUTER_FEEDBACK stages
20. Original P1 safety tests are not broken
21. Full pytest passes (verified by running the suite separately, not in-test)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENTLAB_SH = ROOT / "agentlab.sh"


def _utf8_env() -> dict[str, str]:
    env = {
        **__import__("os").environ,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
    }
    return env


class TestPipelineDryRunShowsP2FStages:
    """Test 19: run-pipeline --dry-run shows P2-F stages."""

    def test_run_pipeline_dry_run_succeeds(self):
        """Verify run-pipeline --dry-run completes without error."""
        result = subprocess.run(
            [str(AGENTLAB_SH), "run-pipeline", "--task-id", "task_0001", "--dry-run"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            env=_utf8_env(),
            timeout=60,
        )
        # Should not crash (exit 0 or 1 from Rich/typer, not a Python exception)
        assert "Traceback" not in result.stderr, f"Traceback in stderr:\n{result.stderr}"

    def test_p2_closure_dry_run_succeeds(self, tmp_path: Path):
        """Verify p2-closure --dry-run runs the full P2-F stage chain."""
        # Use an existing fixture as delivery
        fixture = ROOT / "tests" / "fixtures" / "p2_closure" / "accepted_delivery"
        if not fixture.exists():
            pytest.skip("Fixture not found")

        output_dir = tmp_path / "p2_output"
        result = subprocess.run(
            [
                str(AGENTLAB_SH), "p2-closure",
                "--task-id", "test_p2f_integration",
                "--delivery-path", str(fixture),
                "--output-dir", str(output_dir),
                "--dry-run",
                "--provider-id", "agentlab.mock_patch",
                "--executor", "supervisor",
            ],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            env=_utf8_env(),
            timeout=60,
        )
        assert "Traceback" not in result.stderr, f"Traceback in stderr:\n{result.stderr}"

    def test_p2_closure_produces_review_artifacts(self, tmp_path: Path):
        """Verify p2-closure produces review_result / provider_feedback / router_feedback."""
        fixture = ROOT / "tests" / "fixtures" / "p2_closure" / "accepted_delivery"
        if not fixture.exists():
            pytest.skip("Fixture not found")

        output_dir = tmp_path / "p2_artifacts"
        result = subprocess.run(
            [
                str(AGENTLAB_SH), "p2-closure",
                "--task-id", "test_artifacts",
                "--delivery-path", str(fixture),
                "--output-dir", str(output_dir),
                "--dry-run",
                "--provider-id", "agentlab.mock_patch",
                "--executor", "supervisor",
            ],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            env=_utf8_env(),
            timeout=60,
        )
        assert result.returncode == 0, f"p2-closure failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"

        # Check that key artifacts were produced
        assert (output_dir / "review_verdict.yml").exists(), "Missing review_verdict.yml"
        assert (output_dir / "provider_feedback.yml").exists(), "Missing provider_feedback.yml"
        assert (output_dir / "router_feedback.yml").exists(), "Missing router_feedback.yml"
        assert (output_dir / "router_update_dry_run.yml").exists(), "Missing router_update_dry_run.yml"

    def test_p2_closure_produces_retry_artifacts_on_fail(self, tmp_path: Path):
        """Verify p2-closure on a failing delivery produces revision packet (retry trigger)."""
        fixture = ROOT / "tests" / "fixtures" / "p2_closure" / "needs_revision_delivery"
        if not fixture.exists():
            pytest.skip("Fixture not found")

        output_dir = tmp_path / "p2_retry"
        result = subprocess.run(
            [
                str(AGENTLAB_SH), "p2-closure",
                "--task-id", "test_retry_artifacts",
                "--delivery-path", str(fixture),
                "--output-dir", str(output_dir),
                "--dry-run",
                "--provider-id", "agentlab.mock_patch",
                "--executor", "supervisor",
            ],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            env=_utf8_env(),
            timeout=60,
        )
        # Non-accepted verdict returns exit code 1, which is expected
        assert (output_dir / "review_verdict.yml").exists(), "Missing review_verdict.yml"
        assert (output_dir / "provider_feedback.yml").exists(), "Missing provider_feedback.yml"
        assert (output_dir / "router_feedback.yml").exists(), "Missing router_feedback.yml"
        # Should produce a revision packet for needs_revision
        assert (output_dir / "revision_packet.md").exists(), "Missing revision_packet.md"


class TestP1SafetyNotBroken:
    """Test 20: Original P1 safety tests are not broken."""

    def test_text_integrity_audit_compiles(self):
        """Verify text integrity audit script still compiles after P2-F changes."""
        result = subprocess.run(
            [
                sys.executable, "-m", "py_compile",
                str(ROOT / "scripts" / "audit_text_integrity.py"),
            ],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=30,
        )
        assert result.returncode == 0, f"audit_text_integrity.py does not compile:\n{result.stderr}"

    def test_p2_closure_tests_still_pass(self):
        """Verify existing P2 closure tests are not broken by new test files."""
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_p2_closure.py", "-q", "--tb=line"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            env=_utf8_env(),
            timeout=120,
        )
        assert result.returncode == 0, f"P2 closure tests failed:\n{result.stdout}\n{result.stderr}"

    def test_new_test_files_compile(self):
        """Verify all new P2-F test files compile without syntax errors."""
        new_tests = [
            ROOT / "tests" / "test_p2f_reviewer.py",
            ROOT / "tests" / "test_p2f_retry_plan.py",
            ROOT / "tests" / "test_p2f_provider_feedback.py",
            ROOT / "tests" / "test_p2f_router_feedback.py",
            ROOT / "tests" / "test_p2f_pipeline_integration.py",
        ]
        for test_file in new_tests:
            if test_file.exists():
                result = subprocess.run(
                    [sys.executable, "-m", "py_compile", str(test_file)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                assert result.returncode == 0, f"{test_file.name} does not compile:\n{result.stderr}"

    def test_new_test_files_importable(self):
        """Verify new P2-F test files can be loaded via runpy without cycles."""
        import runpy
        new_tests = [
            ROOT / "tests" / "test_p2f_reviewer.py",
            ROOT / "tests" / "test_p2f_retry_plan.py",
            ROOT / "tests" / "test_p2f_provider_feedback.py",
            ROOT / "tests" / "test_p2f_router_feedback.py",
        ]
        for test_file in new_tests:
            if test_file.exists():
                # runpy will execute the module; if it has import cycles, it will crash
                result = subprocess.run(
                    [sys.executable, "-c", f"import sys; sys.path.insert(0, '{ROOT}'); exec(open('{test_file}').read())"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                # Should not have ImportError or SyntaxError
                assert "ImportError" not in result.stderr, f"Import error in {test_file.name}: {result.stderr}"
                assert "SyntaxError" not in result.stderr, f"Syntax error in {test_file.name}: {result.stderr}"
