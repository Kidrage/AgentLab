from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from artifact_contract import artifact_content_issues, validate_artifacts
from lifecycle_graph import create_lifecycle, load_lifecycle, mark_node_started, save_lifecycle
from memory_writer import apply_archivist_memory_edits
from pipeline_runner import _block_on_artifact_gate, run_next_node


class ArtifactGateTests(TestCase):
    def test_tool_call_report_is_invalid(self) -> None:
        issues = artifact_content_issues(
            "02_reposcout_report.md",
            '<tool_call>{"shell": "ls -la"}</tool_call>',
        )
        self.assertIn("unexecuted tool call in report", issues)

    def test_execution_placeholder_is_invalid(self) -> None:
        issues = artifact_content_issues(
            "06_implementation_report.md",
            "# Implementation Report\n\nCommands run: None\nNo implementation work was performed.\n",
        )
        self.assertIn("execution placeholder or no command evidence", issues)

    def test_artifact_gate_blocks_lifecycle_node(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            create_lifecycle(run_dir, {"route": {"agents": ["Supervisor", "RepoScout"]}})
            mark_node_started(run_dir, "REPO_CONTEXT")

            result = _block_on_artifact_gate(
                run_dir,
                "AgentLab",
                "task_gate",
                "REPO_CONTEXT",
                "RepoScout",
                ["unexecuted tool call in report"],
                report_path=run_dir / "02_reposcout_report.md",
            )

            lifecycle = load_lifecycle(run_dir)
            self.assertEqual(result["status"], "paused")
            self.assertEqual(lifecycle["nodes"]["REPO_CONTEXT"]["status"], "failed")
            self.assertTrue((run_dir / "USER_DECISION_REQUIRED.md").exists())

    def test_fake_provider_agent_node_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = root / "projects" / "Demo" / "runs" / "task_fake"
            run_dir.mkdir(parents=True)
            (run_dir / "workflow_plan.yml").write_text(
                "route:\n  agents:\n    - Supervisor\n    - RepoScout\n",
                encoding="utf-8",
            )
            lifecycle = create_lifecycle(run_dir, {"route": {"agents": ["Supervisor", "RepoScout"]}})
            for node in ["INIT_TASK", "PREPARE_PLAN", "SUPERVISOR_PLAN"]:
                lifecycle["nodes"][node]["status"] = "completed"
            lifecycle["nodes"]["REPO_CONTEXT"]["status"] = "waiting"
            save_lifecycle(run_dir, lifecycle)

            result = run_next_node(root, "Demo", "task_fake", fake_provider=True)

            self.assertEqual(result["status"], "completed")
            self.assertTrue((run_dir / "02_reposcout_report.md").exists())
            lifecycle = load_lifecycle(run_dir)
            self.assertEqual(lifecycle["nodes"]["REPO_CONTEXT"]["status"], "completed")


class MemoryWriterTests(TestCase):
    def test_archivist_memory_edit_applies_only_allowed_agent_docs_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_root = root / "projects" / "Demo"
            agent_docs = project_root / "agent_docs"
            config = root / "config"
            agent_docs.mkdir(parents=True)
            config.mkdir()
            (config / "memory_policy.yml").write_text(
                "records:\n  project_memory:\n    - 03_DECISION_LOG.md\n",
                encoding="utf-8",
            )
            target = agent_docs / "03_DECISION_LOG.md"
            target.write_text("old decision\n", encoding="utf-8")

            output = "\n".join([
                "# Archivist Report",
                "",
                "<<<AGENTLAB_EDIT agent_docs/03_DECISION_LOG.md",
                "------- SEARCH",
                "old decision",
                "=" * 7,
                "old decision",
                "new decision",
                "+" * 7 + " REPLACE",
                ">>>",
                "",
            ])
            result = apply_archivist_memory_edits(root, project_root, output)

            self.assertTrue(result.ok)
            self.assertEqual(result.applied, 1)
            self.assertIn("new decision", target.read_text(encoding="utf-8"))

    def test_archivist_memory_edit_rejects_non_memory_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_root = root / "projects" / "Demo"
            project_root.mkdir(parents=True)
            config = root / "config"
            config.mkdir()
            (config / "memory_policy.yml").write_text(
                "records:\n  project_memory:\n    - 03_DECISION_LOG.md\n",
                encoding="utf-8",
            )
            readme = project_root / "README.md"
            readme.write_text("old\n", encoding="utf-8")

            output = "\n".join([
                "# Archivist Report",
                "",
                "<<<AGENTLAB_EDIT README.md",
                "------- SEARCH",
                "old",
                "=" * 7,
                "new",
                "+" * 7 + " REPLACE",
                ">>>",
                "",
            ])
            result = apply_archivist_memory_edits(root, project_root, output)

            self.assertFalse(result.ok)
            self.assertEqual(result.applied, 0)
            self.assertIn("File not in Supervisor-approved scope", result.results[0].error)
            self.assertEqual("old\n", readme.read_text(encoding="utf-8"))


class ArtifactContractTests(TestCase):
    def test_validate_artifacts_reports_semantic_issues(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "workflow_plan.yml").write_text(
                "route:\n  agents:\n    - Coder\n",
                encoding="utf-8",
            )
            for name in [
                "user_request.md",
                "state.yml",
                "progress.yml",
                "task_snapshot.yml",
                "brain_decisions.yml",
                "cost_ledger.yml",
                "lifecycle.yml",
                "self_check_report.yml",
                "task_card.yml",
                "artifact_manifest.yml",
            ]:
                (run_dir / name).write_text("ok: true\n", encoding="utf-8")
            (run_dir / "06_implementation_report.md").write_text(
                "# Implementation Report\n\nCommands run: None\n",
                encoding="utf-8",
            )

            result = validate_artifacts(run_dir)

            self.assertFalse(result["valid"])
            self.assertIn(
                {"file": "06_implementation_report.md", "issue": "execution placeholder or no command evidence"},
                result["issues"],
            )


if __name__ == "__main__":
    main()
