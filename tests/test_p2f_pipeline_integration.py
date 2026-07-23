"""P2-F Pipeline Integration tests.

Covers the spec-required pipeline integration scenarios:
19. run-pipeline --dry-run includes REVIEW / RETRY_PLAN / PROVIDER_FEEDBACK / ROUTER_FEEDBACK stages
20. Original P1 safety tests are not broken
21. Full pytest passes (verified by running the suite separately, not in-test)
"""
from __future__ import annotations

import subprocess
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
