import unittest
from pathlib import Path
from datetime import datetime
from agent_runtime.external_agents.ledger import ExternalAgentLedger
from agent_runtime.task_index import TaskIndex
from agent_runtime.task_events import TaskEvents

class TestExternalAgentLedger(unittest.TestCase):
    def setUp(self):
        """Set up test environment"""
        self.task_id = "task_0035"
        self.output_dir = f"projects/AgentLab/runs/{self.task_id}"
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        
        # Initialize task index and events
        self.task_index = TaskIndex()
        self.task_index.create_task(self.task_id, "Test Task", "External Agent Ledger Test")
        self.task_events = TaskEvents(self.task_id)
        
        # Create a sample handoff
        self.handoff_data = {
            "handoff_id": "handoff_20260612_235959",
            "task_id": self.task_id,
            "project": "AgentLab",
            "target": {
                "agent_id": "cline_codex",
                "agent_type": "ide_agent",
                "integration_mode": "handoff_only",
                "enabled": False,
                "status": "proposed"
            },
            "objective": {
                "title": "Implement feature X",
                "summary": "Description of the task to be performed by the external agent"
            },
            "constraints": [],
            "required_outputs": [],
            "budget": {
                "billing_mode": "subscription_quota",
                "api_cost_visible": False,
                "external_token_visibility": "unknown"
            },
            "evidence_requirements": []
        }
        
        # Create ledger and add handoff
        self.ledger = ExternalAgentLedger(self.task_id, self.output_dir)
        self.ledger.add_handoff(self.handoff_data)
    
    def test_ledger_initialization(self):
        """Test ledger initialization and file creation"""
        ledger_path = Path(self.output_dir) / "external_agent_ledger.yml"
        self.assertTrue(ledger_path.exists())
        
        # Verify ledger structure
        with open(ledger_path, 'r') as f:
            ledger_data = self.ledger.get_ledger()
        
        self.assertEqual(ledger_data["task_id"], self.task_id)
        self.assertEqual(len(ledger_data["handoffs"]), 1)
        
        handoff_entry = ledger_data["handoffs"][0]
        self.assertEqual(handoff_entry["handoff_id"], self.handoff_data["handoff_id"])
        self.assertEqual(handoff_entry["agent_id"], self.handoff_data["target"]["agent_id"])
        self.assertEqual(handoff_entry["status"], self.handoff_data["target"]["status"])
        self.assertEqual(handoff_entry["evidence_status"], "missing")
        self.assertEqual(handoff_entry["artifact_gate_status"], "pending")
    
    def test_result_status_update(self):
        """Test updating ledger when submitting a result"""
        result_data = {
            "handoff_id": self.handoff_data["handoff_id"],
            "task_id": self.task_id,
            "executor": {
                "agent_id": "cline_codex",
                "reported_by": "user",
                "billing_mode": "subscription_quota",
                "token_visibility": "unknown"
            },
            "status": "completed",
            "summary": "Successfully implemented feature X",
            "changed_files": ["src/feature_x.py"],
            "commands_run": ["pytest tests/test_feature_x.py"],
            "artifacts": ["coverage_report.xml"],
            "risks": [],
            "cost_notes": {}
        }
        
        self.ledger.update_result_status(result_data)
        ledger_data = self.ledger.get_ledger()
        
        handoff_entry = ledger_data["handoffs"][0]
        self.assertEqual(handoff_entry["status"], "completed")
        self.assertEqual(handoff_entry["evidence_status"], "complete")
        self.assertEqual(handoff_entry["artifact_gate_status"], "passed")
        
        # Verify event was recorded
        events = self.task_events.get_task_events(self.task_id)
        result_events = [e for e in events if e["event_type"] == "external_result_submitted"]
        self.assertTrue(len(result_events) > 0)
        
        last_event = result_events[-1]
        self.assertEqual(last_event["handoff_id"], result_data["handoff_id"])
        self.assertEqual(last_event["agent_id"], result_data["executor"]["agent_id"])
        self.assertEqual(last_event["token_visibility"], "unknown")
    
    def test_skill_usage_recording(self):
        """Test recording skill usage in the ledger"""
        # Add skill usage for a handoff
        skill_data = {
            "suggested_external_skills": ["ecc.planner", "ecc.code-reviewer"]
        }
        
        self.ledger.add_skill_usage(self.handoff_data["handoff_id"], skill_data)
        ledger_data = self.ledger.get_ledger()
        
        handoff_entry = ledger_data["handoffs"][0]
        self.assertEqual(len(handoff_entry["skill_usage_events"]), 1)
        
        skill_event = handoff_entry["skill_usage_events"][0]
        self.assertEqual(skill_event["event"], "planned")
        self.assertEqual(skill_event["executor"], "unknown")
        self.assertEqual(skill_event["cost_mode"], "unknown")
        
        # Add skill usage for a result
        result_data = {
            "handoff_id": self.handoff_data["handoff_id"],
            "task_id": self.task_id,
            "executor": {
                "agent_id": "cline_codex",
                "reported_by": "user",
                "billing_mode": "subscription_quota",
                "token_visibility": "unknown"
            },
            "status": "completed",
            "summary": "Successfully implemented feature X",
            "changed_files": ["src/feature_x.py"],
            "commands_run": ["pytest tests/test_feature_x.py"],
            "artifacts": ["coverage_report.xml"],
            "risks": [],
            "cost_notes": {}
        }
        
        # Update status with evidence
        self.ledger.update_result_status(result_data)
        
        # Add skill usage from result
        result_data["executor"] = "cline_codex"
        result_data["cost_mode"] = "subscription_quota"
        result_data["event"] = "used"
        self.ledger.add_skill_usage(self.handoff_data["handoff_id"], result_data)
        
        # Verify ledger update
        ledger_data = self.ledger.get_ledger()
        handoff_entry = ledger_data["handoffs"][0]
        self.assertEqual(len(handoff_entry["skill_usage_events"]), 2)
        
        used_event = handoff_entry["skill_usage_events"][1]
        self.assertEqual(used_event["event"], "used")
        self.assertEqual(used_event["executor"], "cline_codex")
        self.assertEqual(used_event["cost_mode"], "subscription_quota")
    
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
        self.assertEqual(handoff_entry["status"], self.handoff_data["target"]["status"])
        self.assertEqual(handoff_entry["evidence_status"], "missing")
        self.assertEqual(handoff_entry["artifact_gate_status"], "pending")
    
    def test_multiple_handoffs(self):
        """Test handling multiple handoffs in a single task"""
        # Add second handoff
        handoff_data2 = self.handoff_data.copy()
        handoff_data2["handoff_id"] = "handoff_20260613_000001"
        handoff_data2["target"]["agent_id"] = "ecc_pack"
        
        self.ledger.add_handoff(handoff_data2)
        
        # Verify both handoffs exist
        ledger_data = self.ledger.get_ledger()
        self.assertEqual(len(ledger_data["handoffs"]), 2)
        
        # Verify first handoff
        handoff1 = ledger_data["handoffs"][0]
        self.assertEqual(handoff1["handoff_id"], self.handoff_data["handoff_id"])
        self.assertEqual(handoff1["agent_id"], self.handoff_data["target"]["agent_id"])
        self.assertEqual(handoff1["status"], "proposed")
        self.assertEqual(handoff1["evidence_status"], "missing")
        self.assertEqual(handoff1["artifact_gate_status"], "pending")
        
        # Verify second handoff
        handoff2 = ledger_data["handoffs"][1]
        self.assertEqual(handoff2["handoff_id"], handoff_data2["handoff_id"])
        self.assertEqual(handoff2["agent_id"], handoff_data2["target"]["agent_id"])
        self.assertEqual(handoff2["status"], "proposed")
        self.assertEqual(handoff2["evidence_status"], "missing")
        self.assertEqual(handoff2["artifact_gate_status"], "pending")
    
    def test_ledger_event_recording(self):
        """Test ledger events are recorded in task events"""
        # Verify event was recorded when creating ledger
        events = self.task_events.get_task_events(self.task_id)
        ledger_events = [e for e in events if e["event_type"] == "external_ledger_update"]
        self.assertTrue(len(ledger_events) > 0)
        
        # Verify event was recorded when adding handoff
        last_event = ledger_events[-1]
        self.assertEqual(last_event["handoff_id"], self.handoff_data["handoff_id"])
        self.assertEqual(last_event["agent_id"], self.handoff_data["target"]["agent_id"])
        self.assertEqual(last_event["token_visibility"], "unknown")
        
        # Test event recording when updating result
        result_data = {
            "handoff_id": self.handoff_data["handoff_id"],
            "task_id": self.task_id,
            "executor": {
                "agent_id": "cline_codex",
                "reported_by": "user",
                "billing_mode": "subscription_quota",
                "token_visibility": "unknown"
            },
            "status": "completed",
            "summary": "Successfully implemented feature X",
            "changed_files": ["src/feature_x.py"],
            "commands_run": ["pytest tests/test_feature_x.py"],
            "artifacts": ["coverage_report.xml"],
            "risks": [],
            "cost_notes": {}
        }
        
        self.ledger.update_result_status(result_data)
        
        # Verify event was recorded
        events = self.task_events.get_task_events(self.task_id)
        result_events = [e for e in events if e["event_type"] == "external_result_submitted"]
        self.assertTrue(len(result_events) > 0)
        
        last_event = result_events[-1]
        self.assertEqual(last_event["handoff_id"], self.handoff_data["handoff_id"])
        self.assertEqual(last_event["agent_id"], result_data["executor"]["agent_id"])
        self.assertEqual(last_event["evidence_status"], "complete")

if __name__ == '__main__':
    unittest.main()