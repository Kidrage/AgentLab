from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from artifact_contract import artifact_content_issues, validate_artifacts
from atomic_io import atomic_write_yaml
from lifecycle_graph import create_lifecycle, load_lifecycle, mark_node_started, save_lifecycle
from llm_provider import build_fallback_provider_chain, generate_text
from memory_writer import apply_archivist_memory_edits
from pipeline_runner import _block_on_artifact_gate, run_next_node
from schemas import LLMSettings


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

    def test_direct_api_candidate_without_commands_is_valid_execution_evidence(self) -> None:
        issues = artifact_content_issues(
            "06_implementation_report.md",
            "\n".join(
                [
                    "# Coder Report",
                    "",
                    "Coder execution mode: direct_api_text_generation.",
                    "Commands run: none by this model call.",
                    "Candidate implementation: proposed files under runs/task_x/artifacts/.",
                    "",
                    "## Proposed Validation Commands",
                    "Run `python3 -m pytest -q tests/test_agent_runner_cli_integration.py`.",
                    "",
                    "<<<AGENTLAB_EDIT runs/task_x/artifacts/example.txt",
                    "=======",
                    "candidate",
                    "+++++++ REPLACE",
                    ">>>",
                ]
            ),
        )
        self.assertNotIn("execution placeholder or no command evidence", issues)

    def test_unclosed_html_edit_block_is_invalid(self) -> None:
        issues = artifact_content_issues(
            "06_implementation_report.md",
            "\n".join(
                [
                    "# Coder Report",
                    "",
                    "Coder execution mode: direct_api_text_generation.",
                    "Commands run: none by this model call.",
                    "Candidate implementation: proposed files under runs/task_x/artifacts/.",
                    "",
                    "<!-- AGENTLAB_EDIT: runs/task_x/artifacts/index.html -->",
                    "<html>partial",
                ]
            ),
        )
        self.assertIn("unclosed structured edit block", issues)

    def test_unclosed_primary_edit_block_is_invalid(self) -> None:
        issues = artifact_content_issues(
            "06_implementation_report.md",
            "\n".join(
                [
                    "# Coder Report",
                    "",
                    "Coder execution mode: direct_api_text_generation.",
                    "Commands run: none by this model call.",
                    "Candidate implementation: proposed files under runs/task_x/artifacts/.",
                    "",
                    "<<<AGENTLAB_EDIT runs/task_x/artifacts/example.txt",
                    "=======",
                    "partial",
                ]
            ),
        )
        self.assertIn("unclosed structured edit block", issues)

    def test_production_pack_empty_yaml_payload_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "workflow_plan.yml").write_text(
                "\n".join([
                    "production_pack:",
                    "  pack_id: media_series_production",
                    "  required_outputs:",
                    "    - episode_plan.yml",
                    "",
                ]),
                encoding="utf-8",
            )
            issues = artifact_content_issues(
                "episode_plan.yml",
                yaml.safe_dump(
                    {
                        "schema_version": 1,
                        "project": "Crown_of_Ash",
                        "task_id": "task_media",
                        "production_pack": "media_series_production",
                        "artifact": "episode_plan.yml",
                        "status": "candidate",
                        "execution_mode": "dry_run",
                        "generated_by": "fake_provider",
                        "items": [],
                    },
                    sort_keys=False,
                ),
                run_dir,
            )

        self.assertIn("production-pack candidate artifact has no meaningful payload beyond metadata", issues)

    def test_artifact_gate_blocks_lifecycle_node(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            create_lifecycle(run_dir, {"route": {"agents": ["Supervisor", "RepoScout"]}})
            mark_node_started(run_dir, "REPO_CONTEXT")

            result = _block_on_artifact_gate(
                run_dir,
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

    def test_fake_artifact_producer_writes_production_pack_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = root / "projects" / "Demo" / "runs" / "task_media"
            run_dir.mkdir(parents=True)
            (run_dir / "workflow_plan.yml").write_text(
                "\n".join([
                    "route:",
                    "  agents:",
                    "    - Supervisor",
                    "    - ArtifactProducer",
                    "production_pack:",
                    "  pack_id: media_series_production",
                    "  lifecycle_nodes:",
                    "    - INIT_TASK",
                    "    - CONTEXT_PROFILE",
                    "    - CONTEXT_BUDGET",
                    "    - CONTEXT_PACK",
                    "    - PREPARE_PLAN",
                    "    - SUPERVISOR_PLAN",
                    "    - ARTIFACT_PRODUCTION",
                    "    - SELF_CHECK",
                    "    - FINALIZE",
                    "  required_outputs:",
                    "    - episode_plan.yml",
                    "    - shot_list.yml",
                    "    - prompt_pack.yml",
                    "",
                ]),
                encoding="utf-8",
            )
            lifecycle = create_lifecycle(
                run_dir,
                yaml.safe_load((run_dir / "workflow_plan.yml").read_text(encoding="utf-8")),
            )
            for node_id, node in lifecycle["nodes"].items():
                if node_id == "ARTIFACT_PRODUCTION":
                    node["status"] = "waiting"
                elif node.get("status") != "skipped":
                    node["status"] = "completed"
            save_lifecycle(run_dir, lifecycle)

            result = run_next_node(root, "Demo", "task_media", fake_provider=True)

            self.assertEqual(result["status"], "completed")
            self.assertTrue((run_dir / "artifact_producer_report.md").exists())
            self.assertTrue((run_dir / "episode_plan.yml").exists())
            self.assertTrue((run_dir / "shot_list.yml").exists())
            self.assertTrue((run_dir / "prompt_pack.yml").exists())
            self.assertEqual(
                yaml.safe_load((run_dir / "episode_plan.yml").read_text(encoding="utf-8"))["status"],
                "candidate",
            )
            episode_plan = yaml.safe_load((run_dir / "episode_plan.yml").read_text(encoding="utf-8"))
            shot_list = yaml.safe_load((run_dir / "shot_list.yml").read_text(encoding="utf-8"))
            prompt_pack = yaml.safe_load((run_dir / "prompt_pack.yml").read_text(encoding="utf-8"))
            self.assertTrue(episode_plan["episodes"])
            self.assertEqual(episode_plan["episodes"][0]["episode_id"], "ep01")
            self.assertTrue(shot_list["shots"])
            self.assertEqual(shot_list["shots"][0]["prompt_ref"], "prompt_ep01_sh001")
            self.assertTrue(prompt_pack["prompts"])
            self.assertEqual(prompt_pack["prompts"][0]["prompt_id"], "prompt_ep01_sh001")
            self.assertNotIn(
                "production-pack candidate artifact has no meaningful payload beyond metadata",
                artifact_content_issues(
                    "episode_plan.yml",
                    (run_dir / "episode_plan.yml").read_text(encoding="utf-8"),
                    run_dir,
                ),
            )

    def test_fake_media_artifact_producer_writes_backend_dry_run_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config_dir = root / "config"
            config_dir.mkdir(parents=True)
            (config_dir / "media_generation_backends.yml").write_text(
                (ROOT / "config" / "media_generation_backends.yml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            run_dir = root / "projects" / "Crown_of_Ash" / "runs" / "task_media_backend"
            run_dir.mkdir(parents=True)
            (run_dir / "workflow_plan.yml").write_text(
                "\n".join([
                    "route:",
                    "  route_key: media_generation_task",
                    "  agents:",
                    "    - Supervisor",
                    "    - ArtifactProducer",
                    "production_pack:",
                    "  pack_id: media_generation",
                    "  lifecycle_nodes:",
                    "    - INIT_TASK",
                    "    - PREPARE_PLAN",
                    "    - SUPERVISOR_PLAN",
                    "    - ARTIFACT_PRODUCTION",
                    "    - SELF_CHECK",
                    "    - FINALIZE",
                    "  required_outputs:",
                    "    - generation_ledger.yml",
                    "    - media_qc_report.yml",
                    "    - media_delivery_receipt.yml",
                    "",
                ]),
                encoding="utf-8",
            )
            atomic_write_yaml(run_dir / "media_generation_contract.yml", {
                "schema_version": 1,
                "contract_type": "media_generation_contract",
                "project_id": "Crown_of_Ash",
                "task_id": "task_media_backend",
                "modality": "image",
                "prompt": "Generate image: Crown of Ash poster.",
                "selected_backend": "grok_direct",
                "delivery_constraints": {"aspect_ratio": "16:9"},
            })
            lifecycle = create_lifecycle(
                run_dir,
                yaml.safe_load((run_dir / "workflow_plan.yml").read_text(encoding="utf-8")),
            )
            for node_id, node in lifecycle["nodes"].items():
                if node_id == "ARTIFACT_PRODUCTION":
                    node["status"] = "waiting"
                elif node.get("status") != "skipped":
                    node["status"] = "completed"
            save_lifecycle(run_dir, lifecycle)

            result = run_next_node(root, "Crown_of_Ash", "task_media_backend", fake_provider=True)

            self.assertEqual(result["status"], "completed")
            self.assertIn("artifacts/media_backend/media_backend_preflight.yml", result["media_backend_outputs"])
            self.assertTrue((run_dir / "artifacts" / "media_backend" / "media_backend_preflight.yml").exists())
            self.assertTrue((run_dir / "artifacts" / "media_backend" / "media_backend_payload_plan.yml").exists())
            ledger = yaml.safe_load(
                (run_dir / "artifacts" / "media_backend" / "generation_ledger.yml").read_text(encoding="utf-8")
            )
            self.assertEqual(ledger["status"], "dry_run")
            self.assertFalse(ledger["live"])

    def test_fake_writer_writes_narrative_batch_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = root / "projects" / "Crown_of_Ash" / "runs" / "task_batch"
            run_dir.mkdir(parents=True)
            (run_dir / "workflow_plan.yml").write_text(
                "\n".join([
                    "route:",
                    "  route_key: narrative_batch_chapters",
                    "  agents:",
                    "    - Supervisor",
                    "    - Writer",
                    "production_pack:",
                    "  pack_id: narrative_longform",
                    "  lifecycle_nodes:",
                    "    - INIT_TASK",
                    "    - CONTEXT_PROFILE",
                    "    - CONTEXT_BUDGET",
                    "    - CONTEXT_PACK",
                    "    - PREPARE_PLAN",
                    "    - SUPERVISOR_PLAN",
                    "    - WRITER_DRAFT",
                    "    - SELF_CHECK",
                    "    - FINALIZE",
                    "",
                ]),
                encoding="utf-8",
            )
            lifecycle = create_lifecycle(
                run_dir,
                yaml.safe_load((run_dir / "workflow_plan.yml").read_text(encoding="utf-8")),
            )
            for node_id, node in lifecycle["nodes"].items():
                if node_id == "WRITER_DRAFT":
                    node["status"] = "waiting"
                elif node.get("status") != "skipped":
                    node["status"] = "completed"
            save_lifecycle(run_dir, lifecycle)

            result = run_next_node(root, "Crown_of_Ash", "task_batch", fake_provider=True)

            self.assertEqual(result["status"], "completed")
            self.assertTrue((run_dir / "fiction_draft.md").exists())
            self.assertTrue((run_dir / "chapter_batch_plan.yml").exists())
            self.assertTrue((run_dir / "chapters" / "chapter_001.md").exists())
            self.assertTrue((run_dir / "batch_continuity_ledger.yml").exists())
            self.assertTrue((run_dir / "state_transition_proposal.yml").exists())
            self.assertTrue((run_dir / "narrative_batch_delivery_receipt.yml").exists())


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

    def test_archivist_without_edit_block_appends_fallback_memory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_root = root / "projects" / "Demo"
            agent_docs = project_root / "agent_docs"
            config = root / "config"
            agent_docs.mkdir(parents=True)
            config.mkdir()
            (config / "memory_policy.yml").write_text(
                "records:\n  project_memory:\n    - 07_DEVELOPMENT_LOG.md\n",
                encoding="utf-8",
            )
            target = agent_docs / "07_DEVELOPMENT_LOG.md"
            target.write_text("# Development Log\n", encoding="utf-8")

            result = apply_archivist_memory_edits(root, project_root, "# Archive Update\n\nNo structured edits.")

            self.assertTrue(result.ok)
            self.assertTrue(result.fallback_applied)
            text = target.read_text(encoding="utf-8")
            self.assertIn("Archivist fallback memory write", text)
            self.assertIn("No structured edits", text)

    def test_archivist_fallback_mirrors_to_remote_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "local"
            remote = Path(td) / "remote"
            project_root = root / "projects" / "Demo"
            agent_docs = project_root / "agent_docs"
            config = root / "config"
            agent_docs.mkdir(parents=True)
            config.mkdir(parents=True)
            remote.mkdir()
            (config / "memory_policy.yml").write_text(
                "records:\n  project_memory:\n    - 07_DEVELOPMENT_LOG.md\n",
                encoding="utf-8",
            )
            (agent_docs / "07_DEVELOPMENT_LOG.md").write_text("# Development Log\n", encoding="utf-8")

            import os
            previous = os.environ.get("AGENTLAB_REMOTE_REPO_ROOT")
            os.environ["AGENTLAB_REMOTE_REPO_ROOT"] = str(remote)
            try:
                result = apply_archivist_memory_edits(root, project_root, "# Archive Update\n\nMirror me.")
            finally:
                if previous is None:
                    os.environ.pop("AGENTLAB_REMOTE_REPO_ROOT", None)
                else:
                    os.environ["AGENTLAB_REMOTE_REPO_ROOT"] = previous

            mirrored = remote / "projects" / "Demo" / "agent_docs" / "07_DEVELOPMENT_LOG.md"
            self.assertTrue(result.ok)
            self.assertIsNotNone(result.mirror_path)
            self.assertTrue(mirrored.exists())
            self.assertIn("Mirror me", mirrored.read_text(encoding="utf-8"))


class ProviderFallbackTests(TestCase):
    def test_deepseek_writer_disables_thinking_mode(self) -> None:
        import sys
        import types
        from types import SimpleNamespace

        calls: list[dict] = []

        class FakeOpenAI:
            def __init__(self, **kwargs):
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

            def create(self, **kwargs):
                calls.append(kwargs)
                if kwargs.get("stream"):
                    return iter(
                        [
                            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="# Writer\n\n"))]),
                            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="ok"))]),
                        ]
                    )
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="# Writer\n\nok"))],
                    usage=SimpleNamespace(model_dump=lambda: {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}),
                )

        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = FakeOpenAI
        previous_openai = sys.modules.get("openai")
        sys.modules["openai"] = fake_openai
        try:
            result = generate_text(
                LLMSettings(
                    provider="deepseek",
                    provider_type="openai_compatible",
                    model="deepseek-v4-flash",
                    base_url="https://api.deepseek.com",
                    api_key_configured=True,
                    max_output_tokens=128,
                ),
                {
                    "providers": {
                        "deepseek": {
                            "type": "openai_compatible",
                            "api_key": "deepseek-key",
                            "base_url": "https://api.deepseek.com",
                        }
                    }
                },
                [{"role": "user", "content": "write"}],
                agent_name="Writer",
            )
        finally:
            if previous_openai is None:
                sys.modules.pop("openai", None)
            else:
                sys.modules["openai"] = previous_openai

        self.assertEqual(result.status, "completed")
        self.assertEqual(calls[0]["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertTrue(calls[0]["stream"])
        self.assertEqual(result.content, "# Writer\n\nok")
        self.assertTrue(result.raw_usage["streaming"])

    def test_build_fallback_provider_chain_from_config(self) -> None:
        model_providers = {
            "defaults": {"fallback_provider": "deepseek"},
            "providers": {
                "qwen3": {
                    "type": "openai_compatible",
                    "fallback_provider": "deepseek",
                    "default_model": "qwen3.7-max",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                },
                "deepseek": {
                    "type": "openai_compatible",
                    "fallback_provider": "qwen3",
                    "default_model": "deepseek-v4-pro",
                    "base_url": "https://api.deepseek.com",
                },
            },
        }

        chain = build_fallback_provider_chain(model_providers, "qwen3")

        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0]["key"], "deepseek")
        self.assertEqual(chain[0]["model"], "deepseek-v4-pro")

    def test_generate_text_auto_retries_configured_fallback_provider(self) -> None:
        import sys
        import types
        from types import SimpleNamespace

        calls: list[str] = []

        class FakeOpenAI:
            def __init__(self, **kwargs):
                self.base_url = kwargs.get("base_url")
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

            def create(self, **kwargs):
                calls.append(kwargs["model"])
                if kwargs["model"] == "qwen3.7-max":
                    raise TimeoutError("network timeout while calling qwen3")
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="# RepoScout Report\n\nfallback ok"))],
                    usage=SimpleNamespace(model_dump=lambda: {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}),
                )

        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = FakeOpenAI
        previous_openai = sys.modules.get("openai")
        sys.modules["openai"] = fake_openai

        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            model_providers = {
                "providers": {
                    "qwen3": {
                        "type": "openai_compatible",
                        "api_key": "qwen-key",
                        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                        "default_model": "qwen3.7-max",
                        "fallback_provider": "deepseek",
                    },
                    "deepseek": {
                        "type": "openai_compatible",
                        "api_key": "deepseek-key",
                        "base_url": "https://api.deepseek.com",
                        "default_model": "deepseek-v4-pro",
                    },
                }
            }
            settings = LLMSettings(
                provider="qwen3",
                provider_type="openai_compatible",
                model="qwen3.7-max",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                api_key_configured=True,
                max_output_tokens=128,
            )
            try:
                result = generate_text(
                    settings,
                    model_providers,
                    [{"role": "user", "content": "scan repo"}],
                    agent_name="RepoScout",
                    run_dir=str(run_dir),
                    project="Demo",
                    task_id="task_fb",
                    role="repo_reader",
                    risk_level="R1",
                    route=["RepoScout"],
                )
            finally:
                if previous_openai is None:
                    sys.modules.pop("openai", None)
                else:
                    sys.modules["openai"] = previous_openai

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.provider, "deepseek")
        self.assertEqual(result.fallback_from, "qwen3")
        self.assertEqual(calls, ["qwen3.7-max", "deepseek-v4-pro"])
        self.assertTrue(result.raw_usage["auto_fallback"])

    def test_generate_text_retries_retryable_network_error_before_guard(self) -> None:
        import sys
        import types
        from types import SimpleNamespace
        from unittest.mock import patch

        calls: list[str] = []

        class FakeOpenAI:
            def __init__(self, **kwargs):
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

            def create(self, **kwargs):
                calls.append(kwargs["model"])
                if len(calls) == 1:
                    raise TimeoutError("network timeout while streaming")
                if kwargs.get("stream"):
                    return iter(
                        [
                            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="# Writer\n\n"))]),
                            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="ok"))]),
                        ]
                    )
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="# Writer\n\nok"))],
                    usage=SimpleNamespace(model_dump=lambda: {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}),
                )

        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = FakeOpenAI
        previous_openai = sys.modules.get("openai")
        sys.modules["openai"] = fake_openai

        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            model_providers = {
                "providers": {
                    "deepseek": {
                        "type": "openai_compatible",
                        "api_key": "deepseek-key",
                        "base_url": "https://api.deepseek.com",
                        "default_model": "deepseek-v4-flash",
                    },
                }
            }
            settings = LLMSettings(
                provider="deepseek",
                provider_type="openai_compatible",
                model="deepseek-v4-flash",
                base_url="https://api.deepseek.com",
                api_key_configured=True,
                max_output_tokens=128,
            )
            try:
                with patch("llm_provider.time.sleep"):
                    result = generate_text(
                        settings,
                        model_providers,
                        [{"role": "user", "content": "write"}],
                        agent_name="Writer",
                        run_dir=str(run_dir),
                        project="Demo",
                        task_id="task_writer_retry",
                        role="writer",
                        risk_level="R2",
                        route=["Supervisor", "Writer"],
                    )
            finally:
                if previous_openai is None:
                    sys.modules.pop("openai", None)
                else:
                    sys.modules["openai"] = previous_openai

        self.assertEqual(result.status, "completed")
        self.assertEqual(calls, ["deepseek-v4-flash", "deepseek-v4-flash"])
        self.assertFalse((run_dir / "USER_DECISION_REQUIRED.md").exists())


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

    def test_validate_artifacts_requires_production_pack_outputs_and_respects_skipped_archive(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "workflow_plan.yml").write_text(
                "\n".join([
                    "route:",
                    "  agents:",
                    "    - Supervisor",
                    "    - ArtifactProducer",
                    "    - Archivist",
                    "production_pack:",
                    "  pack_id: media_series_production",
                    "  required_outputs:",
                    "    - episode_plan.yml",
                    "    - prompt_pack.yml",
                    "",
                ]),
                encoding="utf-8",
            )
            (run_dir / "lifecycle.yml").write_text(
                "\n".join([
                    "nodes:",
                    "  ARTIFACT_PRODUCTION:",
                    "    status: completed",
                    "  ARCHIVE:",
                    "    status: skipped",
                    "    skip_reason: Production pack media_series_production excludes ARCHIVE",
                    "",
                ]),
                encoding="utf-8",
            )
            for name in [
                "user_request.md",
                "state.yml",
                "progress.yml",
                "task_snapshot.yml",
                "brain_decisions.yml",
                "cost_ledger.yml",
                "self_check_report.yml",
                "task_card.yml",
                "artifact_manifest.yml",
                "01_supervisor_plan.md",
                "artifact_producer_report.md",
                "episode_plan.yml",
            ]:
                (run_dir / name).write_text("ok: true\n", encoding="utf-8")

            result = validate_artifacts(run_dir)

            self.assertFalse(result["valid"])
            self.assertIn({"file": "prompt_pack.yml", "issue": "missing"}, result["issues"])
            self.assertNotIn({"file": "artifact_lineage.yml", "issue": "missing"}, result["issues"])
            self.assertNotIn({"file": "archive_receipt.yml", "issue": "missing"}, result["issues"])


if __name__ == "__main__":
    main()
