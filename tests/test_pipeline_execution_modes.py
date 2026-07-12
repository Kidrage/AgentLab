"""P0-1: Verify that _resolve_execution_mode prevents real LLM calls in dry_run / mock_provider modes."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main
import unittest.mock as mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from lifecycle_graph import (  # noqa: E402
    create_lifecycle, load_lifecycle, save_lifecycle,
    LIFECYCLE_NODES,
)
from pipeline_runner import (  # noqa: E402
    _resolve_execution_mode,
    _write_synthesis_domain_research_brief,
    run_full_pipeline,
    run_next_node,
)
from pipeline_runner import _pack_candidate_payload  # noqa: E402
from production_pack_output_materializer import (  # noqa: E402
    REQUIRED_SYNTHESIS_OUTPUTS,
    materialize_production_pack_candidate_result,
)
from schemas import LLMCallResult  # noqa: E402


class ExecutionModeResolutionTests(TestCase):
    def test_dry_run_forces_fake_provider(self) -> None:
        mode = _resolve_execution_mode(dry_run=True, fake_provider=False)
        self.assertEqual(mode["execution_mode"], "dry_run")
        self.assertTrue(mode["effective_fake_provider"])
        self.assertFalse(mode["allow_real_provider"])
        self.assertFalse(mode["allow_patches"])

    def test_mock_provider_no_real_provider(self) -> None:
        mode = _resolve_execution_mode(dry_run=False, fake_provider=True)
        self.assertEqual(mode["execution_mode"], "mock_provider")
        self.assertTrue(mode["effective_fake_provider"])
        self.assertFalse(mode["allow_real_provider"])
        self.assertFalse(mode["allow_patches"])

    def test_execute_allows_real_provider_and_patches(self) -> None:
        mode = _resolve_execution_mode(dry_run=False, fake_provider=False)
        self.assertEqual(mode["execution_mode"], "execute")
        self.assertFalse(mode["effective_fake_provider"])
        self.assertTrue(mode["allow_real_provider"])
        self.assertTrue(mode["allow_patches"])


class DryRunNoRealCallTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.run_dir = self.root / "projects" / "Demo" / "runs" / "task_mode_001"
        self.run_dir.mkdir(parents=True)
        (self.run_dir / "workflow_plan.yml").write_text(
            "route:\n  agents:\n    - Supervisor\n    - Coder\n",
            encoding="utf-8",
        )
        (self.run_dir / "user_request.md").write_text("# Test\n\nDry-run test.\n", encoding="utf-8")
        create_lifecycle(self.run_dir, {"route": {"agents": ["Supervisor", "Coder"]}})
        # Mark INIT and PREPARE as completed so pipeline advances to SUPERVISOR_PLAN
        lc = load_lifecycle(self.run_dir)
        if lc:
            lc["nodes"]["INIT_TASK"]["status"] = "completed"
            lc["nodes"]["PREPARE_PLAN"]["status"] = "completed"
            save_lifecycle(self.run_dir, lc)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_dry_run_fake_provider_false_does_not_call_real_model(self) -> None:
        """When dry_run=True, even with fake_provider=False, no real LLM call should happen."""
        import unittest.mock as mock
        with mock.patch("agent_runner.run_agent_model") as patched_run:
            result = run_full_pipeline(
                self.root, "Demo", "task_mode_001",
                dry_run=True, fake_provider=False,
                max_steps=3,
            )
            patched_run.assert_not_called()
            self.assertEqual(result.get("execution_mode"), "dry_run")

    def test_mock_provider_does_not_call_real_llm(self) -> None:
        """dry_run=False, fake_provider=True should still NOT call real LLM."""
        import unittest.mock as mock
        with mock.patch("agent_runner.run_agent_model") as patched_run:
            result = run_full_pipeline(
                self.root, "Demo", "task_mode_001",
                dry_run=False, fake_provider=True,
                max_steps=3,
            )
            patched_run.assert_not_called()
            self.assertEqual(result.get("execution_mode"), "mock_provider")


class DryRunClosureEvidenceTests(TestCase):
    def test_prepare_plan_reopens_audit_and_archive_nodes_from_existing_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = root / "projects" / "Demo" / "runs" / "task_late_plan_001"
            run_dir.mkdir(parents=True)
            (run_dir / "user_request.md").write_text(
                "# User Request\n\nImplement code, validate, audit, and archive dry-run evidence.\n",
                encoding="utf-8",
            )
            (run_dir / "workflow_plan.yml").write_text(
                "route:\n"
                "  agents:\n"
                "    - Supervisor\n"
                "    - RepoScout\n"
                "    - Coder\n"
                "    - TesterAuditor\n"
                "    - Archivist\n",
                encoding="utf-8",
            )
            create_lifecycle(run_dir, {})

            result = run_full_pipeline(
                root,
                "Demo",
                "task_late_plan_001",
                dry_run=True,
                fake_provider=False,
                max_steps=30,
            )

            self.assertTrue(result["success"])
            lifecycle = load_lifecycle(run_dir) or {}
            nodes = lifecycle.get("nodes", {})
            self.assertEqual(nodes["VALIDATION"]["status"], "completed")
            self.assertEqual(nodes["AUDIT"]["status"], "completed")
            self.assertEqual(nodes["ARCHIVE"]["status"], "completed")
            self.assertTrue((run_dir / "artifact_lineage.yml").exists())
            self.assertTrue((run_dir / "archive_receipt.yml").exists())

    def test_full_dry_run_pipeline_writes_closure_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = root / "projects" / "Demo" / "runs" / "task_closure_001"
            run_dir.mkdir(parents=True)
            (run_dir / "user_request.md").write_text(
                "# User Request\n\nSmoke test dry-run closure evidence.\n",
                encoding="utf-8",
            )
            (run_dir / "workflow_plan.yml").write_text(
                "route:\n"
                "  agents:\n"
                "    - Supervisor\n"
                "    - RepoScout\n"
                "    - Coder\n"
                "    - TesterAuditor\n"
                "    - Archivist\n",
                encoding="utf-8",
            )
            create_lifecycle(
                run_dir,
                {
                    "route": {
                        "agents": [
                            "Supervisor",
                            "RepoScout",
                            "Coder",
                            "TesterAuditor",
                            "Archivist",
                        ]
                    }
                },
            )

            result = run_full_pipeline(
                root,
                "Demo",
                "task_closure_001",
                dry_run=True,
                fake_provider=False,
                max_steps=30,
            )

            self.assertTrue(result["success"])
            self.assertEqual(result["final_status"], "completed")
            self.assertEqual(result["execution_mode"], "dry_run")
            self.assertTrue((run_dir / "implementation_report.md").exists())
            self.assertTrue((run_dir / "validation_report.md").exists())
            self.assertTrue((run_dir / "archive_update.md").exists())
            self.assertTrue((run_dir / "artifact_lineage.yml").exists())
            self.assertTrue((run_dir / "artifact_promotion_plan.yml").exists())
            self.assertTrue((run_dir / "archive_receipt.yml").exists())
            self.assertTrue((root / "projects" / "Demo" / "project_artifact_index.yml").exists())
            self.assertTrue((run_dir / "execution_log.yml").exists())
            self.assertTrue((run_dir / "cost_ledger.yml").exists())
            self.assertTrue((run_dir / "artifact_manifest.yml").exists())

            ledger = yaml.safe_load((run_dir / "cost_ledger.yml").read_text(encoding="utf-8")) or {}
            entries = ledger.get("entries", [])
            self.assertTrue(any(e.get("dry_run") is True for e in entries))
            self.assertTrue(any(e.get("provider") == "fake_provider" for e in entries))

            validation = (run_dir / "07_validation_report.md").read_text(encoding="utf-8")
            self.assertIn("command_id", validation)


class WriterExecuteMaterializationTests(TestCase):
    def test_execute_writer_materializes_candidate_blocks_instead_of_cli_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            task_id = "task_writer_execute"
            run_dir = root / "projects" / "Demo" / "runs" / task_id
            run_dir.mkdir(parents=True)
            (run_dir / "user_request.md").write_text("Write chapter 1.", encoding="utf-8")
            (run_dir / "workflow_plan.yml").write_text(
                "route:\n  agents:\n    - Writer\n",
                encoding="utf-8",
            )
            create_lifecycle(run_dir, {"route": {"agents": ["Writer"]}})
            lifecycle = load_lifecycle(run_dir) or {}
            for node_id in LIFECYCLE_NODES:
                if node_id == "WRITER_DRAFT":
                    lifecycle["nodes"][node_id]["status"] = "waiting"
                    break
                lifecycle["nodes"][node_id]["status"] = "completed"
            save_lifecycle(run_dir, lifecycle)

            draft = "# Chapter 1\n\n" + "\n\n".join(
                f"Paragraph {index} carries the story forward with concrete action."
                for index in range(40)
            )
            outputs = {
                "fiction_draft.md": draft,
                "continuity_ledger.yml": (
                    "schema_version: 1\nchapter: 1\nbaseline_mode: reset\n"
                    "timeline:\n  monotonic: true\nwriter_marker: retained\n"
                ),
                "state_transition_proposal.yml": (
                    "schema_version: 1\nstatus: candidate\nrequires_user_promotion: true\n"
                    "events:\n  - event_type: plot\n    scope: candidate_only\n"
                ),
                "narrative_delivery_receipt.yml": (
                    "schema_version: 1\nstatus: pass\ncandidate_only: true\n"
                ),
            }
            model_content = "\n".join(
                f"<!-- AGENTLAB_EDIT: runs/{task_id}/{name} -->\n{value.rstrip()}\n"
                "<!-- END AGENTLAB_EDIT -->\n"
                for name, value in outputs.items()
            )
            model_result = LLMCallResult(
                provider="agentlab-cli-executor",
                model="agy",
                content=model_content,
                status="completed",
                raw_usage={"usage_source": "external_cli_estimate"},
            )

            with mock.patch("workflow_plan.build_workflow_plan", return_value=object()), mock.patch(
                "agent_runner.run_agent_model",
                return_value=model_result,
            ):
                result = run_next_node(
                    root,
                    "Demo",
                    task_id,
                    fake_provider=False,
                    execution_mode="execute",
                )

            self.assertEqual(result["status"], "completed", result)
            self.assertEqual(result["node"], "WRITER_DRAFT")
            self.assertEqual((run_dir / "fiction_draft.md").read_text(encoding="utf-8").strip(), draft)
            ledger = yaml.safe_load((run_dir / "continuity_ledger.yml").read_text(encoding="utf-8"))
            self.assertEqual(ledger["writer_marker"], "retained")
            capture = (run_dir / "writer_role_session_capture.md").read_text(encoding="utf-8")
            self.assertIn("AGENTLAB_EDIT", capture)
            self.assertNotIn("AGENTLAB_EDIT", (run_dir / "fiction_draft.md").read_text(encoding="utf-8"))


class ProductionPackExecuteMaterializationTests(TestCase):
    def _pack(self) -> dict:
        return {
            "status": "synthesis_candidate",
            "pack_id": "pack_synthesis_candidate",
            "route_key": "artifact_production_task",
            "project_type": "experiential_installation",
            "task_domain": "scent_theater",
            "artifact_type": "show_package",
            "required_outputs": list(REQUIRED_SYNTHESIS_OUTPUTS),
        }

    def _model_result(self, task_id: str) -> LLMCallResult:
        blocks = []
        for name in REQUIRED_SYNTHESIS_OUTPUTS:
            payload = _pack_candidate_payload(
                "pack_synthesis_candidate",
                name,
                "Demo",
                task_id,
                execution_mode="execute",
                pack=self._pack(),
            )
            payload["generated_by"] = "ArtifactProducer role session"
            value = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
            blocks.append(
                f"<!-- AGENTLAB_EDIT: runs/{task_id}/{name} -->\n"
                f"```yaml\n{value.rstrip()}\n```\n"
                "<!-- END AGENTLAB_EDIT -->"
            )
        return LLMCallResult(
            provider="agentlab-cli-executor",
            model="agy",
            content="\n\n".join(blocks),
            status="completed",
            raw_usage={"cli_agent": "agy", "usage_source": "external_cli_estimate"},
        )

    def _run_dir_at_node(self, root: Path, task_id: str, node_id: str) -> Path:
        run_dir = root / "projects" / "Demo" / "runs" / task_id
        run_dir.mkdir(parents=True)
        pack = self._pack()
        (run_dir / "user_request.md").write_text(
            "Design a governed scent-theater production pack.", encoding="utf-8"
        )
        (run_dir / "workflow_plan.yml").write_text(
            yaml.safe_dump(
                {
                    "route": {
                        "agents": [
                            "Supervisor",
                            "Researcher",
                            "ArtifactProducer",
                            "Verifier",
                        ]
                    },
                    "production_pack": pack,
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        create_lifecycle(run_dir, {"route": {"agents": ["ArtifactProducer", "Verifier"]}})
        lifecycle = load_lifecycle(run_dir) or {}
        for current in LIFECYCLE_NODES:
            if current == node_id:
                lifecycle["nodes"][current]["status"] = "waiting"
                break
            lifecycle["nodes"][current]["status"] = "completed"
        save_lifecycle(run_dir, lifecycle)
        return run_dir

    def test_execute_artifact_producer_materializes_returned_pack_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            task_id = "task_pack_execute"
            run_dir = self._run_dir_at_node(root, task_id, "ARTIFACT_PRODUCTION")
            (root / "config").mkdir()
            (root / "config" / "production_packs.yml").write_text(
                "packs: []\n", encoding="utf-8"
            )
            (run_dir / "production_pack_research_contract.yml").write_text(
                "status: pass\nexecution_mode: execute\nprovider_returned_research: true\n",
                encoding="utf-8",
            )
            plan = SimpleNamespace(production_pack=self._pack())
            model_result = self._model_result(task_id)

            with mock.patch(
                "workflow_plan.build_workflow_plan", return_value=plan
            ), mock.patch("agent_runner.run_agent_model", return_value=model_result) as run_model:
                result = run_next_node(
                    root,
                    "Demo",
                    task_id,
                    fake_provider=False,
                    execution_mode="execute",
                    allow_patches=True,
                )

            self.assertEqual(result["status"], "completed", result)
            self.assertEqual(result["node"], "ARTIFACT_PRODUCTION")
            self.assertFalse(run_model.call_args.kwargs["apply_patches"])
            contract = yaml.safe_load(
                (run_dir / "production_pack_output_contract.yml").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(contract["status"], "pass")
            self.assertTrue(contract["provider_returned_outputs"])
            self.assertNotIn(
                "AGENTLAB_EDIT",
                (run_dir / "artifact_producer_report.md").read_text(encoding="utf-8"),
            )

    def test_cli_native_research_report_is_not_overwritten_by_result_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            task_id = "task_pack_research"
            run_dir = self._run_dir_at_node(root, task_id, "RESEARCH_OPTIONAL")
            report_path = run_dir / "03_research_notes.md"
            report_path.write_text("# placeholder\n", encoding="utf-8")
            plan = SimpleNamespace(production_pack=self._pack())
            wrapper = LLMCallResult(
                provider="agentlab-cli-executor",
                model="claude_code",
                content="# CLI wrapper\n\nThe worker reported success.\n",
                status="completed",
                raw_usage={"cli_agent": "claude_code"},
            )

            def run_model(*args, **kwargs):
                output_path = args[3]
                output_path.write_text(
                    "# Domain Research\n\nNative CLI findings must survive.\n",
                    encoding="utf-8",
                )
                return wrapper

            with mock.patch(
                "workflow_plan.build_workflow_plan", return_value=plan
            ), mock.patch("agent_runner.run_agent_model", side_effect=run_model):
                result = run_next_node(
                    root,
                    "Demo",
                    task_id,
                    fake_provider=False,
                    execution_mode="execute",
                )

            self.assertEqual(result["status"], "completed", result)
            self.assertIn(
                "Native CLI findings must survive",
                report_path.read_text(encoding="utf-8"),
            )
            self.assertIn(
                "CLI wrapper",
                (run_dir / "researcher_cli_result_capture.md").read_text(
                    encoding="utf-8"
                ),
            )
            research_contract = yaml.safe_load(
                (run_dir / "production_pack_research_contract.yml").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(research_contract["status"], "pass")

    def test_research_brief_refreshes_when_native_source_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            task_id = "task_pack_research_refresh"
            run_dir = self._run_dir_at_node(root, task_id, "RESEARCH_OPTIONAL")
            report_path = run_dir / "03_research_notes.md"
            report_path.write_text("# First native report\n", encoding="utf-8")

            first = _write_synthesis_domain_research_brief(
                run_dir,
                source_report=report_path,
                execution_mode="execute",
                source_provider="agentlab-cli-executor",
                source_model="claude_code",
                source_status="completed",
            )
            first_contract = yaml.safe_load(
                (run_dir / "production_pack_research_contract.yml").read_text(
                    encoding="utf-8"
                )
            )

            report_path.write_text("# Recovered native report\n", encoding="utf-8")
            second = _write_synthesis_domain_research_brief(
                run_dir,
                source_report=report_path,
                execution_mode="execute",
                source_provider="agentlab-cli-executor",
                source_model="claude_code",
                source_status="completed",
            )
            second_contract = yaml.safe_load(
                (run_dir / "production_pack_research_contract.yml").read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(first, "domain_research_brief.md")
            self.assertEqual(second, "domain_research_brief.md")
            self.assertNotEqual(
                first_contract["source_sha256"], second_contract["source_sha256"]
            )
            brief = (run_dir / "domain_research_brief.md").read_text(encoding="utf-8")
            self.assertIn("Recovered native report", brief)
            self.assertNotIn("First native report", brief)

    def test_execute_verifier_writes_bound_verification_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            task_id = "task_pack_verify"
            run_dir = self._run_dir_at_node(root, task_id, "VERIFY")
            (root / "config").mkdir()
            catalog = root / "config" / "production_packs.yml"
            catalog.write_text("packs: []\n", encoding="utf-8")
            (run_dir / "production_pack_research_contract.yml").write_text(
                "status: pass\nexecution_mode: execute\nprovider_returned_research: true\n",
                encoding="utf-8",
            )
            assert materialize_production_pack_candidate_result(
                self._model_result(task_id),
                run_dir,
                task_id,
                catalog,
                execution_mode="execute",
            )
            plan = SimpleNamespace(production_pack=self._pack())
            verifier = LLMCallResult(
                provider="agentlab-cli-executor",
                model="hermes",
                content="# Verification\n\nDecision: pass.\n",
                status="completed",
                raw_usage={"cli_agent": "hermes"},
            )

            with mock.patch(
                "workflow_plan.build_workflow_plan", return_value=plan
            ), mock.patch("agent_runner.run_agent_model", return_value=verifier):
                result = run_next_node(
                    root,
                    "Demo",
                    task_id,
                    fake_provider=False,
                    execution_mode="execute",
                )

            self.assertEqual(result["status"], "completed", result)
            receipt = yaml.safe_load(
                (run_dir / "production_pack_verification_receipt.yml").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(receipt["status"], "pass")
            self.assertTrue(receipt["verifier_role_session_returned"])


if __name__ == "__main__":
    main()
