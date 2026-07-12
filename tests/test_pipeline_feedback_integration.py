from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from feedback_manager import (
    assess_task_feedback_state,
    load_pending_decision_cards,
    resolve_decision_card,
)
from lifecycle_graph import create_lifecycle, load_lifecycle
from pipeline_runner import _block_task
from progress_tracker import create_progress, load_progress
from state_store import load_state
from task_events import load_task_events


class PipelineFeedbackIntegrationTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.run_dir = self.root / "projects" / "Demo" / "runs" / "task_feedback_001"
        self.run_dir.mkdir(parents=True)
        (self.run_dir / "workflow_plan.yml").write_text(
            "route:\n  agents:\n    - Supervisor\n",
            encoding="utf-8",
        )
        create_lifecycle(self.run_dir, {"route": {"agents": ["Supervisor"]}})
        create_progress(self.run_dir, "Demo", "task_feedback_001", ["Supervisor"])

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_block_task_writes_decision_card_events_and_feedback_status(self) -> None:
        result = _block_task(
            self.root,
            self.run_dir,
            "Demo",
            "task_feedback_001",
            "SUPERVISOR_PLAN",
            agent="Supervisor",
            reason="Need user approval before continuing.",
            stage="blocked_user_decision",
            user_action_required=True,
            block_type="user_decision",
        )

        self.assertEqual(result["status"], "paused")
        self.assertIn("decision_id", result)
        self.assertTrue((self.run_dir / "USER_DECISION_REQUIRED.md").exists())
        self.assertTrue((self.run_dir / "feedback_status.json").exists())

        cards = load_pending_decision_cards(self.run_dir)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["type"], "user_decision")
        self.assertEqual(cards[0]["recommended_action"], "approve_resume")

        events = load_task_events(self.run_dir)
        self.assertEqual([event["event"] for event in events], ["APPROVAL_REQUIRED", "NODE_BLOCKED"])
        self.assertEqual(events[-1]["status"], "WAITING_FOR_APPROVAL")

        feedback = assess_task_feedback_state(self.run_dir)
        self.assertEqual(feedback["feedback_status"], "WAITING_FOR_APPROVAL")
        self.assertEqual(feedback["pending_decision_count"], 1)

        state = load_state(self.run_dir, "Demo", "task_feedback_001")
        progress = load_progress(self.run_dir) or {}
        lifecycle = load_lifecycle(self.run_dir) or {}
        self.assertEqual(state.status, "blocked")
        self.assertEqual(progress.get("status"), "blocked")
        self.assertEqual(lifecycle["nodes"]["SUPERVISOR_PLAN"]["status"], "failed")

    def test_block_task_redacts_and_compacts_decision_reason(self) -> None:
        local_path = "/" + "Users/private-user/project/error.log"
        fake_api_key = "sk-" + "1234567890abcdef"
        result = _block_task(
            self.root,
            self.run_dir,
            "Demo",
            "task_feedback_001",
            "SUPERVISOR_PLAN",
            agent="Supervisor",
            reason=(
                "provider failed\n"
                f"api_key={fake_api_key}\n"
                f"{local_path}"
            ),
            stage="blocked_user_decision",
            user_action_required=True,
            block_type="provider_error",
        )

        decision = (self.run_dir / "USER_DECISION_REQUIRED.md").read_text(
            encoding="utf-8"
        )
        self.assertNotIn(fake_api_key, decision)
        self.assertNotIn("/" + "Users/private-user", decision)
        self.assertIn("[REDACTED_SECRET]", decision)
        self.assertNotIn("\napi_key", result["message"])

    def test_resolve_decision_card_approves_and_clears_legacy_gate(self) -> None:
        result = _block_task(
            self.root,
            self.run_dir,
            "Demo",
            "task_feedback_001",
            "SUPERVISOR_PLAN",
            agent="Supervisor",
            reason="Need user approval before continuing.",
            stage="blocked_user_decision",
            user_action_required=True,
            block_type="user_decision",
        )

        card = resolve_decision_card(
            self.run_dir,
            result["decision_id"],
            option_id="approve_resume",
            resolution="approved",
        )

        self.assertEqual(card["status"], "approved")
        self.assertFalse((self.run_dir / "USER_DECISION_REQUIRED.md").exists())
        self.assertEqual(load_pending_decision_cards(self.run_dir), [])
        self.assertTrue(
            (self.run_dir / "decision_cards" / f"{result['decision_id']}_USER_DECISION_REQUIRED.approved.md").exists()
        )
        events = load_task_events(self.run_dir)
        self.assertEqual(events[-1]["event"], "USER_DECISION_RECORDED")
        self.assertEqual(events[-1]["payload"]["selected_option"], "approve_resume")


if __name__ == "__main__":
    main()
