from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from project_artifact_steward import (
    apply_archive_protocol,
    build_artifact_intent,
    validate_project_artifact_governance,
)


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


class ProjectArtifactStewardTests(TestCase):
    def _make_run(self, root: Path, project: str = "Novel", task_id: str = "task_0001") -> Path:
        run_dir = root / "projects" / project / "runs" / task_id
        run_dir.mkdir(parents=True)
        (run_dir / "user_request.md").write_text(
            "# Revise Chapter 1\n\nReplace the current chapter draft.\n",
            encoding="utf-8",
        )
        intent = build_artifact_intent(root, project, task_id)
        _write_yaml(
            run_dir / "workflow_plan.yml",
            {
                "project": project,
                "task_id": task_id,
                "route": {"agents": ["Supervisor", "Coder", "Archivist"]},
                "artifact_intent": intent,
            },
        )
        return run_dir

    def test_archive_protocol_promotes_candidate_archives_old_and_updates_index(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = self._make_run(root)
            production = root / "projects" / "Novel" / "artifacts" / "chapter_01.md"
            production.parent.mkdir(parents=True)
            production.write_text("old chapter\n", encoding="utf-8")
            candidate = run_dir / "artifacts" / "chapter_01.md"
            candidate.parent.mkdir(parents=True)
            candidate.write_text("new chapter\n", encoding="utf-8")
            _write_yaml(
                run_dir / "artifact_promotion_plan.yml",
                {
                    "version": 1,
                    "project": "Novel",
                    "task_id": "task_0001",
                    "promotions": [
                        {
                            "artifact_id": "chapter_01",
                            "source_run_artifact": "artifacts/chapter_01.md",
                            "production_path": "artifacts/chapter_01.md",
                            "action": "replace",
                        }
                    ],
                },
            )

            receipt = apply_archive_protocol(root, "Novel", "task_0001")

            self.assertEqual(receipt["status"], "completed")
            self.assertEqual(production.read_text(encoding="utf-8"), "new chapter\n")
            archived = receipt["promotions_applied"][0]["archive_path"]
            self.assertTrue((root / "projects" / "Novel" / archived).exists())
            index = yaml.safe_load(
                (root / "projects" / "Novel" / "project_artifact_index.yml").read_text(encoding="utf-8")
            )
            current = [a for a in index["artifacts"] if a["artifact_id"] == "chapter_01" and a["status"] == "current"]
            self.assertEqual(len(current), 1)
            self.assertEqual(current[0]["source_task"], "task_0001")
            self.assertEqual(current[0]["source_run_artifact"], "artifacts/chapter_01.md")
            self.assertFalse(validate_project_artifact_governance(root, "Novel", "task_0001"))

    def test_production_report_contamination_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._make_run(root)
            report = root / "projects" / "Novel" / "artifacts" / "07_validation_report.md"
            report.parent.mkdir(parents=True)
            report.write_text("# Validation Report\n", encoding="utf-8")

            issues = validate_project_artifact_governance(root, "Novel", "task_0001")

            self.assertTrue(any("contains evidence/report file" in issue for issue in issues))

    def test_replace_without_archived_old_version_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._make_run(root)
            _write_yaml(
                root / "projects" / "Novel" / "project_artifact_index.yml",
                {
                    "version": 1,
                    "project": "Novel",
                    "artifacts": [
                        {
                            "artifact_id": "chapter_01",
                            "status": "current",
                            "current_version": "v2",
                            "production_path": "artifacts/chapter_01.md",
                            "source_task": "task_0001",
                            "source_run_artifact": "artifacts/chapter_01.md",
                            "supersedes": "v1",
                            "archived_versions": [],
                        }
                    ],
                },
            )

            issues = validate_project_artifact_governance(root, "Novel", "task_0001")

            self.assertTrue(any("supersedes an old version without archived_versions" in issue for issue in issues))

    def test_undeclared_production_path_in_lineage_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = self._make_run(root)
            _write_yaml(
                run_dir / "artifact_lineage.yml",
                {
                    "version": 1,
                    "project": "Novel",
                    "task_id": "task_0001",
                    "added": [{"path": "projects/Novel/artifacts/chapter_02.md"}],
                },
            )

            issues = validate_project_artifact_governance(root, "Novel", "task_0001")

            self.assertTrue(any("undeclared production path" in issue for issue in issues))

    def test_completed_task_requires_archive_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = self._make_run(root)
            _write_yaml(run_dir / "state.yml", {"status": "completed"})

            issues = validate_project_artifact_governance(root, "Novel", "task_0001")

            self.assertTrue(any("completed task missing archive_receipt.yml" in issue for issue in issues))


if __name__ == "__main__":
    main()
