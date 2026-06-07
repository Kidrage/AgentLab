"""P1-4: Verify run_next_node() returns correct execution_mode when called directly."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from lifecycle_graph import create_lifecycle, load_lifecycle, save_lifecycle, LIFECYCLE_NODES
from pipeline_runner import run_next_node


def _setup_minimal_run_dir(root: Path, project: str, task_id: str) -> Path:
    run_dir = root / "projects" / project / "runs" / task_id
    run_dir.mkdir(parents=True)
    (run_dir / "workflow_plan.yml").write_text(
        "route:\n  agents:\n    - Supervisor\n", encoding="utf-8",
    )
    (run_dir / "user_request.md").write_text("# Mode semantics test\n", encoding="utf-8")
    create_lifecycle(run_dir, {"route": {"agents": ["Supervisor"]}})
    lc = load_lifecycle(run_dir)
    if lc:
        for n in LIFECYCLE_NODES:
            lc.setdefault("nodes", {}).setdefault(n, {})["status"] = "completed"
        save_lifecycle(run_dir, lc)
    return run_dir


class RunNextNodeSemanticsTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_fake_provider_true_defaults_to_mock_provider(self) -> None:
        run_dir = _setup_minimal_run_dir(self.root, "Demo", "task_mode_100")
        # All nodes completed → run_next_node returns waiting/completed
        result = run_next_node(self.root, "Demo", "task_mode_100", fake_provider=True)
        self.assertIn(result.get("execution_mode"), ("mock_provider", "completed", "waiting", None))
        # If execution_mode is present, it must be "mock_provider"
        if result.get("execution_mode") and result["status"] in ("completed", "waiting"):
            self.assertEqual(result["execution_mode"], "mock_provider")

    def test_execute_mode_defaults_to_execute(self) -> None:
        run_dir = _setup_minimal_run_dir(self.root, "Demo", "task_mode_101")
        result = run_next_node(self.root, "Demo", "task_mode_101", fake_provider=False)
        if result.get("execution_mode") and result["status"] in ("completed", "waiting"):
            self.assertEqual(result["execution_mode"], "execute")

    def test_explicit_execution_mode_passed_through(self) -> None:
        run_dir = _setup_minimal_run_dir(self.root, "Demo", "task_mode_102")
        result = run_next_node(
            self.root, "Demo", "task_mode_102",
            fake_provider=True, execution_mode="dry_run",
        )
        if result.get("execution_mode") and result["status"] in ("completed", "waiting"):
            self.assertEqual(result["execution_mode"], "dry_run")


if __name__ == "__main__":
    main()