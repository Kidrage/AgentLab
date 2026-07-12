from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from lifecycle_graph import (
    create_lifecycle,
    load_lifecycle,
    mark_node_completed,
    mark_node_failed,
)
from state_store import load_state, save_state
from task_index import rebuild_index
from task_snapshot import build_task_snapshot, write_task_snapshot


class TaskSnapshotTests(TestCase):
    def test_snapshot_normalizes_status_sources(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "projects" / "Demo" / "runs" / "task_0001"
            run_dir.mkdir(parents=True)
            (run_dir / "workflow_plan.yml").write_text(
                "route:\n  agents:\n    - Supervisor\n",
                encoding="utf-8",
            )
            state = load_state(run_dir, "Demo", "task_0001")
            state.status = "complete"
            state.last_event = "legacy complete status"
            save_state(run_dir, state)

            snapshot = build_task_snapshot(run_dir, project="Demo", task_id="task_0001")

            self.assertEqual(snapshot["status"], "completed")
            self.assertEqual(snapshot["percent_complete"], 100)

    def test_snapshot_tracks_lifecycle_progress(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "projects" / "Demo" / "runs" / "task_0002"
            run_dir.mkdir(parents=True)
            create_lifecycle(run_dir, {"route": {"agents": ["Supervisor"]}})
            mark_node_completed(run_dir, "INIT_TASK")
            path = write_task_snapshot(run_dir, project="Demo", task_id="task_0002")

            self.assertTrue(path.exists())
            snapshot = build_task_snapshot(run_dir, project="Demo", task_id="task_0002")
            self.assertEqual(snapshot["lifecycle"]["completed_count"], 1)

    def test_completed_recovery_clears_stale_lifecycle_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "projects" / "Demo" / "runs" / "task_0004"
            run_dir.mkdir(parents=True)
            create_lifecycle(run_dir, {"route": {"agents": ["Supervisor"]}})
            mark_node_failed(run_dir, "FINALIZE", "old artifact gate failure")

            mark_node_completed(run_dir, "FINALIZE")

            lifecycle = load_lifecycle(run_dir) or {}
            final_node = lifecycle["nodes"]["FINALIZE"]
            self.assertEqual(final_node["status"], "completed")
            self.assertIsNone(final_node["error"])


class TaskIndexLedgerTests(TestCase):
    def test_rebuild_index_syncs_ledger_from_runs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = root / "projects" / "Demo" / "runs" / "task_0003"
            run_dir.mkdir(parents=True)
            (run_dir / "user_request.md").write_text("# Demo Task\n\nImplement closure.\n", encoding="utf-8")
            state = load_state(run_dir, "Demo", "task_0003")
            state.status = "completed"
            save_state(run_dir, state)

            index = rebuild_index(root, "Demo")
            ledger = root / "projects" / "Demo" / "agent_docs" / "02_TASK_LEDGER.yml"

            self.assertEqual(index["task_count"], 1)
            self.assertTrue((run_dir / "task_snapshot.yml").exists())
            self.assertTrue((run_dir / "task_card.yml").exists())
            self.assertTrue(ledger.exists())
            self.assertIn("task_0003", ledger.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
