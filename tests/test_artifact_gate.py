from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from artifact_contract import artifact_content_issues, validate_artifacts
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
