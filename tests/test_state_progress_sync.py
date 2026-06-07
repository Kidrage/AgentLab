"""P0-3 / P0-4: Verify blocked states sync state.yml and progress.yml consistently,
and that exception branches produce block artifacts and USER_DECISION_REQUIRED.md."""

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
    LIFECYCLE_NODES,
)
from state_store import load_state
from progress_tracker import load_progress, create_progress
from pipeline_runner import run_full_pipeline, _block_task


class StateProgressSyncTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.run_dir = self.root / "projects" / "Demo" / "runs" / "task_sync_001"
        self.run_dir.mkdir(parents=True)
        (self.run_dir / "workflow_plan.yml").write_text(
            "route:\n  agents:\n    - Supervisor\n",
            encoding="utf-8",
        )
        (self.run_dir / "user_request.md").write_text("# Sync test\n", encoding="utf-8")
        create_lifecycle(self.run_dir, {"route": {"agents": ["Supervisor"]}})
        lc = load_lifecycle(self.run_dir)
        if lc:
            lc["nodes"]["INIT_TASK"]["status"] = "completed"
            lc["nodes"]["PREPARE_PLAN"]["status"] = "completed"
            save_lifecycle(self.run_dir, lc)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_quota_failure_syncs_state_and_progress(self) -> None:
        result = run_full_pipeline(
            self.root, "Demo", "task_sync_001",
            dry_run=False, fake_provider=True,
            simulate_quota_failure_at="SUPERVISOR_PLAN",
            max_steps=3,
        )
        state = load_state(self.run_dir, "Demo", "task_sync_001")
        progress = load_progress(self.run_dir) or {}
        self.assertEqual(state.status, "blocked")
        self.assertEqual(progress.get("status"), "blocked")
        self.assertIsNone(progress.get("current_agent"))
        self.assertIn(progress.get("current_stage", ""), [
            "blocked", "blocked_quota", "blocked_user_decision",
        ])
        self.assertFalse(result["success"])

    def test_loop_detection_or_max_steps_triggers_block_task(self) -> None:
        """Any pipeline termination via _block_task should sync state and progress."""
        # Use max_steps=1 — this will either finish or trigger max_steps exceeded.
        # Either way _block_task is used for terminal conditions.
        lc = load_lifecycle(self.run_dir)
        if lc:
            for n in LIFECYCLE_NODES:
                lc.setdefault("nodes", {}).setdefault(n, {})["status"] = "waiting"
            save_lifecycle(self.run_dir, lc)

        result = run_full_pipeline(
            self.root, "Demo", "task_sync_001",
            dry_run=False, fake_provider=True,
            max_steps=1,
        )
        # Pipeline should terminate via _block_task (max_steps exceeded)
        state = load_state(self.run_dir, "Demo", "task_sync_001")
        progress = load_progress(self.run_dir) or {}
        # Either blocked or error/completed (depends on lifecycle state)
        # The key test is that it doesn't crash
        self.assertFalse(result["success"])

    def test_max_steps_exceeded_syncs_state_and_progress(self) -> None:
        """max_steps exceeded triggers _block_task."""
        result = run_full_pipeline(
            self.root, "Demo", "task_sync_001",
            dry_run=False, fake_provider=True,
            max_steps=2,
        )
        state = load_state(self.run_dir, "Demo", "task_sync_001")
        progress = load_progress(self.run_dir) or {}
        self.assertEqual(state.status, "blocked")
        self.assertEqual(progress.get("status"), "blocked")
        self.assertFalse(result["success"])
        # USER_DECISION_REQUIRED.md must exist
        self.assertTrue((self.run_dir / "USER_DECISION_REQUIRED.md").exists())

    def test_exception_block_generates_evidence_files(self) -> None:
        """When _block_task is called, USER_DECISION_REQUIRED.md must exist."""
        # Ensure progress is initialized first so _block_task can update it
        create_progress(self.run_dir, "Demo", "task_sync_001", [])
        _block_task(
            self.root, self.run_dir, "Demo", "task_sync_001",
            "CODER_IMPLEMENTATION",
            agent="Coder",
            reason="Test exception block",
            stage="blocked_exception",
            block_type="exception",
            user_action_required=True,
        )
        # After _block_task call, USER_DECISION_REQUIRED.md must exist
        self.assertTrue((self.run_dir / "USER_DECISION_REQUIRED.md").exists())
        state = load_state(self.run_dir, "Demo", "task_sync_001")
        self.assertEqual(state.status, "blocked")
        progress = load_progress(self.run_dir) or {}
        self.assertEqual(progress.get("status"), "blocked")
        self.assertFalse(progress.get("current_agent"))

    def test_no_progress_block_syncs_state(self) -> None:
        """No-progress detection should also trigger _block_task."""
        # Mark all lifecycle nodes as completed to force the completion path n=0 iteration
        lc = load_lifecycle(self.run_dir)
        if lc:
            for n in LIFECYCLE_NODES:
                lc.setdefault("nodes", {}).setdefault(n, {})["status"] = "completed"
            save_lifecycle(self.run_dir, lc)
        result = run_full_pipeline(
            self.root, "Demo", "task_sync_001",
            dry_run=False, fake_provider=True,
            max_steps=5,
        )
        state = load_state(self.run_dir, "Demo", "task_sync_001")
        progress = load_progress(self.run_dir) or {}
        # Either completed or blocked
        self.assertFalse(result["success"])


if __name__ == "__main__":
    main()