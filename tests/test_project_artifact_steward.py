from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from project_artifact_steward import (  # noqa: E402
    apply_archive_protocol,
    build_artifact_intent,
    ensure_artifact_promotion_plan,
    validate_content_promotion_readiness,
    validate_project_artifact_governance,
)
from narrative.state_store import NarrativeStateStore  # noqa: E402
from agent_runtime.project_truth import ProjectTruthStore  # noqa: E402


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
            _write_yaml(
                root / "config" / "knowledge_system.yml",
                {"indexing": {"project_allowlist": ["Novel"]}},
            )
            run_dir = self._make_run(root)
            production = (
                root
                / "projects"
                / "Novel"
                / "production"
                / "artifacts"
                / "chapter_01.md"
            )
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
                            "production_path": "production/artifacts/chapter_01.md",
                            "action": "replace",
                        }
                    ],
                },
            )

            receipt = apply_archive_protocol(root, "Novel", "task_0001")

            self.assertEqual(receipt["status"], "completed")
            self.assertEqual(receipt["knowledge_sync"]["status"], "SYNCED")
            self.assertEqual(
                receipt["knowledge_sync"]["namespaces"],
                ["project.Novel", "domain.longform_narrative"],
            )
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
            self.assertEqual(
                current[0]["production_sha256"],
                hashlib.sha256(production.read_bytes()).hexdigest(),
            )
            self.assertFalse(validate_project_artifact_governance(root, "Novel", "task_0001"))

    def test_enforced_truth_promotion_has_one_current_semantic_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_root = root / "projects" / "Novel"
            _write_yaml(
                root / "config" / "knowledge_system.yml",
                {"indexing": {"project_allowlist": ["Novel"]}},
            )
            _write_yaml(
                project_root / "project.yml",
                {
                    "project_id": "Novel",
                    "features": {
                        "project_truth_mode": "enforced",
                        "enable_project_agents": True,
                    },
                    "workspace": {"isolation": "required"},
                },
            )
            ProjectTruthStore(project_root).initialize("Novel")

            for task_id, content in (
                ("task_0001", "first accepted chapter\n"),
                ("task_0002", "revised accepted chapter\n"),
            ):
                run_dir = self._make_run(root, task_id=task_id)
                candidate = run_dir / "artifacts" / "chapter_01.md"
                candidate.parent.mkdir(parents=True)
                candidate.write_text(content, encoding="utf-8")
                _write_yaml(
                    run_dir / "artifact_promotion_plan.yml",
                    {
                        "version": 1,
                        "project": "Novel",
                        "task_id": task_id,
                        "promotions": [
                            {
                                "artifact_id": "chapter_01",
                                "canonical_key": "manuscript.chapter.01",
                                "source_run_artifact": "artifacts/chapter_01.md",
                                "production_path": (
                                    "production/artifacts/chapter_01.md"
                                ),
                                "action": "replace",
                            }
                        ],
                    },
                )
                receipt = apply_archive_protocol(root, "Novel", task_id)
                self.assertEqual(receipt["status"], "completed")
                self.assertIn("canonical_commit_receipt", receipt)

            truth = ProjectTruthStore(project_root)
            current = truth.current()
            resource = current.resources["artifact.manuscript.chapter.01"]
            self.assertEqual(
                resource.content["content"], "revised accepted chapter\n"
            )
            self.assertEqual(
                len(
                    truth.resource_history(
                        "artifact.manuscript.chapter.01"
                    )
                ),
                2,
            )
            self.assertEqual(
                list(
                    key
                    for key in current.resources
                    if key == "artifact.manuscript.chapter.01"
                ),
                ["artifact.manuscript.chapter.01"],
            )

    def test_enforced_truth_blocks_artifact_without_semantic_key(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_root = root / "projects" / "Novel"
            _write_yaml(
                project_root / "project.yml",
                {
                    "project_id": "Novel",
                    "features": {
                        "project_truth_mode": "enforced",
                        "enable_project_agents": True,
                    },
                    "workspace": {"isolation": "required"},
                },
            )
            truth = ProjectTruthStore(project_root)
            initial = truth.initialize("Novel")
            run_dir = self._make_run(root)
            candidate = run_dir / "artifacts" / "chapter_01.md"
            candidate.parent.mkdir(parents=True)
            candidate.write_text("ambiguous chapter\n", encoding="utf-8")
            _write_yaml(
                run_dir / "artifact_promotion_plan.yml",
                {
                    "version": 1,
                    "project": "Novel",
                    "task_id": "task_0001",
                    "promotions": [
                        {
                            "artifact_id": "chapter_01_variant",
                            "source_run_artifact": "artifacts/chapter_01.md",
                            "production_path": (
                                "production/artifacts/chapter_01_variant.md"
                            ),
                            "action": "replace",
                        }
                    ],
                },
            )

            receipt = apply_archive_protocol(root, "Novel", "task_0001")

            self.assertEqual(receipt["status"], "blocked")
            self.assertIn("canonical_key", receipt["errors"][0])
            self.assertEqual(
                truth.current().snapshot_id, initial.current_snapshot_id
            )
            self.assertFalse(
                (
                    project_root
                    / "production"
                    / "artifacts"
                    / "chapter_01_variant.md"
                ).exists()
            )

    def test_fact_authority_promotion_writes_commit_ready_index_binding(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_root = root / "projects" / "Novel"
            _write_yaml(
                root / "config" / "knowledge_system.yml",
                {"indexing": {"project_allowlist": ["Novel"]}},
            )
            run_dir = self._make_run(root)
            workflow = yaml.safe_load(
                (run_dir / "workflow_plan.yml").read_text(encoding="utf-8")
            )
            workflow["artifact_intent"]["production_dir"] = str(
                project_root / "production"
            )
            _write_yaml(run_dir / "workflow_plan.yml", workflow)
            candidate = run_dir / "artifacts" / "fact_authority.yml"
            _write_yaml(
                candidate,
                {
                    "schema_version": "narrative-fact-authority/v1",
                    "project": "Novel",
                    "authority_id": "novel-character-age-standard",
                    "revision": 1,
                    "status": "active",
                    "effective_at": "2026-07-23T00:00:00Z",
                    "supersedes_authority_sha256": None,
                    "facts": [
                        {
                            "fact_id": "char_test.age",
                            "target": "characters",
                            "entity_id": "char_test",
                            "field": "age",
                            "value": 24,
                        }
                    ],
                },
            )
            _write_yaml(
                run_dir / "artifact_promotion_plan.yml",
                {
                    "version": 1,
                    "project": "Novel",
                    "task_id": "task_0001",
                    "promotions": [
                        {
                            "artifact_id": "crown_fact_authority_01",
                            "source_run_artifact": "artifacts/fact_authority.yml",
                            "production_path": "production/fact_authority.yml",
                            "action": "promote",
                        }
                    ],
                },
            )
            source = project_root / "bootstrap.yml"
            _write_yaml(source, {"project": "Novel"})
            store = NarrativeStateStore(
                project_root / "project_brain",
                project="Novel",
            )
            store.bootstrap(
                {
                    "schema_version": "narrative-bootstrap/v1",
                    "project": "Novel",
                    "precedence": ["single_active_fact_authority"],
                    "sources": [
                        {
                            "path": "bootstrap.yml",
                            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        }
                    ],
                    "base_state": {
                        "characters": {"char_test": {"age": 31}},
                    },
                }
            )

            promotion = apply_archive_protocol(root, "Novel", "task_0001")
            receipt = store.commit_fact_authority(
                project_root / "production" / "fact_authority.yml"
            )

            self.assertEqual(promotion["status"], "completed")
            self.assertEqual(receipt["status"], "overridden")
            index = yaml.safe_load(
                (project_root / "project_artifact_index.yml").read_text(
                    encoding="utf-8"
                )
            )
            current = index["artifacts"][-1]
            self.assertEqual(
                current["authority_id"],
                "novel-character-age-standard",
            )
            self.assertEqual(current["authority_revision"], 1)
            self.assertEqual(
                index["current"]["crown_fact_authority_01"],
                "production/fact_authority.yml",
            )
            self.assertEqual(store.read()["characters"]["char_test"]["age"], 24)

    def test_promotion_archives_current_record_for_same_path_when_id_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_root = root / "projects" / "Novel"
            _write_yaml(
                root / "config" / "knowledge_system.yml",
                {"indexing": {"project_allowlist": ["Novel"]}},
            )
            production = project_root / "production" / "fact_authority.yml"
            _write_yaml(
                production,
                {
                    "schema_version": "narrative-fact-authority/v1",
                    "project": "Novel",
                    "authority_id": "novel-character-age-standard",
                    "revision": 1,
                    "status": "active",
                    "effective_at": "2026-07-22T00:00:00Z",
                    "supersedes_authority_sha256": None,
                    "facts": [
                        {
                            "fact_id": "char_test.age",
                            "target": "characters",
                            "entity_id": "char_test",
                            "field": "age",
                            "value": 31,
                        }
                    ],
                },
            )
            old_sha = hashlib.sha256(production.read_bytes()).hexdigest()
            _write_yaml(
                project_root / "project_artifact_index.yml",
                {
                    "schema_version": 1,
                    "project": "Novel",
                    "artifacts": [
                        {
                            "artifact_id": "fact_authority_old_id",
                            "status": "current",
                            "current_version": old_sha[:16],
                            "production_path": "production/fact_authority.yml",
                            "production_sha256": old_sha,
                            "authority_id": "novel-character-age-standard",
                            "authority_revision": 1,
                        }
                    ],
                    "current": {
                        "fact_authority_old_id": "production/fact_authority.yml",
                    },
                },
            )
            run_dir = self._make_run(root, task_id="task_0002")
            workflow = yaml.safe_load(
                (run_dir / "workflow_plan.yml").read_text(encoding="utf-8")
            )
            workflow["artifact_intent"]["production_dir"] = str(
                project_root / "production"
            )
            _write_yaml(run_dir / "workflow_plan.yml", workflow)
            candidate = run_dir / "artifacts" / "fact_authority.yml"
            _write_yaml(
                candidate,
                {
                    "schema_version": "narrative-fact-authority/v1",
                    "project": "Novel",
                    "authority_id": "novel-character-age-standard",
                    "revision": 2,
                    "status": "active",
                    "effective_at": "2026-07-23T00:00:00Z",
                    "supersedes_authority_sha256": old_sha,
                    "facts": [
                        {
                            "fact_id": "char_test.age",
                            "target": "characters",
                            "entity_id": "char_test",
                            "field": "age",
                            "value": 24,
                        }
                    ],
                    "evidence_policy": {
                        "sole_semantic_authority": (
                            "project_brain/narrative_state_events.jsonl"
                        ),
                        "projections": ["production/canonical/characters.yml"],
                        "registries": [],
                    },
                },
            )
            _write_yaml(
                run_dir / "artifact_promotion_plan.yml",
                {
                    "version": 1,
                    "project": "Novel",
                    "task_id": "task_0002",
                    "promotions": [
                        {
                            "artifact_id": "fact_authority_new_id",
                            "source_run_artifact": "artifacts/fact_authority.yml",
                            "production_path": "production/fact_authority.yml",
                            "action": "replace",
                        }
                    ],
                },
            )

            receipt = apply_archive_protocol(root, "Novel", "task_0002")

            self.assertEqual(receipt["status"], "completed")
            index = yaml.safe_load(
                (project_root / "project_artifact_index.yml").read_text(
                    encoding="utf-8"
                )
            )
            current = [
                record
                for record in index["artifacts"]
                if record["status"] == "current"
                and record["production_path"] == "production/fact_authority.yml"
            ]
            self.assertEqual(len(current), 1)
            self.assertEqual(current[0]["artifact_id"], "fact_authority_new_id")
            self.assertEqual(
                index["current"],
                {
                    "fact_authority_new_id": "production/fact_authority.yml",
                },
            )

    def test_production_report_contamination_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._make_run(root)
            report = (
                root
                / "projects"
                / "Novel"
                / "production"
                / "artifacts"
                / "07_validation_report.md"
            )
            report.parent.mkdir(parents=True)
            report.write_text("# Validation Report\n", encoding="utf-8")

            issues = validate_project_artifact_governance(root, "Novel", "task_0001")

            self.assertTrue(any("contains evidence/report file" in issue for issue in issues))

    def test_legacy_project_artifacts_path_is_not_current_authority(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._make_run(root)
            _write_yaml(
                root / "projects" / "Novel" / "project_artifact_index.yml",
                {
                    "artifacts": [
                        {
                            "artifact_id": "legacy",
                            "status": "current",
                            "production_path": "artifacts/legacy.txt",
                            "source_task": "task_0001",
                            "source_run_artifact": "artifacts/legacy.txt",
                        }
                    ]
                },
            )

            issues = validate_project_artifact_governance(
                root,
                "Novel",
                "task_0001",
            )

            self.assertTrue(
                any("must point under production/" in issue for issue in issues)
            )

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
                str(project_root / "production" / "media"),
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

            self.assertEqual(
                intent["production_dir"],
                str(project_root / "production" / "artifacts"),
            )

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
                            "production_path": "production/artifacts/chapter_01.md",
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
                    "added": [
                        {"path": "projects/Novel/production/artifacts/chapter_02.md"}
                    ],
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

    def test_media_promotion_requires_recomputed_independent_visual_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = self._make_run(root)
            candidate = run_dir / "artifacts" / "poster.png"
            candidate.parent.mkdir(parents=True)
            candidate.write_bytes(b"real-candidate-image")
            _write_yaml(
                run_dir / "artifact_promotion_plan.yml",
                {
                    "version": 1,
                    "project": "Novel",
                    "task_id": "task_0001",
                    "promotions": [
                        {
                            "artifact_id": "poster",
                            "source_run_artifact": "artifacts/poster.png",
                            "production_path": "production/artifacts/poster.png",
                        }
                    ],
                },
            )

            blocked = apply_archive_protocol(root, "Novel", "task_0001")

            self.assertEqual(blocked["status"], "blocked")
            self.assertEqual(blocked["visual_acceptance_gate"]["status"], "blocked")
            self.assertTrue(
                any("visual promotion missing visual_acceptance_candidate.yml" in issue for issue in blocked["errors"])
            )
            self.assertFalse(
                (
                    root
                    / "projects"
                    / "Novel"
                    / "production"
                    / "artifacts"
                    / "poster.png"
                ).exists()
            )

            digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
            size_bytes = candidate.stat().st_size
            dimensions = {
                name: {"verdict": "pass", "evidence": [f"checked {name}"]}
                for name in ("aesthetic", "continuity", "technical", "factual_safety")
            }
            _write_yaml(
                run_dir / "visual_acceptance_candidate.yml",
                {
                    "candidate_id": "poster-v1",
                    "candidate_only": True,
                    "status": "complete",
                    "asset": {
                        "path": "artifacts/poster.png",
                        "media_type": "image",
                        "sha256": digest,
                        "size_bytes": size_bytes,
                    },
                    "generation_receipt": {
                        "status": "complete",
                        "producer": {"role": "ArtifactProducer", "id": "grok-producer"},
                        "backend": "hermes_grok_oauth",
                        "model": "grok-imagine-image",
                        "prompt_parameters": {"prompt_sha256": hashlib.sha256(b"prompt").hexdigest()},
                        "reference_assets": [],
                    },
                    "observer_evidence": {
                        "status": "complete",
                        "observer": {
                            "role": "Observer",
                            "id": "agy-observer",
                            "backend": "agy_oauth",
                            "model": "gemini-3.5-flash",
                        },
                        "asset": {
                            "path": "artifacts/poster.png",
                            "sha256": digest,
                            "size_bytes": size_bytes,
                        },
                        "keyframes": [{"label": "full_frame", "sha256": digest}],
                    },
                    "reviews": [
                        {
                            "reviewer": {
                                "role": "Reviewer",
                                "id": "claude-reviewer",
                                "backend": "claude_shell",
                                "model": "deepseek-v4-pro",
                            },
                            "status": "complete",
                            "asset": {
                                "path": "artifacts/poster.png",
                                "sha256": digest,
                                "size_bytes": size_bytes,
                            },
                            "dimensions": dimensions,
                        },
                        {
                            "reviewer": {
                                "role": "Verifier",
                                "id": "codex-verifier",
                                "backend": "hermes_codex_oauth",
                                "model": "gpt-5.6-sol",
                            },
                            "status": "complete",
                            "asset": {
                                "path": "artifacts/poster.png",
                                "sha256": digest,
                                "size_bytes": size_bytes,
                            },
                            "checks": {
                                name: {"verdict": "pass", "evidence": [f"checked {name}"]}
                                for name in ("asset_integrity", "evidence_chain", "reviewer_independence", "promotion_boundary")
                            },
                        },
                    ],
                },
            )

            accepted = apply_archive_protocol(root, "Novel", "task_0001")

            self.assertEqual(accepted["status"], "completed")
            self.assertEqual(accepted["visual_acceptance_gate"]["status"], "pass")
            self.assertEqual(accepted["visual_acceptance_gate"]["verified_sources"], ["artifacts/poster.png"])
            self.assertEqual(
                (
                    root
                    / "projects"
                    / "Novel"
                    / "production"
                    / "artifacts"
                    / "poster.png"
                ).read_bytes(),
                b"real-candidate-image",
            )

    def test_media_promotion_rechecks_file_hash_after_acceptance_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = self._make_run(root)
            candidate = run_dir / "artifacts" / "poster.png"
            candidate.parent.mkdir(parents=True)
            candidate.write_bytes(b"original")
            digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
            size_bytes = candidate.stat().st_size
            _write_yaml(
                run_dir / "artifact_promotion_plan.yml",
                {
                    "promotions": [
                        {
                            "source_run_artifact": "artifacts/poster.png",
                            "production_path": "production/artifacts/poster.png",
                        }
                    ]
                },
            )
            _write_yaml(
                run_dir / "visual_acceptance_candidate.yml",
                {
                    "candidate_id": "poster-v1",
                    "candidate_only": True,
                    "status": "complete",
                    "asset": {
                        "path": "artifacts/poster.png",
                        "media_type": "image",
                        "sha256": digest,
                        "size_bytes": size_bytes,
                    },
                    "generation_receipt": {
                        "status": "complete",
                        "producer": {"role": "ArtifactProducer", "id": "grok-producer"},
                        "backend": "grok",
                        "model": "grok-image",
                        "prompt_parameters": {"prompt_sha256": "abc"},
                        "reference_assets": [],
                    },
                    "observer_evidence": {
                        "status": "complete",
                        "observer": {"role": "Observer", "id": "observer", "backend": "agy", "model": "gemini"},
                        "asset": {"path": "artifacts/poster.png", "sha256": digest, "size_bytes": size_bytes},
                        "keyframes": [{"label": "full", "sha256": digest}],
                    },
                    "reviews": [
                        {
                            "reviewer": {"role": "Reviewer", "id": "reviewer", "backend": "claude", "model": "deepseek"},
                            "status": "complete",
                            "asset": {"path": "artifacts/poster.png", "sha256": digest, "size_bytes": size_bytes},
                            "dimensions": {name: {"verdict": "pass", "evidence": ["ok"]} for name in ("aesthetic", "continuity", "technical", "factual_safety")},
                        },
                        {
                            "reviewer": {"role": "Verifier", "id": "verifier", "backend": "hermes", "model": "gpt-5.6-sol"},
                            "status": "complete",
                            "asset": {"path": "artifacts/poster.png", "sha256": digest, "size_bytes": size_bytes},
                            "checks": {name: {"verdict": "pass", "evidence": ["ok"]} for name in ("asset_integrity", "evidence_chain", "reviewer_independence", "promotion_boundary")},
                        },
                    ],
                },
            )
            candidate.write_bytes(b"tampered-after-review")

            receipt = apply_archive_protocol(root, "Novel", "task_0001")

            self.assertEqual(receipt["status"], "blocked")
            self.assertTrue(any("asset.sha256_mismatch" in issue for issue in receipt["errors"]))
            self.assertFalse(
                (
                    root
                    / "projects"
                    / "Novel"
                    / "production"
                    / "artifacts"
                    / "poster.png"
                ).exists()
            )


if __name__ == "__main__":
    main()
