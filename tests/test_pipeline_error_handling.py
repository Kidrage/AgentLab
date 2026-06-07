"""P1-2: Verify pipeline-level errors don't pollute lifecycle.yml nodes."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

import yaml

from lifecycle_graph import create_lifecycle, load_lifecycle, save_lifecycle, LIFECYCLE_NODES
from state_store import load_state
from progress_tracker import load_progress
from pipeline_runner import run_full_pipeline


def _setup_run_dir(root: Path, project: str, task_id: str) -> Path:
    run_dir = root / "projects" / project / "runs" / task_id
    run_dir.mkdir(parents=True)
    (run_dir / "workflow_plan.yml").write_text(
        "route:\n  agents:\n    - Supervisor\n", encoding="utf-8",
    )
    (run_dir / "user_request.md").write_text("# Error handling test\n", encoding="utf-8")
    create_lifecycle(run_dir, {"route": {"agents": ["Supervisor"]}})
    lc = load_lifecycle(run_dir)
    if lc:
        for n in LIFECYCLE_NODES:
            lc.setdefault("nodes", {}).setdefault(n, {})["status"] = "waiting"
        lc["nodes"]["INIT_TASK"]["status"] = "completed"
        lc["nodes"]["PREPARE_PLAN"]["status"] = "completed"
        save_lifecycle(run_dir, lc)
    return run_dir


class PipelineErrorHandlingTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_loop_detected_no_fake_pipeline_node_in_lifecycle(self) -> None:
        run_dir = _setup_run_dir(self.root, "Demo", "task_loop_001")
        # Force loop: mark all nodes as waiting except INIT/PREPARE, then revert to waiting
        # Use max_steps to guarantee hitting loop or max_steps
        result = run_full_pipeline(
            self.root, "Demo", "task_loop_001",
            dry_run=False, fake_provider=True,
            max_steps=2,
        )
        lc = load_lifecycle(run_dir)
        self.assertIsNotNone(lc)
        self.assertNotIn("PIPELINE", lc.get("nodes", {}))
        self.assertFalse(result["success"])
        self.assertEqual(result["final_status"], "paused")

    def test_max_steps_exceeded_no_fake_pipeline_node_in_lifecycle(self) -> None:
        run_dir = _setup_run_dir(self.root, "Demo", "task_maxsteps_001")
        result = run_full_pipeline(
            self.root, "Demo", "task_maxsteps_001",
            dry_run=False, fake_provider=True,
            max_steps=2,
        )
        lc = load_lifecycle(run_dir)
        self.assertIsNotNone(lc)
        self.assertNotIn("PIPELINE", lc.get("nodes", {}))
        self.assertFalse(result["success"])
        self.assertEqual(result["final_status"], "paused")

    def test_pipeline_incident_exists_on_error(self) -> None:
        run_dir = _setup_run_dir(self.root, "Demo", "task_incident_001")
        result = run_full_pipeline(
            self.root, "Demo", "task_incident_001",
            dry_run=False, fake_provider=True,
            max_steps=2,
        )
        self.assertFalse(result["success"])
        self.assertTrue((run_dir / "pipeline_incident.yml").exists())
        incident = yaml.safe_load((run_dir / "pipeline_incident.yml").read_text(encoding="utf-8"))
        self.assertIn(incident["incident_type"], {"max_steps_exceeded", "no_progress", "loop_detected"})

    def test_state_and_progress_blocked_on_pipeline_error(self) -> None:
        run_dir = _setup_run_dir(self.root, "Demo", "task_blocked_001")
        result = run_full_pipeline(
            self.root, "Demo", "task_blocked_001",
            dry_run=False, fake_provider=True,
            max_steps=2,
        )
        self.assertFalse(result["success"])
        state = load_state(run_dir, "Demo", "task_blocked_001")
        progress = load_progress(run_dir) or {}
        self.assertEqual(state.status, "blocked")
        self.assertEqual(progress.get("status"), "blocked")


if __name__ == "__main__":
    main()