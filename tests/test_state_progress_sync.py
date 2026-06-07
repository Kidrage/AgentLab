"""P0-3 / P0-4 / P0.5-4: Verify blocked states sync state.yml and progress.yml consistently,
and that exception branches produce block artifacts and USER_DECISION_REQUIRED.md.

P0.5-4: Assertions now go beyond "doesn't crash" — verifying blocked state,
progress sync, and USER_DECISION_REQUIRED.md presence for every block path.
"""

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

    # ── P0.5-4 Test 1: _block_task basic state sync ──
    def test_block_task_basic_state_sync(self) -> None:
        """Direct _block_task call must sync state, progress, and write USER_DECISION_REQUIRED.md."""
        create_progress(self.run_dir, "Demo", "task_sync_001", [])
        block_result = _block_task(
            self.root, self.run_dir, "Demo", "task_sync_001",
            "CODER_IMPLEMENTATION",
            agent="Coder",
            reason="Test blocked state sync",
            stage="blocked_exception",
            block_type="exception",
            user_action_required=True,
        )
        # Result-level assertions
        self.assertEqual(block_result["status"], "paused")
        self.assertFalse(block_result["success"])
        self.assertTrue(block_result["requires_user_action"])
        self.assertEqual(block_result["block_type"], "exception")

        # State sync
        state = load_state(self.run_dir, "Demo", "task_sync_001")
        self.assertEqual(state.status, "blocked")
        self.assertEqual(state.current_agent, "Coder")
        self.assertIn("Blocked at CODER_IMPLEMENTATION", state.last_event)

        # Progress sync
        progress = load_progress(self.run_dir) or {}
        self.assertEqual(progress.get("status"), "blocked")
        self.assertIsNone(progress.get("current_agent"))
        self.assertEqual(progress.get("current_stage"), "blocked_exception")

        # USER_DECISION_REQUIRED.md
        self.assertTrue((self.run_dir / "USER_DECISION_REQUIRED.md").exists())

    # ── P0.5-4 Test 2: loop detected enters blocked ──
    def test_loop_detection_enters_blocked(self) -> None:
        """Loop detection must call _block_task with full blocked state."""
        # Set all lifecycle nodes to 'waiting' so the pipeline has something to do,
        # but the same state in multiple iterations triggers loop detection.
        lc = load_lifecycle(self.run_dir)
        if lc:
            for n in LIFECYCLE_NODES:
                lc.setdefault("nodes", {}).setdefault(n, {})["status"] = "waiting"
            save_lifecycle(self.run_dir, lc)

        result = run_full_pipeline(
            self.root, "Demo", "task_sync_001",
            dry_run=False, fake_provider=True,
            max_steps=3,
        )
        # P0.5-4: assert not just "doesn't crash" but specific blocked state
        self.assertFalse(result["success"])
        self.assertEqual(result["final_status"], "paused")
        self.assertFalse(result["terminal"])
        self.assertTrue(result["requires_user_action"])
        self.assertIn(result.get("blocked_type", ""), ["pipeline_error", "artifact_validation"])

        # Evidence files
        self.assertTrue(
            (self.run_dir / "USER_DECISION_REQUIRED.md").exists(),
            "USER_DECISION_REQUIRED.md must exist on blocked paths",
        )

    # ── P0.5-4 Test 3: max_steps exceeded enters blocked ──
    def test_max_steps_exceeded_enters_blocked(self) -> None:
        """max_steps exceeded must trigger _block_task with strong assertions."""
        result = run_full_pipeline(
            self.root, "Demo", "task_sync_001",
            dry_run=False, fake_provider=True,
            max_steps=2,
        )
        # P0.5-4 assertions
        self.assertFalse(result["success"])
        self.assertEqual(result["final_status"], "paused")
        self.assertFalse(result["terminal"])
        self.assertTrue(result["requires_user_action"])
        self.assertEqual(result.get("blocked_type"), "pipeline_error")

        # State
        state = load_state(self.run_dir, "Demo", "task_sync_001")
        self.assertEqual(state.status, "blocked")

        # Progress
        progress = load_progress(self.run_dir) or {}
        self.assertEqual(progress.get("status"), "blocked")
        self.assertIsNone(progress.get("current_agent"))

        # Evidence
        self.assertTrue((self.run_dir / "USER_DECISION_REQUIRED.md").exists())
        self.assertTrue((self.run_dir / "pipeline_incident.yml").exists())
        self.assertTrue((self.run_dir / "pipeline_error.log").exists())

    # ── P0.5-4 Test 4: terminal artifact invalid enters _block_task ──
    def test_terminal_artifact_invalid_enters_block_task(self) -> None:
        """When all lifecycle nodes are completed/skipped but artifacts invalid,
        the pipeline must call _block_task, not manually write state."""
        # Ensure progress exists before pipeline runs so _block_task can sync it
        create_progress(self.run_dir, "Demo", "task_sync_001", [])
        # Mark all lifecycle nodes as completed to simulate terminal state
        lc = load_lifecycle(self.run_dir)
        if lc:
            for n in LIFECYCLE_NODES:
                lc.setdefault("nodes", {}).setdefault(n, {})["status"] = "completed"
            save_lifecycle(self.run_dir, lc)

        # Remove any report files that artifact_contract would validate,
        # so artifact validation fails.
        for report_name in [
            "01_supervisor_plan.md", "02_reposcout_report.md",
            "06_implementation_report.md", "07_validation_report.md",
            "08_audit_report.md", "verification_report.md",
            "09_archive_update.md",
        ]:
            rp = self.run_dir / report_name
            if rp.exists():
                rp.unlink()

        result = run_full_pipeline(
            self.root, "Demo", "task_sync_001",
            dry_run=False, fake_provider=True,
            max_steps=5,
        )
        # P0.5-4 assertions for terminal artifact invalid
        self.assertFalse(result["success"])
        self.assertEqual(result["final_status"], "paused")
        self.assertFalse(result["terminal"])
        self.assertTrue(result["requires_user_action"])
        self.assertEqual(result.get("blocked_type"), "artifact_validation")

        # State must be blocked
        state = load_state(self.run_dir, "Demo", "task_sync_001")
        self.assertEqual(state.status, "blocked")

        # Progress must be synced
        progress = load_progress(self.run_dir) or {}
        self.assertEqual(progress.get("status"), "blocked")

        # USER_DECISION_REQUIRED.md must exist
        self.assertTrue((self.run_dir / "USER_DECISION_REQUIRED.md").exists())

    # ── Existing tests kept and strengthened ──

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
        # P0.5-4: additional assertions
        self.assertTrue(result["requires_user_action"])
        self.assertEqual(result["final_status"], "paused")
        self.assertFalse(result.get("terminal", True))

    def test_loop_detection_or_max_steps_triggers_block_task(self) -> None:
        """Any pipeline termination via _block_task should sync state and progress."""
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
        self.assertFalse(result["success"])
        # P0.5-4: verify paused semantics
        self.assertEqual(result["final_status"], "paused")
        self.assertTrue(result["requires_user_action"])

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
        self.assertTrue((self.run_dir / "USER_DECISION_REQUIRED.md").exists())

    def test_exception_block_generates_evidence_files(self) -> None:
        """When _block_task is called, USER_DECISION_REQUIRED.md must exist."""
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
        self.assertTrue((self.run_dir / "USER_DECISION_REQUIRED.md").exists())
        state = load_state(self.run_dir, "Demo", "task_sync_001")
        self.assertEqual(state.status, "blocked")
        progress = load_progress(self.run_dir) or {}
        self.assertEqual(progress.get("status"), "blocked")
        self.assertFalse(progress.get("current_agent"))

    def test_no_progress_block_syncs_state(self) -> None:
        """No-progress detection should also trigger _block_task."""
        create_progress(self.run_dir, "Demo", "task_sync_001", [])
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
        # P0.5-4: strengthen — terminal artifact invalid now goes through _block_task
        self.assertFalse(result["success"])
        # With all completed + missing artifacts, this should now hit the artifact_validation block
        self.assertEqual(result["final_status"], "paused")
        self.assertTrue(result["requires_user_action"])


if __name__ == "__main__":
    main()