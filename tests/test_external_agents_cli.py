"""Tests for the external_agents_cli module."""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


class TestExternalAgentsCLI(unittest.TestCase):
    """Test the external agents CLI commands."""

    def test_external_agents_cli_list_runs(self):
        """Test that 'python -m agent_runtime.external_agents_cli list' exits 0."""
        result = subprocess.run(
            [sys.executable, "-m", "agent_runtime.external_agents_cli", "list"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        self.assertEqual(result.returncode, 0, f"CLI list failed: {result.stderr}")
        self.assertIn("External Agents", result.stdout)
        self.assertIn("cline_codex", result.stdout)
        self.assertIn("ecc_pack", result.stdout)
        self.assertIn("Enabled: False", result.stdout)

    def test_external_agents_cli_list_no_execution(self):
        """list must not invoke subprocess or external tools."""
        result = subprocess.run(
            [sys.executable, "-m", "agent_runtime.external_agents_cli", "list"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        self.assertEqual(result.returncode, 0)
        # Only prints agent info, no command execution
        self.assertNotIn("Traceback", result.stderr)

    def test_create_handoff_cli(self):
        """Test create-handoff CLI generates artifacts."""
        task_id = "cli_test_001"
        output_dir = f"projects/AgentLab/runs/{task_id}"
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_runtime.external_agents_cli",
                "create-handoff",
                "--task-id", task_id,
                "--agent-id", "cline_codex",
                "--title", "CLI Test Handoff",
                "--summary", "Testing CLI create-handoff",
                "--output-dir", output_dir,
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        self.assertEqual(
            result.returncode, 0,
            f"create-handoff failed: {result.stderr}"
        )
        self.assertIn("Handoff Created Successfully", result.stdout)

        yaml_path = Path(output_dir) / "external_handoff.yml"
        md_path = Path(output_dir) / "external_handoff.md"
        self.assertTrue(yaml_path.exists(), f"YAML not created at {yaml_path}")
        self.assertTrue(md_path.exists(), f"MD not created at {md_path}")

    def test_ledger_cli(self):
        """Test ledger CLI shows ledger for a task."""
        task_id = "cli_ledger_test_002"
        output_dir = f"projects/AgentLab/runs/{task_id}"
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # First create a handoff to populate the ledger
        subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_runtime.external_agents_cli",
                "create-handoff",
                "--task-id", task_id,
                "--agent-id", "cline_codex",
                "--title", "Ledger Test",
                "--summary", "Testing CLI ledger",
                "--output-dir", output_dir,
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_runtime.external_agents_cli",
                "ledger",
                "--task-id", task_id,
                "--output-dir", output_dir,
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        self.assertEqual(result.returncode, 0, f"ledger CLI failed: {result.stderr}")
        self.assertIn("External Agent Ledger", result.stdout)
        self.assertIn(task_id, result.stdout)


if __name__ == "__main__":
    unittest.main()