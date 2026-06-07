"""P0-2: Verify paused / blocked states never return success=True."""

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
from pipeline_runner import run_full_pipeline, run_next_node


class PauseSemanticsTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.run_dir = self.root / "projects" / "Demo" / "runs" / "task_pause_001"
        self.run_dir.mkdir(parents=True)
        (self.run_dir / "workflow_plan.yml").write_text(
            "route:\n  agents:\n    - Supervisor\n    - TesterAuditor\n",
            encoding="utf-8",
        )
        (self.run_dir / "user_request.md").write_text("# Test\n\nPause semantics.\n", encoding="utf-8")
        create_lifecycle(self.run_dir, {"route": {"agents": ["Supervisor", "TesterAuditor"]}})
        lc = load_lifecycle(self.run_dir)
        if lc:
            lc["nodes"]["INIT_TASK"]["status"] = "completed"
            lc["nodes"]["PREPARE_PLAN"]["status"] = "completed"
            save_lifecycle(self.run_dir, lc)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_quota_failure_paused_returns_success_false(self) -> None:
        result = run_full_pipeline(
            self.root, "Demo", "task_pause_001",
            dry_run=False, fake_provider=True,
            simulate_quota_failure_at="SUPERVISOR_PLAN",
            max_steps=3,
        )
        self.assertEqual(result["final_status"], "paused")
        self.assertFalse(result["success"])

    def test_artifact_gate_blocked_returns_success_false(self) -> None:
        """When artifact gate blocks, success must be False."""
        # Inject a USER_DECISION_REQUIRED.md to trigger Supervisor gate
        (self.run_dir / "USER_DECISION_REQUIRED.md").write_text(
            "# Split plan\n\nUser must decide.\n", encoding="utf-8"
        )
        result = run_full_pipeline(
            self.root, "Demo", "task_pause_001",
            dry_run=False, fake_provider=False,
            max_steps=3,
        )
        # Pipeline hits SUPERVISOR_PLAN → sees USER_DECISION_REQUIRED → returns paused
        self.assertEqual(result["final_status"], "paused")
        self.assertFalse(result["success"])

    def test_user_decision_required_returns_success_false(self) -> None:
        """Supervisor gate with USER_DECISION_REQUIRED.md → success=False."""
        (self.run_dir / "USER_DECISION_REQUIRED.md").write_text(
            "# Requires action\n", encoding="utf-8"
        )
        result = run_full_pipeline(
            self.root, "Demo", "task_pause_001",
            dry_run=False, fake_provider=False,
            max_steps=3,
        )
        self.assertIn(result["final_status"], ("paused", "error"))
        self.assertFalse(result["success"])


if __name__ == "__main__":
    main()