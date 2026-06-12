import unittest
from pathlib import Path
from agent_runtime.external_agents.handoff import ExternalHandoff

class TestExternalHandoffArtifacts(unittest.TestCase):
    def setUp(self):
        """Set up test environment"""
        self.task_id = "task_0035"
        self.output_dir = f"projects/AgentLab/runs/{self.task_id}"
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        
    def test_handoff_artifact_creation(self):
        """Test creation of both YAML and markdown artifacts"""
        handoff = ExternalHandoff(self.task_id, self.output_dir)
        result = handoff.create_handoff("cline_codex", "Implement feature X", "Description of feature X")
        
        # Verify YAML file exists
        yaml_path = Path(self.output_dir) / "external_handoff.yml"
        self.assertTrue(yaml_path.exists())
        
        # Verify YAML content
        with open(yaml_path, 'r') as f:
            yaml_data = result  # Handoff data should match return value
            
        self.assertEqual(yaml_data["task_id"], self.task_id)
        self.assertEqual(yaml_data["project"], "AgentLab")
        self.assertEqual(yaml_data["target"]["agent_id"], "cline_codex")
        self.assertEqual(yaml_data["target"]["status"], "proposed")
        
    def test_handoff_markdown_content(self):
        """Test markdown artifact contains required information"""
        handoff = ExternalHandoff(self.task_id, self.output_dir)
        result = handoff.create_handoff("cline_codex", "Implement feature X", "Description of feature X")
        
        # Verify markdown content
        md_path = Path(self.output_dir) / "external_handoff.md"
        self.assertTrue(md_path.exists())
        
        with open(md_path, 'r') as f:
            md_content = f.read()
            
        # Verify key sections exist
        self.assertIn(f"# External Agent Handoff - {result['handoff_id']}", md_content)
        self.assertIn(f"**Task ID:** {self.task_id}", md_content)
        self.assertIn(f"**Project:** AgentLab", md_content)
        self.assertIn("## Target Agent", md_content)
        self.assertIn("## Objective", md_content)
        self.assertIn("## Constraints", md_content)
        self.assertIn("## Required Outputs", md_content)
        self.assertIn("## Budget Information", md_content)
        
    def test_handoff_directory_structure(self):
        """Test handoff artifacts are written to correct directory"""
        custom_dir = "test_handoff_dir"
        Path(custom_dir).mkdir(exist_ok=True)
        
        handoff = ExternalHandoff(self.task_id, custom_dir)
        handoff.create_handoff("cline_codex", "Implement feature X", "Description of feature X")
        
        # Verify artifacts in custom directory
        self.assertTrue(Path(custom_dir) / "external_handoff.yml".exists())
        self.assertTrue(Path(custom_dir) / "external_handoff.md".exists())
        
        # Clean up
        Path(custom_dir).rmtree()
        
    def test_handoff_with_empty_summary(self):
        """Test handoff creation with empty summary"""
        handoff = ExternalHandoff(self.task_id, self.output_dir)
        result = handoff.create_handoff("cline_codex", "Implement feature X", "")
        
        # Verify YAML content
        self.assertEqual(result["objective"]["summary"], "")
        
        # Verify markdown content
        md_path = Path(self.output_dir) / "external_handoff.md"
        with open(md_path, 'r') as f:
            md_content = f.read()
            
        self.assertIn("## Objective", md_content)
        self.assertIn("### Implement feature X", md_content)
        self.assertIn("Description of feature X", md_content)
        self.assertIn("## Constraints", md_content)
        self.assertIn("## Required Outputs", md_content)
        self.assertIn("## Budget Information", md_content)
        
    def test_handoff_with_special_characters(self):
        """Test handoff creation with special characters"""
        handoff = ExternalHandoff(self.task_id, self.output_dir)
        result = handoff.create_handoff("cline_codex", "Implement feature: X", "Description with\nnewlines and special characters: > < &")
        
        # Verify YAML content
        self.assertEqual(result["objective"]["title"], "Implement feature: X")
        self.assertEqual(result["objective"]["summary"], "Description with\nnewlines and special characters: > < &")
        
        # Verify markdown content
        md_path = Path(self.output_dir) / "external_handoff.md"
        with open(md_path, 'r') as f:
            md_content = f.read()
            
        self.assertIn("### Implement feature: X", md_content)
        self.assertIn("Description with\nnewlines and special characters: > < &", md_content)

if __name__ == '__main__':
    unittest.main()