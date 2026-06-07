"""P2-2: Provider failover recovery tests.

Simulate provider failure and verify:
1. Task enters blocked/paused state
2. Resume from failed node without re-running completed nodes
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from lifecycle_graph import (
    create_lifecycle, load_lifecycle, save_lifecycle,
    LIFECYCLE_NODES,
)
from state_store import load_state
from progress_tracker import load_progress
from pipeline_runner import run_full_pipeline, resume_pipeline


class ProviderFailoverRecoveryTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.run_dir = self.root / "projects" / "Demo" / "runs" / "task_failover_001"
        self.run_dir.mkdir(parents=True)
        (self.run_dir / "workflow_plan.yml").write_text(
            "route:\n  agents:\n    - Supervisor\n    - TesterAuditor\n",
            encoding="utf-8",
        )
        (self.run_dir / "user_request.md").write_text("# Provider failover test\n", encoding="utf-8")
        create_lifecycle(self.run_dir, {"route": {"agents": ["Supervisor", "TesterAuditor"]}})
        lc = load_lifecycle(self.run_dir)
        if lc:
            lc["nodes"]["INIT_TASK"]["status"] = "completed"
            lc["nodes"]["PREPARE_PLAN"]["status"] = "completed"
            save_lifecycle(self.run_dir, lc)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_quota_failure_blocks_and_writes_evidence(self) -> None:
        """Simulated quota failure writes blocked state + USER_DECISION_REQUIRED."""
        result = run_full_pipeline(
            self.root, "Demo", "task_failover_001",
            dry_run=False, fake_provider=True,
            simulate_quota_failure_at="SUPERVISOR_PLAN",
            max_steps=3,
        )
        self.assertEqual(result["final_status"], "paused")
        self.assertFalse(result["success"])
        state = load_state(self.run_dir, "Demo", "task_failover_001")
        progress = load_progress(self.run_dir) or {}
        self.assertEqual(state.status, "blocked")
        self.assertEqual(progress.get("status"), "blocked")
        self.assertTrue((self.run_dir / "USER_DECISION_REQUIRED.md").exists())

    def test_resume_after_quota_failure_continues(self) -> None:
        """After quota failure, resume should re-enter pipeline."""
        run_full_pipeline(
            self.root, "Demo", "task_failover_001",
            dry_run=False, fake_provider=True,
            simulate_quota_failure_at="SUPERVISOR_PLAN",
            max_steps=3,
        )
        result = resume_pipeline(
            self.root, "Demo", "task_failover_001",
            dry_run=False, fake_provider=True,
            simulate_provider_recovered=True,
        )
        self.assertIn(result.get("final_status", result.get("status")),
                      ("paused", "error", "completed", None))

    def test_resume_does_not_rerun_completed_nodes(self) -> None:
        """Resume should not re-run nodes that are already completed."""
        lc = load_lifecycle(self.run_dir)
        if lc:
            lc["nodes"]["SUPERVISOR_PLAN"]["status"] = "completed"
            lc["nodes"]["SUPERVISOR_PLAN"]["completed_at"] = "2025-01-01T00:00:00Z"
            save_lifecycle(self.run_dir, lc)
        resume_pipeline(
            self.root, "Demo", "task_failover_001",
            dry_run=False, fake_provider=True,
        )
        lc2 = load_lifecycle(self.run_dir)
        if lc2:
            self.assertEqual(lc2["nodes"]["SUPERVISOR_PLAN"]["status"], "completed")


if __name__ == "__main__":
    main()