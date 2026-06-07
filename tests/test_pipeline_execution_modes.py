"""P0-1: Verify that _resolve_execution_mode prevents real LLM calls in dry_run / mock_provider modes."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

import yaml

from lifecycle_graph import (
    create_lifecycle, load_lifecycle, save_lifecycle,
    mark_node_completed, LIFECYCLE_NODES,
)
from pipeline_runner import _resolve_execution_mode, run_full_pipeline, run_next_node, _block_task


class ExecutionModeResolutionTests(TestCase):
    def test_dry_run_forces_fake_provider(self) -> None:
        mode = _resolve_execution_mode(dry_run=True, fake_provider=False)
        self.assertEqual(mode["execution_mode"], "dry_run")
        self.assertTrue(mode["effective_fake_provider"])
        self.assertFalse(mode["allow_real_provider"])
        self.assertFalse(mode["allow_patches"])

    def test_mock_provider_no_real_provider(self) -> None:
        mode = _resolve_execution_mode(dry_run=False, fake_provider=True)
        self.assertEqual(mode["execution_mode"], "mock_provider")
        self.assertTrue(mode["effective_fake_provider"])
        self.assertFalse(mode["allow_real_provider"])
        self.assertFalse(mode["allow_patches"])

    def test_execute_allows_real_provider_and_patches(self) -> None:
        mode = _resolve_execution_mode(dry_run=False, fake_provider=False)
        self.assertEqual(mode["execution_mode"], "execute")
        self.assertFalse(mode["effective_fake_provider"])
        self.assertTrue(mode["allow_real_provider"])
        self.assertTrue(mode["allow_patches"])


class DryRunNoRealCallTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.run_dir = self.root / "projects" / "Demo" / "runs" / "task_mode_001"
        self.run_dir.mkdir(parents=True)
        (self.run_dir / "workflow_plan.yml").write_text(
            "route:\n  agents:\n    - Supervisor\n    - Coder\n",
            encoding="utf-8",
        )
        (self.run_dir / "user_request.md").write_text("# Test\n\nDry-run test.\n", encoding="utf-8")
        create_lifecycle(self.run_dir, {"route": {"agents": ["Supervisor", "Coder"]}})
        # Mark INIT and PREPARE as completed so pipeline advances to SUPERVISOR_PLAN
        lc = load_lifecycle(self.run_dir)
        if lc:
            lc["nodes"]["INIT_TASK"]["status"] = "completed"
            lc["nodes"]["PREPARE_PLAN"]["status"] = "completed"
            save_lifecycle(self.run_dir, lc)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_dry_run_fake_provider_false_does_not_call_real_model(self) -> None:
        """When dry_run=True, even with fake_provider=False, no real LLM call should happen."""
        import unittest.mock as mock
        with mock.patch("agent_runner.run_agent_model") as patched_run:
            result = run_full_pipeline(
                self.root, "Demo", "task_mode_001",
                dry_run=True, fake_provider=False,
                max_steps=3,
            )
            patched_run.assert_not_called()
            self.assertEqual(result.get("execution_mode"), "dry_run")

    def test_mock_provider_does_not_call_real_llm(self) -> None:
        """dry_run=False, fake_provider=True should still NOT call real LLM."""
        import unittest.mock as mock
        with mock.patch("agent_runner.run_agent_model") as patched_run:
            result = run_full_pipeline(
                self.root, "Demo", "task_mode_001",
                dry_run=False, fake_provider=True,
                max_steps=3,
            )
            patched_run.assert_not_called()
            self.assertEqual(result.get("execution_mode"), "mock_provider")


if __name__ == "__main__":
    main()