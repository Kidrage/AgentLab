import unittest
import yaml
from pathlib import Path
from agent_runtime.external_agents.result import ExternalResult
from agent_runtime.task_index import TaskIndex

class TestExternalResultSubmission(unittest.TestCase):
    def setUp(self):
        """Set up test environment"""
        self.task_id = "task_0035"
        self.handoff_id = "handoff_20260612_235959"
        self.output_dir = f"projects/AgentLab/runs/{self.task_id}"
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        
        # Create a sample handoff file
        handoff_data = {
            "handoff_id": self.handoff_id,
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
            "budget": {
                "billing_mode": "subscription_quota",
                "api_cost_visible": False,
                "external_token_visibility": "unknown"
            }
        }
        
        with open(Path(self.output_dir) / "external_handoff.yml", 'w') as f:
            yaml.safe_dump(handoff_data, f)
            
        # Initialize task index
        self.task_index = TaskIndex()
        self.task_index.create_task(self.task_id, "Test Task", "External Result Submission Test")
    
    def test_result_validation(self):
        """Test result submission validation"""
        result = ExternalResult(self.task_id, self.handoff_id, self.output_dir)
        
        # Test missing required fields
        with self.assertRaises(ValueError):
            result.submit_result({
                "handoff_id": self.handoff_id,
                "summary": "Test result summary"
            })
            
        with self.assertRaises(ValueError):
            result.submit_result({
                "task_id": self.task_id,
                "summary": "Test result summary"
            })
            
        with self.assertRaises(ValueError):
            result.submit_result({
                "handoff_id": self.handoff_id,
                "task_id": self.task_id
            })
            
    def test_executor_validation(self):
        """Test executor field validation"""
        result = ExternalResult(self.task_id, self.handoff_id, self.output_dir)
        
        # Test missing executor fields
        with self.assertRaises(ValueError):
            result.submit_result({
                "handoff_id": self.handoff_id,
                "task_id": self.task_id,
                "executor": {
                    "agent_id": "cline_codex",
                    "reported_by": "user",
                    "billing_mode": "subscription_quota"
                },
                "summary": "Test result summary"
            })
            
        with self.assertRaises(ValueError):
            result.submit_result({
                "handoff_id": self.handoff_id,
                "task_id": self.task_id,
                "executor": {
                    "agent_id": "cline_codex",
                    "reported_by": "user",
                    "token_visibility": "unknown"
                },
                "summary": "Test result summary"
            })
            
    def test_token_visibility_validation(self):
        """Test token visibility is properly validated"""
        result = ExternalResult(self.task_id, self.handoff_id, self.output_dir)
        
        with self.assertRaises(ValueError):
            result.submit_result({
                "handoff_id": self.handoff_id,
                "task_id": self.task_id,
                "executor": {
                    "agent_id": "cline_codex",
                    "reported_by": "user",
                    "billing_mode": "subscription_quota",
                    "token_visibility": "visible"
                },
                "summary": "Test result summary"
            })
            
    def test_evidence_requirements(self):
        """Test evidence requirement validation"""
        result = ExternalResult(self.task_id, self.handoff_id, self.output_dir)
        
        # Test missing evidence for changed files
        with self.assertRaises(ValueError):
            result.submit_result({
                "handoff_id": self.handoff_id,
                "task_id": self.task_id,
                "executor": {
                    "agent_id": "cline_codex",
                    "reported_by": "user",
                    "billing_mode": "subscription_quota",
                    "token_visibility": "unknown"
                },
                "summary": "Test result summary",
                "changed_files": ["file1.py", "file2.py"]
            })
            
        # Test missing evidence for build/test claims
        with self.assertRaises(ValueError):
            result.submit_result({
                "handoff_id": self.handoff_id,
                "task_id": self.task_id,
                "executor": {
                    "agent_id": "cline_codex",
                    "reported_by": "user",
                    "billing_mode": "subscription_quota",
                    "token_visibility": "unknown"
                },
                "summary": "Ran tests and made changes to improve code quality"
            })
            
    def test_result_submission(self):
        """Test successful result submission"""
        result = ExternalResult(self.task_id, self.handoff_id, self.output_dir)
        
        result_data = {
            "handoff_id": self.handoff_id,
            "task_id": self.task_id,
            "executor": {
                "agent_id": "cline_codex",
                "reported_by": "user",
                "billing_mode": "subscription_quota",
                "token_visibility": "unknown"
            },
            "summary": "Successfully implemented feature X",
            "changed_files": ["src/feature_x.py"],
            "commands_run": ["pytest tests/test_feature_x.py"],
            "artifacts": ["coverage_report.xml"]
        }
        
        submitted_result = result.submit_result(result_data)
        
        # Verify result data
        self.assertEqual(submitted_result["status"], "completed")
        self.assertEqual(submitted_result["executor"]["agent_id"], "cline_codex")
        self.assertEqual(submitted_result["executor"]["token_visibility"], "unknown")
        
        # Verify YAML file was created
        yaml_path = Path(self.output_dir) / "external_result.yml"
        self.assertTrue(yaml_path.exists())
        
        with open(yaml_path, 'r') as f:
            yaml_data = yaml.safe_load(f)
            self.assertEqual(yaml_data["task_id"], self.task_id)
            self.assertEqual(yaml_data["executor"]["agent_id"], "cline_codex")
            self.assertEqual(yaml_data["evidence_status"], "complete")
            
    def test_result_ledger_event(self):
        """Test result submission records events in task ledger"""
        result = ExternalResult(self.task_id, self.handoff_id, self.output_dir)
        
        result_data = {
            "handoff_id": self.handoff_id,
            "task_id": self.task_id,
            "executor": {
                "agent_id": "cline_codex",
                "reported_by": "user",
                "billing_mode": "subscription_quota",
                "token_visibility": "unknown"
            },
            "summary": "Successfully implemented feature X",
            "changed_files": ["src/feature_x.py"],
            "commands_run": ["pytest tests/test_feature_x.py"],
            "artifacts": ["coverage_report.xml"]
        }
        
        result.submit_result(result_data)
        
        # Verify event was recorded
        events = self.task_index.get_task_events(self.task_id)
        result_events = [e for e in events if e["event_type"] == "external_result_submitted"]
        
        self.assertTrue(len(result_events) > 0)
        last_event = result_events[-1]
        
        self.assertEqual(last_event["handoff_id"], self.handoff_id)
        self.assertEqual(last_event["agent_id"], "cline_codex")
        self.assertEqual(last_event["token_visibility"], "unknown")
        self.assertEqual(last_event["evidence_status"], "complete")
            
if __name__ == '__main__':
    unittest.main()