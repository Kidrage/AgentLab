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
    ensure_artifact_promotion_plan,
    validate_content_promotion_readiness,
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

    def test_generated_promotion_plan_treats_patch_diffs_as_evidence_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = self._make_run(root)
            artifact_dir = run_dir / "artifacts" / "web_ui"
            artifact_dir.mkdir(parents=True)
            (artifact_dir / "index.html").write_text("<main>ok</main>\n", encoding="utf-8")
            (artifact_dir / "before_diff_runs_task_web_ui_index.html.patch").write_text(
                "--- before\n",
                encoding="utf-8",
            )
            (artifact_dir / "after_diff_runs_task_web_ui_index.html.patch").write_text(
                "+++ after\n",
                encoding="utf-8",
            )

            plan = ensure_artifact_promotion_plan(root, "Novel", "task_0001")

            promoted_sources = {item["source_run_artifact"] for item in plan["promotions"]}
            self.assertEqual(promoted_sources, {"artifacts/web_ui/index.html"})
            self.assertIn(
                "artifacts/web_ui/before_diff_runs_task_web_ui_index.html.patch",
                plan["evidence_only"],
            )
            self.assertIn(
                "artifacts/web_ui/after_diff_runs_task_web_ui_index.html.patch",
                plan["evidence_only"],
            )

    def test_media_pack_uses_media_artifact_production_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_root = root / "projects" / "Crown"
            project_root.mkdir(parents=True)
            intent = build_artifact_intent(
                root,
                "Crown",
                "task_media",
                {"artifact_steward": {"production_dir": "production/manuscript"}},
                {"pack_id": "media_series_production"},
            )

            self.assertEqual(
                intent["production_dir"],
                str(project_root / "artifacts" / "media"),
            )

    def test_article_pack_does_not_inherit_manuscript_production_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_root = root / "projects" / "Crown"
            project_root.mkdir(parents=True)
            intent = build_artifact_intent(
                root,
                "Crown",
                "task_article",
                {"artifact_steward": {"production_dir": "production/manuscript"}},
                {"pack_id": "article_light"},
            )

            self.assertEqual(intent["production_dir"], str(project_root / "artifacts"))

    def test_narrative_pack_keeps_project_manuscript_production_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_root = root / "projects" / "Crown"
            project_root.mkdir(parents=True)
            intent = build_artifact_intent(
                root,
                "Crown",
                "task_chapter",
                {"artifact_steward": {"production_dir": "production/manuscript"}},
                {"pack_id": "narrative_longform"},
            )

            self.assertEqual(
                intent["production_dir"],
                str(project_root / "production" / "manuscript"),
            )

    def test_narrative_pack_defaults_to_manuscript_without_project_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_root = root / "projects" / "Crown"

            intent = build_artifact_intent(
                root,
                "Crown",
                "task_chapter",
                {},
                {"pack_id": "narrative_longform"},
            )

            self.assertEqual(
                intent["production_dir"],
                str(project_root / "production" / "manuscript"),
            )

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

    def test_skipped_archive_lifecycle_ignores_init_archive_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = self._make_run(root)
            (run_dir / "09_archive_update.md").write_text("# Archive Update\n\nTBD\n", encoding="utf-8")
            _write_yaml(
                run_dir / "lifecycle.yml",
                {
                    "nodes": {
                        "ARCHIVE": {
                            "status": "skipped",
                            "skip_reason": "Production pack article_light excludes ARCHIVE",
                        },
                        "FINALIZE": {"status": "running"},
                    }
                },
            )
            _write_yaml(run_dir / "task_card.yml", {"status": "completed"})

            issues = validate_project_artifact_governance(root, "Novel", "task_0001")

            self.assertFalse(any("ARCHIVE completed" in issue for issue in issues))
            self.assertFalse(any("completed task missing archive_receipt.yml" in issue for issue in issues))

    def test_active_content_current_artifact_must_use_production_fact_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "config").mkdir()
            _write_yaml(
                root / "config" / "content_project_governance.yml",
                {
                    "active_projects": ["NovelGen"],
                    "formal_fact_roots": ["production", "project_brain"],
                    "candidate_roots": ["candidates", "runs"],
                    "archive_roots": ["archive", "_archive"],
                    "legacy_fact_dir_patterns": ["*_rebuild", "v[0-9]*_*", "*legacy*"],
                },
            )
            self._make_run(root, project="NovelGen")
            _write_yaml(
                root / "projects" / "NovelGen" / "project_artifact_index.yml",
                {
                    "version": 1,
                    "project": "NovelGen",
                    "artifacts": [
                        {
                            "artifact_id": "world_bible",
                            "status": "current",
                            "production_path": "v2_rewrite/rewrite_blueprint_v2.md",
                            "source_task": "task_0001",
                            "source_run_artifact": "artifacts/rewrite_blueprint_v2.md",
                        }
                    ],
                },
            )

            issues = validate_project_artifact_governance(root, "NovelGen", "task_0001")

            self.assertTrue(any("must point under production/" in issue for issue in issues))
            self.assertTrue(any("legacy/candidate directory" in issue for issue in issues))

    def test_active_content_task_requires_lineage_and_state_transition(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "config").mkdir()
            _write_yaml(
                root / "config" / "content_project_governance.yml",
                {
                    "active_projects": ["Crown_of_Ash"],
                    "formal_fact_roots": ["production", "project_brain"],
                    "required_content_task_outputs": ["artifact_lineage.yml", "state_transition_proposal.yml"],
                },
            )
            run_dir = self._make_run(root, project="Crown_of_Ash")
            _write_yaml(
                run_dir / "artifact_promotion_plan.yml",
                {
                    "version": 1,
                    "project": "Crown_of_Ash",
                    "task_id": "task_0001",
                    "promotions": [],
                },
            )

            issues = validate_project_artifact_governance(root, "Crown_of_Ash", "task_0001")

            self.assertTrue(any("content task missing required output artifact_lineage.yml" in issue for issue in issues))
            self.assertTrue(any("content task missing required output state_transition_proposal.yml" in issue for issue in issues))
            self.assertTrue(any("content promotion readiness missing artifact_lineage.yml" in issue for issue in issues))
            self.assertTrue(any("content promotion readiness missing state_transition_proposal.yml" in issue for issue in issues))

    def test_active_content_media_candidate_does_not_require_promotion_readiness_when_archive_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "config").mkdir()
            _write_yaml(
                root / "config" / "content_project_governance.yml",
                {
                    "active_projects": ["Crown_of_Ash"],
                    "required_content_task_outputs": ["artifact_lineage.yml", "state_transition_proposal.yml"],
                },
            )
            run_dir = self._make_run(root, project="Crown_of_Ash")
            _write_yaml(
                run_dir / "workflow_plan.yml",
                {
                    "project": "Crown_of_Ash",
                    "task_id": "task_0001",
                    "route": {
                        "agents": [
                            "Supervisor",
                            "ArtifactProducer",
                            "TesterAuditor",
                            "Verifier",
                            "Archivist",
                        ]
                    },
                    "production_pack": {
                        "pack_id": "media_series_production",
                        "lifecycle_nodes": [
                            "INIT_TASK",
                            "CONTEXT_PROFILE",
                            "CONTEXT_BUDGET",
                            "CONTEXT_PACK",
                            "PREPARE_PLAN",
                            "SUPERVISOR_PLAN",
                            "ARTIFACT_PRODUCTION",
                            "VALIDATION",
                            "VERIFY",
                            "SELF_CHECK",
                            "FINALIZE",
                        ],
                    },
                },
            )
            _write_yaml(
                run_dir / "lifecycle.yml",
                {
                    "nodes": {
                        "ARCHIVE": {
                            "status": "skipped",
                            "skip_reason": "Production pack media_series_production excludes ARCHIVE",
                        },
                        "FINALIZE": {"status": "completed"},
                    }
                },
            )
            _write_yaml(run_dir / "state.yml", {"status": "completed"})

            issues = validate_project_artifact_governance(root, "Crown_of_Ash", "task_0001")

            self.assertFalse(any("content task missing required output" in issue for issue in issues))
            self.assertFalse(any("content promotion readiness missing" in issue for issue in issues))
            self.assertFalse(any("completed task missing archive_receipt.yml" in issue for issue in issues))

    def test_active_content_archive_protocol_blocks_without_readiness_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "config").mkdir()
            _write_yaml(
                root / "config" / "content_project_governance.yml",
                {"active_projects": ["Crown_of_Ash"]},
            )
            run_dir = self._make_run(root, project="Crown_of_Ash")
            candidate = run_dir / "artifacts" / "chapter_01.md"
            candidate.parent.mkdir(parents=True)
            candidate.write_text("new chapter\n", encoding="utf-8")
            _write_yaml(
                run_dir / "artifact_promotion_plan.yml",
                {
                    "version": 1,
                    "project": "Crown_of_Ash",
                    "task_id": "task_0001",
                    "promotions": [
                        {
                            "artifact_id": "chapter_01",
                            "source_run_artifact": "artifacts/chapter_01.md",
                            "production_path": "production/manuscript/chapter_01.md",
                        }
                    ],
                },
            )

            receipt = apply_archive_protocol(root, "Crown_of_Ash", "task_0001")

            self.assertEqual(receipt["status"], "blocked")
            self.assertTrue(any("content promotion readiness missing artifact_lineage.yml" in err for err in receipt["errors"]))
            self.assertFalse((root / "projects/Crown_of_Ash/production/manuscript/chapter_01.md").exists())

    def test_content_promotion_readiness_checks_archive_receipt_and_single_current(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "config").mkdir()
            _write_yaml(
                root / "config" / "content_project_governance.yml",
                {"active_projects": ["Crown_of_Ash"]},
            )
            run_dir = self._make_run(root, project="Crown_of_Ash")
            _write_yaml(run_dir / "artifact_lineage.yml", {"modified": ["production/manuscript/chapter_01.md"]})
            _write_yaml(run_dir / "state_transition_proposal.yml", {"events": []})
            _write_yaml(
                root / "projects" / "Crown_of_Ash" / "project_artifact_index.yml",
                {
                    "artifacts": [
                        {"artifact_id": "chapter_01", "status": "current", "production_path": "production/manuscript/chapter_01.md"},
                        {"artifact_id": "chapter_01", "status": "current", "production_path": "production/manuscript/chapter_01_v2.md"},
                    ]
                },
            )

            issues = validate_content_promotion_readiness(
                root,
                "Crown_of_Ash",
                "task_0001",
                run_dir,
                require_archive_receipt=True,
            )

            self.assertTrue(any("missing archive_receipt.yml" in issue for issue in issues))
            self.assertTrue(any("single-current invariant" in issue for issue in issues))


if __name__ == "__main__":
    main()
