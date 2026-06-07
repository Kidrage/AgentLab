"""P1-1: Verify resume_pipeline() always returns a dict and never None."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

import yaml

from lifecycle_graph import create_lifecycle, load_lifecycle, save_lifecycle, LIFECYCLE_NODES
from state_store import load_state, save_state
from pipeline_runner import resume_pipeline, run_full_pipeline


def _setup_minimal_run_dir(root: Path, project: str, task_id: str, status: str) -> Path:
    run_dir = root / "projects" / project / "runs" / task_id
    run_dir.mkdir(parents=True)
    (run_dir / "workflow_plan.yml").write_text(
        "route:\n  agents:\n    - Supervisor\n", encoding="utf-8",
    )
    (run_dir / "user_request.md").write_text("# Resume test\n", encoding="utf-8")
    create_lifecycle(run_dir, {"route": {"agents": ["Supervisor"]}})
    lc = load_lifecycle(run_dir)
    if lc:
        for n in LIFECYCLE_NODES:
            lc.setdefault("nodes", {}).setdefault(n, {})["status"] = "waiting"
        lc["nodes"]["INIT_TASK"]["status"] = "completed"
        lc["nodes"]["PREPARE_PLAN"]["status"] = "completed"
        save_lifecycle(run_dir, lc)
    state = load_state(run_dir, project, task_id)
    state.status = status
    save_state(run_dir, state)
    return run_dir


class ResumePipelineTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_completed_returns_success_true(self) -> None:
        _setup_minimal_run_dir(self.root, "Demo", "task_resume_1", "completed")
        result = resume_pipeline(self.root, "Demo", "task_resume_1")
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"])
        self.assertEqual(result["final_status"], "completed")
        self.assertTrue(result["terminal"])

    def test_blocked_calls_run_full_pipeline(self) -> None:
        _setup_minimal_run_dir(self.root, "Demo", "task_resume_2", "blocked")
        # run_full_pipeline with dry_run=True, fake_provider=True should succeed
        result = resume_pipeline(self.root, "Demo", "task_resume_2")
        self.assertIsInstance(result, dict)
        self.assertIn(result["final_status"], ("completed", "paused", "failed"))

    def test_paused_calls_run_full_pipeline(self) -> None:
        _setup_minimal_run_dir(self.root, "Demo", "task_resume_3", "paused")
        result = resume_pipeline(self.root, "Demo", "task_resume_3")
        self.assertIsInstance(result, dict)
        self.assertIn(result["final_status"], ("completed", "paused", "failed"))

    def test_failed_returns_non_resumable(self) -> None:
        _setup_minimal_run_dir(self.root, "Demo", "task_resume_4", "failed")
        result = resume_pipeline(self.root, "Demo", "task_resume_4")
        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
        self.assertTrue(result["terminal"])
        self.assertEqual(result["final_status"], "failed")

    def test_unknown_status_returns_dict(self) -> None:
        _setup_minimal_run_dir(self.root, "Demo", "task_resume_5", "paused")
        # Force an unrecognized status on the loaded state object
        import unittest.mock as mock
        patched_state = load_state(
            self.root / "projects" / "Demo" / "runs" / "task_resume_5",
            "Demo", "task_resume_5",
        )
        patched_state.status = "weird_state"
        with mock.patch("pipeline_runner.load_state", return_value=patched_state):
            result = resume_pipeline(self.root, "Demo", "task_resume_5")
        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
        self.assertEqual(result["final_status"], "weird_state")
        self.assertTrue(result["requires_user_action"])


if __name__ == "__main__":
    main()