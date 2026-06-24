import unittest
from pathlib import Path
from agent_runtime.external_agents.result import ExternalResult
from agent_runtime.external_agents.registry import registry as agent_registry

class TestExternalResultSubmission(unittest.TestCase):
    def setUp(self):
        """Set up test environment"""
        self.task_id = "task_0035"
        self.handoff_id = "handoff_20260612_235959"
        self.output_dir = f"projects/AgentLab/runs/{self.task_id}"
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    def test_result_validation_missing_fields(self):
        """Test result submission with missing required fields"""
        result = ExternalResult(self.task_id, self.handoff_id, self.output_dir)

        # Missing handoff_id
        with self.assertRaises(ValueError):
            result.submit_result({
                "task_id": self.task_id,
                "summary": "Test result summary"
            })

        # Missing task_id
        with self.assertRaises(ValueError):
            result.submit_result({
                "handoff_id": self.handoff_id,
                "summary": "Test result summary"
            })

        # Missing executor
        with self.assertRaises(ValueError):
            result.submit_result({
                "handoff_id": self.handoff_id,
                "task_id": self.task_id,
                "summary": "Test result summary"
            })

    def test_executor_validation(self):
        """Test executor field validation"""
        result = ExternalResult(self.task_id, self.handoff_id, self.output_dir)

        # Missing token_visibility
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

    def test_token_visibility_must_be_unknown(self):
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

    def test_evidence_requirements_changed_files(self):
        """Test missing evidence for changed files"""
        result = ExternalResult(self.task_id, self.handoff_id, self.output_dir)

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

    def test_evidence_build_claims(self):
        """Test missing evidence for build/test claims"""
        result = ExternalResult(self.task_id, self.handoff_id, self.output_dir)

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
                "summary": "Ran tests and fixed the code"
            })

    def test_result_submission_success(self):
        """Test successful result submission"""
        result = ExternalResult(self.task_id, self.handoff_id, self.output_dir)

        result_data = {
            "handoff_id": self.handoff_id,
            "task_id": self.task_id,
            "status": "completed",
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

        self.assertEqual(submitted_result["status"], "completed")
        self.assertEqual(submitted_result["executor"]["agent_id"], "cline_codex")
        self.assertEqual(submitted_result["executor"]["token_visibility"], "unknown")
        self.assertEqual(submitted_result["evidence_status"], "complete")

        # Verify YAML file was created
        yaml_path = Path(self.output_dir) / "external_result.yml"
        self.assertTrue(yaml_path.exists())

    def test_result_submission_partial(self):
        """Test result submission with partial evidence"""
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
            "status": "partial",
            "summary": "Partially implemented feature X",
            "changed_files": ["src/feature_x.py"],
            "commands_run": ["pytest tests/test_feature_x.py"],
            "artifacts": ["coverage_report.xml"]
        }

        submitted_result = result.submit_result(result_data)
        self.assertEqual(submitted_result["evidence_status"], "complete")

if __name__ == '__main__':
    unittest.main()