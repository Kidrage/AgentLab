from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from handoff_builder import build_handoff_packet
from state_store import load_state, save_state


class HandoffBuilderTests(TestCase):
    def test_missing_legacy_mode_defaults_to_agentlab_orchestration(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_root = Path(td) / "projects" / "Demo"
            run_dir = project_root / "runs" / "task_0001"
            run_dir.mkdir(parents=True)
            (run_dir / "workflow_plan.yml").write_text(
                "route:\n  agents:\n    - Supervisor\n",
                encoding="utf-8",
            )

            packet = build_handoff_packet(project_root, "task_0001")

            self.assertEqual(
                packet["execution_mode"], "agentlab_orchestrated_cli"
            )
            self.assertIn("for_assigned_worker", packet["resume_instructions"])

    def test_completed_task_has_no_resume_agent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_root = Path(td) / "projects" / "Demo"
            run_dir = project_root / "runs" / "task_0001"
            run_dir.mkdir(parents=True)
            (run_dir / "workflow_plan.yml").write_text(
                "route:\n  agents:\n    - Supervisor\n    - Coder\n",
                encoding="utf-8",
            )
            state = load_state(run_dir, "Demo", "task_0001")
            state.status = "completed"
            state.completed_agents = []
            save_state(run_dir, state)

            packet = build_handoff_packet(project_root, "task_0001")

            self.assertEqual(packet["status"], "completed")
            self.assertIsNone(packet["next_agent"])
            self.assertFalse(packet["resume_available"])


if __name__ == "__main__":
    main()
