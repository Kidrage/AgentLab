import unittest
from pathlib import Path
from agent_runtime.external_agents.ledger import ExternalAgentLedger


class TestExternalAgentLedger(unittest.TestCase):
    def setUp(self):
        """Set up test environment with fresh ledger"""
        self.task_id = "task_0035"
        self.output_dir = f"projects/AgentLab/runs/{self.task_id}"
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

        # Remove any existing ledger file to start fresh
        ledger_path = Path(self.output_dir) / "external_agent_ledger.yml"
        if ledger_path.exists():
            ledger_path.unlink()

        self.handoff_data = {
            "handoff_id": "handoff_20260612_235959",
            "task_id": self.task_id,
            "project": "AgentLab",
            "target": {
                "agent_id": "cline_codex",
                "agent_type": "ide_agent",
                "integration_mode": "handoff_only",
                "enabled": False,
                "status": "proposed",
            },
            "objective": {
                "title": "Implement feature X",
                "summary": "Description of the task",
            },
            "constraints": [],
            "required_outputs": [],
            "budget": {
                "billing_mode": "subscription_quota",
                "api_cost_visible": False,
                "external_token_visibility": "unknown",
            },
            "evidence_requirements": [],
        }

        self.ledger = ExternalAgentLedger(self.task_id, self.output_dir)

    def tearDown(self):
        """Clean up ledger file after each test"""
        ledger_path = Path(self.output_dir) / "external_agent_ledger.yml"
        if ledger_path.exists():
            ledger_path.unlink()

    def test_ledger_initialization(self):
        """Test ledger initialization and file creation"""
        ledger_path = Path(self.output_dir) / "external_agent_ledger.yml"
        self.assertTrue(ledger_path.exists())

        ledger_data = self.ledger.get_ledger()
        self.assertEqual(ledger_data["task_id"], self.task_id)
        self.assertEqual(ledger_data["handoffs"], [])

    def test_add_handoff(self):
        """Test adding a handoff to the ledger"""
        self.ledger.add_handoff(self.handoff_data)

        ledger_data = self.ledger.get_ledger()
        self.assertEqual(len(ledger_data["handoffs"]), 1)

        handoff_entry = ledger_data["handoffs"][0]
        self.assertEqual(handoff_entry["handoff_id"], self.handoff_data["handoff_id"])
        self.assertEqual(handoff_entry["agent_id"], self.handoff_data["target"]["agent_id"])
        self.assertEqual(handoff_entry["status"], "proposed")
        self.assertEqual(handoff_entry["token_visibility"], "unknown")
        self.assertEqual(handoff_entry["evidence_status"], "missing")
        self.assertEqual(handoff_entry["artifact_gate_status"], "pending")

    def test_update_result_status(self):
        """Test updating ledger with result submission"""
        self.ledger.add_handoff(self.handoff_data)

        result_data = {
            "handoff_id": self.handoff_data["handoff_id"],
            "status": "completed",
            "evidence_status": "complete",
            "executor": {
                "agent_id": "cline_codex",
                "reported_by": "user",
                "billing_mode": "subscription_quota",
                "token_visibility": "unknown",
            },
            "summary": "Successfully implemented feature X",
            "changed_files": ["src/feature_x.py"],
            "commands_run": ["pytest tests/test_feature_x.py"],
            "artifacts": ["coverage_report.xml"],
        }

        self.ledger.update_result_status(result_data)

        ledger_data = self.ledger.get_ledger()
        handoff_entry = ledger_data["handoffs"][0]

        self.assertEqual(handoff_entry["status"], "submitted")
        self.assertEqual(handoff_entry["evidence_status"], "complete")
        self.assertEqual(handoff_entry["artifact_gate_status"], "pending")

    def test_skill_usage_planned(self):
        """Test recording planned skill usage in the ledger"""
        self.ledger.add_handoff(self.handoff_data)

        skill_data = {
            "suggested_external_skills": ["ecc.planner", "ecc.code-reviewer"],
            "executor": "cline_codex",
            "cost_mode": "subscription_quota",
        }

        self.ledger.add_skill_usage(self.handoff_data["handoff_id"], skill_data)
        ledger_data = self.ledger.get_ledger()

        handoff_entry = ledger_data["handoffs"][0]
        self.assertEqual(len(handoff_entry["skill_usage_events"]), 1)

        skill_event = handoff_entry["skill_usage_events"][0]
        self.assertEqual(skill_event["event"], "planned")
        self.assertEqual(skill_event["executor"], "cline_codex")
        self.assertEqual(skill_event["cost_mode"], "subscription_quota")

    def test_skill_usage_used_with_score(self):
        """Test recording used skill with quality score"""
        self.ledger.add_handoff(self.handoff_data)

        skill_data = {
            "executor": "cline_codex",
            "cost_mode": "subscription_quota",
            "success": True,
            "quality_score": 8.5,
        }

        self.ledger.add_skill_usage(self.handoff_data["handoff_id"], skill_data)
        ledger_data = self.ledger.get_ledger()

        handoff_entry = ledger_data["handoffs"][0]
        self.assertEqual(len(handoff_entry["skill_usage_events"]), 1)

        skill_event = handoff_entry["skill_usage_events"][0]
        self.assertEqual(skill_event["event"], "used")
        self.assertEqual(skill_event["executor"], "cline_codex")
        self.assertEqual(skill_event["success"], True)
        self.assertEqual(skill_event["quality_score"], 8.5)

    def test_ledger_persistence(self):
        """Test ledger data is persisted between sessions"""
        # First session: add handoff
        ledger1 = ExternalAgentLedger(self.task_id, self.output_dir)
        ledger1.add_handoff(self.handoff_data)

        # Second session: load and verify
        ledger2 = ExternalAgentLedger(self.task_id, self.output_dir)
        ledger_data = ledger2.get_ledger()

        self.assertEqual(ledger_data["task_id"], self.task_id)
        self.assertEqual(len(ledger_data["handoffs"]), 1)

        handoff_entry = ledger_data["handoffs"][0]
        self.assertEqual(handoff_entry["handoff_id"], self.handoff_data["handoff_id"])
        self.assertEqual(handoff_entry["agent_id"], self.handoff_data["target"]["agent_id"])
        self.assertEqual(handoff_entry["status"], "proposed")
        self.assertEqual(handoff_entry["evidence_status"], "missing")
        self.assertEqual(handoff_entry["artifact_gate_status"], "pending")

    def test_multiple_handoffs(self):
        """Test handling multiple handoffs in a single task"""
        # Add first handoff
        self.ledger.add_handoff(self.handoff_data)

        # Add second handoff
        handoff_data2 = self.handoff_data.copy()
        handoff_data2["handoff_id"] = "handoff_20260613_000001"
        handoff_data2["target"] = self.handoff_data["target"].copy()
        handoff_data2["target"]["agent_id"] = "ecc_pack"

        self.ledger.add_handoff(handoff_data2)

        ledger_data = self.ledger.get_ledger()
        self.assertEqual(len(ledger_data["handoffs"]), 2)

        # Verify first handoff
        h1 = ledger_data["handoffs"][0]
        self.assertEqual(h1["handoff_id"], self.handoff_data["handoff_id"])
        self.assertEqual(h1["agent_id"], "cline_codex")

        # Verify second handoff
        h2 = ledger_data["handoffs"][1]
        self.assertEqual(h2["handoff_id"], "handoff_20260613_000001")
        self.assertEqual(h2["agent_id"], "ecc_pack")


if __name__ == "__main__":
    unittest.main()