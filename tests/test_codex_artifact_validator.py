from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from codex_artifact_validator import validate_artifacts


class CodexArtifactValidatorTests(TestCase):
    def test_lifecycle_mvp_artifact_names_are_valid_equivalents(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_root = Path(td) / "projects" / "Demo"
            run_dir = project_root / "runs" / "task_0001"
            run_dir.mkdir(parents=True)

            for name in [
                "user_request.md",
                "01_supervisor_plan.md",
                "02_reposcout_report.md",
                "03_research_notes.md",
                "04_interface_map.md",
                "05_coder_prompt.md",
                "06_implementation_report.md",
                "07_validation_report.md",
                "08_audit_report.md",
                "09_archive_update.md",
            ]:
                (run_dir / name).write_text(f"# {name}\n\nEvidence recorded.\n", encoding="utf-8")

            for name in [
                "workflow_plan.yml",
                "state.yml",
                "progress.yml",
                "artifact_lineage.yml",
                "artifact_promotion_plan.yml",
                "archive_receipt.yml",
                "artifact_manifest.yml",
                "lifecycle.yml",
            ]:
                (run_dir / name).write_text("version: 1\n", encoding="utf-8")
            (project_root / "project_artifact_index.yml").write_text(
                "version: 1\nproject: Demo\nartifacts: []\n",
                encoding="utf-8",
            )

            (run_dir / "handoff_packet.yml").write_text(
                yaml.safe_dump(
                    {
                        "task_id": "task_0001",
                        "project": "Demo",
                        "execution_mode": "dry_run",
                        "status": "completed",
                        "last_completed_agent": "Archivist",
                        "next_agent": None,
                        "resume_available": True,
                        "artifacts": {},
                        "code_state": {},
                        "validation": {},
                        "resume_instructions": {},
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            result = validate_artifacts(project_root, "task_0001")

            self.assertEqual(result["result"], "pass")
            self.assertEqual(result["missing_reports"], [])
            self.assertTrue(result["handoff_packet_valid"])

    def test_missing_handoff_still_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_root = Path(td) / "projects" / "Demo"
            run_dir = project_root / "runs" / "task_0002"
            run_dir.mkdir(parents=True)
            (run_dir / "user_request.md").write_text("# Request\n", encoding="utf-8")

            result = validate_artifacts(project_root, "task_0002")

            self.assertEqual(result["result"], "fail")
            self.assertIn("handoff_packet.yml not found", result["handoff_packet_issues"])


if __name__ == "__main__":
    main()
