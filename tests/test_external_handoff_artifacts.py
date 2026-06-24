import subprocess
import unittest
import unittest.mock
import time
from pathlib import Path
from agent_runtime.external_agents.handoff import ExternalHandoff

class TestExternalHandoffArtifacts(unittest.TestCase):
    def setUp(self):
        """Set up test environment"""
        self.task_id = "task_0035"
        self.output_dir = f"projects/AgentLab/runs/{self.task_id}"
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    def test_create_handoff_does_not_execute_external_agent(self):
        """Handoff creation must not invoke subprocess or execute external tools."""
        handoff = ExternalHandoff(self.task_id, self.output_dir)

        with unittest.mock.patch("subprocess.run") as mock_run:
            handoff.create_handoff(
                "cline_codex", "Implement feature X", "Description of feature X"
            )
            mock_run.assert_not_called()

        # Verify artifacts exist
        yaml_path = Path(self.output_dir) / "external_handoff.yml"
        md_path = Path(self.output_dir) / "external_handoff.md"
        self.assertTrue(yaml_path.exists(), "external_handoff.yml not created")
        self.assertTrue(md_path.exists(), "external_handoff.md not created")

        # Verify target.status is proposed (agent is disabled)
        import yaml as _yaml
        with open(yaml_path) as f:
            data = _yaml.safe_load(f)
        self.assertEqual(data["target"]["status"], "proposed")

        # Verify markdown contains required sections
        with open(md_path) as f:
            md = f.read()
        self.assertIn("## Constraints", md)
        self.assertIn("## Required Outputs", md)
        self.assertIn("## Evidence Requirements", md)

    def test_handoff_artifact_creation(self):
        """Test creation of both YAML and markdown artifacts"""
        handoff = ExternalHandoff(self.task_id, self.output_dir)
        result = handoff.create_handoff("cline_codex", "Implement feature X", "Description of feature X")

        yaml_path = Path(self.output_dir) / "external_handoff.yml"
        self.assertTrue(yaml_path.exists())

        self.assertEqual(result["task_id"], self.task_id)
        self.assertEqual(result["project"], "AgentLab")
        self.assertEqual(result["target"]["agent_id"], "cline_codex")
        self.assertEqual(result["target"]["status"], "proposed")

    def test_handoff_markdown_content(self):
        """Test markdown artifact contains required information"""
        handoff = ExternalHandoff(self.task_id, self.output_dir)
        result = handoff.create_handoff("cline_codex", "Implement feature X", "Description of feature X")

        md_path = Path(self.output_dir) / "external_handoff.md"
        self.assertTrue(md_path.exists())

        with open(md_path, 'r') as f:
            md_content = f.read()

        self.assertIn("# External Agent Handoff", md_content)
        self.assertIn(f"**Handoff ID:** {result['handoff_id']}", md_content)
        self.assertIn(f"**Task ID:** {self.task_id}", md_content)
        self.assertIn("## Target Executor", md_content)
        self.assertIn("## Objective", md_content)
        self.assertIn("## Constraints", md_content)
        self.assertIn("## Required Outputs", md_content)
        self.assertIn("## Evidence Requirements", md_content)
        self.assertIn("## Budget", md_content)
        self.assertIn("How to submit result back to AgentLab", md_content)

    def test_handoff_directory_structure(self):
        """Test handoff artifacts are written to correct directory"""
        custom_dir = "test_handoff_dir"
        Path(custom_dir).mkdir(exist_ok=True)

        handoff = ExternalHandoff(self.task_id, custom_dir)
        handoff.create_handoff("cline_codex", "Implement feature X", "Description of feature X")

        self.assertTrue((Path(custom_dir) / "external_handoff.yml").exists())
        self.assertTrue((Path(custom_dir) / "external_handoff.md").exists())

        # Clean up
        for f in Path(custom_dir).glob("*"):
            f.unlink()
        Path(custom_dir).rmdir()

    def test_disabled_agent_handoff(self):
        """Test handoff creation with disabled agent"""
        handoff = ExternalHandoff(self.task_id, self.output_dir)
        result = handoff.create_handoff("ecc_pack", "Security review", "Review code for vulnerabilities")

        self.assertEqual(result["target"]["status"], "proposed")
        self.assertEqual(result["budget"]["external_token_visibility"], "unknown")

    def test_multiple_handoffs(self):
        """Test multiple handoffs can be created for a task"""
        handoff1 = ExternalHandoff(self.task_id, self.output_dir)
        result1 = handoff1.create_handoff("cline_codex", "Implement feature X", "First handoff")

        # Small delay to ensure unique handoff IDs
        time.sleep(0.1)

        handoff2 = ExternalHandoff(self.task_id, self.output_dir)
        result2 = handoff2.create_handoff("ecc_pack", "Security review", "Second handoff")

        self.assertNotEqual(result1["handoff_id"], result2["handoff_id"])

if __name__ == '__main__':
    unittest.main()
