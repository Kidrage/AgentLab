"""P1-3: Verify _sync_task_summary writes index_sync_warning.log on failure."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from lifecycle_graph import create_lifecycle, load_lifecycle, save_lifecycle, LIFECYCLE_NODES
from state_store import load_state
from progress_tracker import load_progress, create_progress
from pipeline_runner import _block_task


def _setup_run_dir(root: Path, project: str, task_id: str) -> Path:
    run_dir = root / "projects" / project / "runs" / task_id
    run_dir.mkdir(parents=True)
    (run_dir / "workflow_plan.yml").write_text(
        "route:\n  agents:\n    - Supervisor\n", encoding="utf-8",
    )
    (run_dir / "user_request.md").write_text("# Sync warning test\n", encoding="utf-8")
    create_lifecycle(run_dir, {"route": {"agents": ["Supervisor"]}})
    lc = load_lifecycle(run_dir)
    if lc:
        for n in LIFECYCLE_NODES:
            lc.setdefault("nodes", {}).setdefault(n, {})["status"] = "waiting"
        lc["nodes"]["INIT_TASK"]["status"] = "completed"
        lc["nodes"]["PREPARE_PLAN"]["status"] = "completed"
        save_lifecycle(run_dir, lc)
    # Initialize progress so _block_task can update it
    create_progress(run_dir, project, task_id, ["Supervisor"])
    return run_dir


class TaskIndexSyncWarningTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_index_sync_warning_log_written_on_failure(self) -> None:
        run_dir = _setup_run_dir(self.root, "Demo", "task_syncwarn_001")

        # Monkey-patch generate_per_task_artifacts to raise
        with mock.patch(
            "task_index.generate_per_task_artifacts",
            side_effect=RuntimeError("Simulated index sync failure"),
        ):
            result = _block_task(
                self.root, run_dir, "Demo", "task_syncwarn_001",
                "SUPERVISOR_PLAN",
                agent="Supervisor",
                reason="Test sync warning",
                stage="blocked_test",
                block_type="test_sync",
            )

        self.assertFalse(result["success"])
        warning_path = run_dir / "index_sync_warning.log"
        self.assertTrue(warning_path.exists(), f"{warning_path} should exist")
        warning_text = warning_path.read_text(encoding="utf-8")
        self.assertIn("Task Index Sync Warning", warning_text)
        self.assertIn("RuntimeError", warning_text)
        self.assertIn("Simulated index sync failure", warning_text)

    def test_state_progress_still_blocked_despite_sync_failure(self) -> None:
        run_dir = _setup_run_dir(self.root, "Demo", "task_syncwarn_002")

        with mock.patch(
            "task_index.generate_per_task_artifacts",
            side_effect=RuntimeError("Index generation failed"),
        ):
            _block_task(
                self.root, run_dir, "Demo", "task_syncwarn_002",
                "CODER_IMPLEMENTATION",
                agent="Coder",
                reason="Test blocked despite sync failure",
                stage="blocked_test",
                block_type="test_sync",
            )

        state = load_state(run_dir, "Demo", "task_syncwarn_002")
        progress = load_progress(run_dir) or {}
        self.assertEqual(state.status, "blocked")
        self.assertEqual(progress.get("status"), "blocked")


if __name__ == "__main__":
    main()