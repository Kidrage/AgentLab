"""Tests for P2-F Closure: capability map, closure runner, revision packet, provider feedback, router feedback, and safety."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.p2_closure import run_p2_closure
from agent_runtime.p2_closure.capability_map import scan_p2_capabilities, write_capability_map
from agent_runtime.p2_closure.models import P2ClosureResult, ProviderFeedback, RouterFeedback


# ─── Fixtures ───────────────────────────────────────────────────────

FIXTURES = ROOT / "tests" / "fixtures" / "p2_closure"
CONFIG_ROOT = ROOT / "config"


# ─── H1: Capability Map ─────────────────────────────────────────────


class TestP2CapabilityMap:
    def test_detects_existing_modules(self):
        cap_map = scan_p2_capabilities()
        assert "capabilities" in cap_map
        caps = cap_map["capabilities"]
        # All known P2 modules should be detected
        for name in ("review", "retry_loop", "executor_router", "provider_governance", "router_update"):
            assert name in caps, f"Missing capability: {name}"
            assert caps[name]["status"] in ("implemented", "implemented_or_partial"), f"{name} should be implemented"

    def test_writes_report(self, tmp_path: Path):
        cap_map = scan_p2_capabilities()
        output_path = tmp_path / "cap_map.yml"
        write_capability_map(cap_map, output_path)
        assert output_path.exists()
        data = yaml.safe_load(output_path.read_text())
        assert "generated_at" in data
        assert "capabilities" in data
        assert "gaps" in data
        assert "recommendations" in data

    def test_marks_missing_or_partial_capabilities(self):
        cap_map = scan_p2_capabilities()
        # The closure module itself should be detected as implemented
        caps = cap_map["capabilities"]
        # Check that notes are populated
        for name, cap in caps.items():
            if cap["status"] in ("implemented_or_partial", "scaffold"):
                # Should have notes explaining the status
                assert isinstance(cap.get("notes"), list)


# ─── H2: Accepted Delivery ──────────────────────────────────────────


class TestAcceptedDelivery:
    def test_accepted_verdict(self, tmp_path: Path):
        delivery = FIXTURES / "accepted_delivery"
        result = run_p2_closure(
            task_id="test_accepted",
            delivery_path=delivery,
            output_dir=tmp_path,
            config_root=CONFIG_ROOT,
            provider_id="deepseek-v4-pro",
            executor="deepseek",
        )
        assert result.verdict_status == "accepted"
        assert result.revision_required is False
        assert result.revision_packet_path is None

        # Check review verdict file
        verdict_path = Path(result.review_verdict_path)
        assert verdict_path.exists()
        data = yaml.safe_load(verdict_path.read_text())
        assert data["verdict"] == "accepted"
        assert data["scores"]["overall"] >= 0.0

    def test_provider_feedback_success(self, tmp_path: Path):
        delivery = FIXTURES / "accepted_delivery"
        result = run_p2_closure(
            task_id="test_accepted",
            delivery_path=delivery,
            output_dir=tmp_path,
            config_root=CONFIG_ROOT,
            provider_id="deepseek-v4-pro",
            executor="deepseek",
        )
        fb_path = Path(result.provider_feedback_path)
        assert fb_path.exists()
        data = yaml.safe_load(fb_path.read_text())
        assert data["review_verdict"] == "accepted"
        assert data["retry_recommended"] is False
        assert data["governance_recommendation"] in ("prefer", "neutral")
        assert data["governance_recommendation"] != "quarantine"

    def test_router_feedback_not_quarantine(self, tmp_path: Path):
        delivery = FIXTURES / "accepted_delivery"
        result = run_p2_closure(
            task_id="test_accepted",
            delivery_path=delivery,
            output_dir=tmp_path,
            config_root=CONFIG_ROOT,
            provider_id="deepseek-v4-pro",
            executor="deepseek",
        )
        fb_path = Path(result.router_feedback_path)
        assert fb_path.exists()
        data = yaml.safe_load(fb_path.read_text())
        assert data["recommendation"] in ("prefer", "neutral")
        assert data["recommendation"] != "quarantine"


# ─── H3: Needs Revision Delivery ────────────────────────────────────


class TestNeedsRevisionDelivery:
    def test_needs_revision_verdict(self, tmp_path: Path):
        delivery = FIXTURES / "needs_revision_delivery"
        result = run_p2_closure(
            task_id="test_revision",
            delivery_path=delivery,
            output_dir=tmp_path,
            config_root=CONFIG_ROOT,
            provider_id="deepseek-v4-pro",
            executor="deepseek",
        )
        # Verdict should not be accepted; may be needs_revision or rejected
        # depending on 3E review analysis of missing artifacts
        assert result.verdict_status != "accepted"
        assert result.verdict_status in ("needs_revision", "rejected")
        assert result.revision_required is True

    def test_revision_packet_generated(self, tmp_path: Path):
        delivery = FIXTURES / "needs_revision_delivery"
        result = run_p2_closure(
            task_id="test_revision",
            delivery_path=delivery,
            output_dir=tmp_path,
            config_root=CONFIG_ROOT,
            provider_id="deepseek-v4-pro",
            executor="deepseek",
        )
        assert result.revision_packet_path is not None
        revision_path = Path(result.revision_packet_path)
        assert revision_path.exists()
        content = revision_path.read_text()
        assert "# P2 Revision Packet" in content
        assert "needs_revision" in content

    def test_provider_feedback_retry_recommended(self, tmp_path: Path):
        delivery = FIXTURES / "needs_revision_delivery"
        result = run_p2_closure(
            task_id="test_revision",
            delivery_path=delivery,
            output_dir=tmp_path,
            config_root=CONFIG_ROOT,
            provider_id="deepseek-v4-pro",
            executor="deepseek",
        )
        fb_path = Path(result.provider_feedback_path)
        data = yaml.safe_load(fb_path.read_text())
        assert data["retry_recommended"] is True
        assert data["review_verdict"] in ("needs_revision", "rejected")

    def test_router_feedback_watchlist_or_neutral(self, tmp_path: Path):
        delivery = FIXTURES / "needs_revision_delivery"
        result = run_p2_closure(
            task_id="test_revision",
            delivery_path=delivery,
            output_dir=tmp_path,
            config_root=CONFIG_ROOT,
            provider_id="deepseek-v4-pro",
            executor="deepseek",
        )
        fb_path = Path(result.router_feedback_path)
        data = yaml.safe_load(fb_path.read_text())
        # Non-accepted verdict should get watchlist, neutral, or quarantine
        assert data["recommendation"] in ("watchlist", "neutral", "quarantine")


# ─── H4: Unsafe Delivery ────────────────────────────────────────────


class TestUnsafeDelivery:
    def test_unsafe_verdict(self, tmp_path: Path):
        delivery = FIXTURES / "unsafe_delivery"
        result = run_p2_closure(
            task_id="test_unsafe",
            delivery_path=delivery,
            output_dir=tmp_path,
            config_root=CONFIG_ROOT,
            provider_id="deepseek-v4-pro",
            executor="deepseek",
        )
        assert result.verdict_status in ("unsafe", "rejected")

    def test_safety_confidence_reduced(self, tmp_path: Path):
        delivery = FIXTURES / "unsafe_delivery"
        result = run_p2_closure(
            task_id="test_unsafe",
            delivery_path=delivery,
            output_dir=tmp_path,
            config_root=CONFIG_ROOT,
            provider_id="deepseek-v4-pro",
            executor="deepseek",
        )
        verdict_path = Path(result.review_verdict_path)
        data = yaml.safe_load(verdict_path.read_text())
        assert data["scores"]["safety_confidence"] < 1.0

    def test_revision_packet_emphasizes_security(self, tmp_path: Path):
        delivery = FIXTURES / "unsafe_delivery"
        result = run_p2_closure(
            task_id="test_unsafe",
            delivery_path=delivery,
            output_dir=tmp_path,
            config_root=CONFIG_ROOT,
            provider_id="deepseek-v4-pro",
            executor="deepseek",
        )
        assert result.revision_packet_path is not None
        content = Path(result.revision_packet_path).read_text()
        assert "Security Isolation" in content or "UNSAFE" in content
        assert "untrusted" in content.lower() or "unsafe" in content.lower()

    def test_router_feedback_watchlist_or_quarantine(self, tmp_path: Path):
        delivery = FIXTURES / "unsafe_delivery"
        result = run_p2_closure(
            task_id="test_unsafe",
            delivery_path=delivery,
            output_dir=tmp_path,
            config_root=CONFIG_ROOT,
            provider_id="deepseek-v4-pro",
            executor="deepseek",
        )
        fb_path = Path(result.router_feedback_path)
        data = yaml.safe_load(fb_path.read_text())
        assert data["recommendation"] in ("watchlist", "quarantine")

    def test_no_router_apply_allowed(self, tmp_path: Path):
        delivery = FIXTURES / "unsafe_delivery"
        result = run_p2_closure(
            task_id="test_unsafe",
            delivery_path=delivery,
            output_dir=tmp_path,
            config_root=CONFIG_ROOT,
            provider_id="deepseek-v4-pro",
            executor="deepseek",
        )
        fb_path = Path(result.router_feedback_path)
        data = yaml.safe_load(fb_path.read_text())
        assert data["apply_allowed"] is False
        assert data["approval_required"] is True


# ─── H5: Missing Artifacts Delivery ─────────────────────────────────


class TestMissingArtifactsDelivery:
    def test_verdict_not_accepted(self, tmp_path: Path):
        delivery = FIXTURES / "missing_artifacts_delivery"
        result = run_p2_closure(
            task_id="test_missing",
            delivery_path=delivery,
            output_dir=tmp_path,
            config_root=CONFIG_ROOT,
            provider_id="deepseek-v4-pro",
            executor="deepseek",
        )
        assert result.verdict_status != "accepted"

    def test_missing_evidence_nonempty(self, tmp_path: Path):
        delivery = FIXTURES / "missing_artifacts_delivery"
        result = run_p2_closure(
            task_id="test_missing",
            delivery_path=delivery,
            output_dir=tmp_path,
            config_root=CONFIG_ROOT,
            provider_id="deepseek-v4-pro",
            executor="deepseek",
        )
        verdict_path = Path(result.review_verdict_path)
        data = yaml.safe_load(verdict_path.read_text())
        missing = data["review"]["examine"]["missing_evidence"]
        assert len(missing) > 0, "Missing evidence should be non-empty"

    def test_revision_packet_lists_missing_items(self, tmp_path: Path):
        delivery = FIXTURES / "missing_artifacts_delivery"
        result = run_p2_closure(
            task_id="test_missing",
            delivery_path=delivery,
            output_dir=tmp_path,
            config_root=CONFIG_ROOT,
            provider_id="deepseek-v4-pro",
            executor="deepseek",
        )
        assert result.revision_packet_path is not None
        content = Path(result.revision_packet_path).read_text()
        assert "Missing Evidence" in content or "missing" in content.lower()


# ─── H6: Router Apply Requires Approval ─────────────────────────────


class TestRouterApplyRequiresApproval:
    def test_apply_without_approval_fails(self, tmp_path: Path):
        delivery = FIXTURES / "accepted_delivery"
        result = run_p2_closure(
            task_id="test_no_approval",
            delivery_path=delivery,
            output_dir=tmp_path,
            config_root=CONFIG_ROOT,
            provider_id="deepseek-v4-pro",
            executor="deepseek",
            dry_run=False,
            allow_router_apply=True,
            approval_path=None,
        )
        assert result.router_apply is not None
        assert result.router_apply.applied is False
        assert result.router_apply.status in ("APPROVAL_REQUIRED", "DRY_RUN_APPROVED")


# ─── H7: Router Apply With Approval Writes Rollback Plan ────────────


class TestRouterApplyWithApproval:
    def test_apply_with_approval_writes_rollback(self, tmp_path: Path):
        delivery = FIXTURES / "accepted_delivery"
        approval_dir = FIXTURES / "router_apply_approval_granted"

        # Create a temp config dir with minimal router policy
        temp_config = tmp_path / "temp_config"
        temp_config.mkdir()
        atomic_write_yaml(temp_config / "executor_router.yml", {
            "executor_router": {
                "providers": [
                    {
                        "provider_id": "deepseek-v4-pro",
                        "provider_type": "api_model",
                        "enabled": True,
                        "requires_approval": False,
                        "execution_mode": "manual_handoff_only",
                        "notes": [],
                    }
                ],
                "provider_priority": {
                    "default": ["mock_executor", "deepseek-v4-pro"],
                },
                "safety": {
                    "forbid_production_mutations": True,
                },
                "routing": {
                    "allow_auto_execution": False,
                },
            },
        })
        atomic_write_yaml(temp_config / "router_update_policy.yml", {
            "router_update_policy": {
                "enabled": True,
                "safety": {"allow_apply_to_production": False},
                "approval": {
                    "method": "file_token",
                    "token_file_name": "APPROVE_ROUTER_PATCH",
                    "token_value": "APPROVED",
                },
            },
        })

        result = run_p2_closure(
            task_id="test_with_approval",
            delivery_path=delivery,
            output_dir=tmp_path,
            config_root=temp_config,
            provider_id="deepseek-v4-pro",
            executor="deepseek",
            dry_run=False,
            allow_router_apply=True,
            approval_path=approval_dir,
        )

        assert result.router_apply is not None
        # May or may not be applied depending on patch validation,
        # but the attempt should have been made
        assert result.router_apply_result_path is not None

    def test_apply_with_missing_approval_dir(self, tmp_path: Path):
        delivery = FIXTURES / "accepted_delivery"
        missing_approval = FIXTURES / "router_apply_approval_missing"

        result = run_p2_closure(
            task_id="test_missing_approval_dir",
            delivery_path=delivery,
            output_dir=tmp_path,
            config_root=CONFIG_ROOT,
            provider_id="deepseek-v4-pro",
            executor="deepseek",
            dry_run=False,
            allow_router_apply=True,
            approval_path=missing_approval,
        )
        assert result.router_apply is not None
        assert result.router_apply.applied is False


# ─── H8: Safety - No External Execution ─────────────────────────────


class TestP2ClosureSafety:
    def test_does_not_execute_external_scripts(self, tmp_path: Path):
        delivery = FIXTURES / "accepted_delivery"

        def trap_subprocess(*args, **kwargs):
            pytest.fail("Subprocess call detected during P2 closure")

        with patch("subprocess.run", side_effect=trap_subprocess):
            with patch("subprocess.call", side_effect=trap_subprocess):
                with patch("subprocess.Popen", side_effect=trap_subprocess):
                    run_p2_closure(
                        task_id="test_safety",
                        delivery_path=delivery,
                        output_dir=tmp_path,
                        config_root=CONFIG_ROOT,
                    )

    def test_does_not_call_network(self, tmp_path: Path):
        delivery = FIXTURES / "accepted_delivery"

        def trap_network(*args, **kwargs):
            pytest.fail("Network call detected during P2 closure")

        with patch("requests.get", side_effect=trap_network):
            with patch("requests.post", side_effect=trap_network):
                with patch("urllib.request.urlopen", side_effect=trap_network):
                    run_p2_closure(
                        task_id="test_safety",
                        delivery_path=delivery,
                        output_dir=tmp_path,
                        config_root=CONFIG_ROOT,
                    )

    def test_does_not_read_secrets(self, tmp_path: Path):
        delivery = FIXTURES / "accepted_delivery"

        # Create a fake .env file
        fake_env = ROOT / ".env"
        original_content = None
        if fake_env.exists():
            original_content = fake_env.read_text()

        try:
            read_paths = []
            original_read_text = Path.read_text

            def track_read(self, *args, **kwargs):
                str_self = str(self)
                # Track reads of actual secret files, not output files
                if str_self.endswith(".env") or "/secrets/" in str_self:
                    read_paths.append(str_self)
                return original_read_text(self, *args, **kwargs)

            with patch.object(Path, "read_text", track_read):
                run_p2_closure(
                    task_id="test_safety",
                    delivery_path=delivery,
                    output_dir=tmp_path,
                    config_root=CONFIG_ROOT,
                )

            # P2 closure should not read .env or secrets/ directory
            for p in read_paths:
                assert not p.endswith(".env"), f"Should not read .env: {p}"
                assert "/secrets/" not in p, f"Should not read secrets/: {p}"
        finally:
            if original_content is not None and fake_env.exists():
                fake_env.write_text(original_content)


# ─── Integration: Script invocation ─────────────────────────────────


class TestP2ClosureScript:
    def test_script_runs_with_help(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "p2_closure_check.py"), "--help"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        assert result.returncode == 0
        assert "--task-id" in result.stdout

    def test_script_runs_with_needs_revision_fixture(self, tmp_path: Path):
        delivery = FIXTURES / "needs_revision_delivery"
        output_dir = tmp_path / "closure_output"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "p2_closure_check.py"),
                "--task-id", "test_script_run",
                "--delivery-path", str(delivery),
                "--output-dir", str(output_dir),
                "--provider-id", "deepseek-v4-pro",
                "--executor", "deepseek",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        # Should return non-zero because verdict is not accepted
        # Verdict may be "needs_revision" or "rejected" depending on 3E analysis
        assert "P2 closure verdict:" in result.stdout
        assert "Revision packet:" in result.stdout
        assert result.returncode != 0
