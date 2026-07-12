"""Tests for cli_executor.py — the CLI Agent executor dispatch module.

These tests are fully unit-level and offline: no real subprocesses are spawned
against hermes or claude_code binaries; instead subprocess.run is patched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
import yaml

if TYPE_CHECKING:
    from agent_runtime.schemas import WorkflowPlan

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan(tmp_path: Path, budget_mode: str = "balanced") -> "WorkflowPlan":
    """Build a minimal WorkflowPlan-like object for testing."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
    from schemas import AgentRoute, WorkflowPlan

    route = AgentRoute(task_size="small", agents=["Supervisor", "Coder"])
    return WorkflowPlan(
        project="TestProject",
        task_id="task_test_001",
        agentlab_root=str(tmp_path),
        project_root=str(tmp_path / "projects" / "TestProject"),
        repo_path=str(tmp_path / "projects" / "TestProject"),
        run_dir=str(tmp_path / "projects" / "TestProject" / "runs" / "task_test_001"),
        user_request_path=str(tmp_path / "projects" / "TestProject" / "runs" / "task_test_001" / "user_request.md"),
        budget_mode=budget_mode,
        route=route,
    )


def _sample_profiles(executor_type: str = "cli_agent") -> dict:
    """Return a minimal agent_model_profiles dict."""
    return {
        "schema_version": 3,
        "profiles": {
            "balanced": {
                "supervisor": {
                    "executor_type": executor_type,
                    "cli_agent": "hermes",
                    "cli_command": 'hermes -z "You are an AgentLab CLI executor. Read the JSON task packet at {task_packet_path}, perform the requested AgentLab role work, and return a concise markdown report with findings, actions taken, verification, and blockers."',
                    "default": "deepseek_v4_pro",
                    "fallback": "qwen3_6_plus_dashscope",
                },
                "coder": {
                    "executor_type": executor_type,
                    "cli_agent": "claude_code",
                    "cli_command": "claude --task {task_packet_path}",
                    "default": "qwen3_coder_plus_dashscope",
                    "fallback": "deepseek_v4_flash",
                },
            },
            "frugal": {
                "supervisor": {
                    "executor_type": "direct_api",
                    "default": "deepseek_v4_flash",
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# resolve_cli_profile
# ---------------------------------------------------------------------------

class TestResolveCliProfile:
    def test_returns_profile_when_cli_agent(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        profiles = _sample_profiles("cli_agent")
        result = resolve_cli_profile(profiles, agent_role="supervisor", profile_name="balanced")
        assert result is not None
        assert result["cli_agent"] == "hermes"

    def test_returns_none_when_direct_api(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        profiles = _sample_profiles("direct_api")
        result = resolve_cli_profile(profiles, agent_role="supervisor", profile_name="balanced")
        assert result is None

    def test_returns_none_for_frugal_direct_api(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        profiles = _sample_profiles()
        result = resolve_cli_profile(profiles, agent_role="supervisor", profile_name="frugal")
        assert result is None

    def test_returns_none_for_unknown_profile(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        result = resolve_cli_profile({}, agent_role="supervisor", profile_name="nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# resolve_cli_profile — schema v4 (modes)
# ---------------------------------------------------------------------------


def _sample_modes_v4(executor_type: str = "cli_agent") -> dict:
    """Return a minimal schema v4 agent_model_profiles dict."""
    return {
        "schema_version": 4.0,
        "default_mode": "full_cli",
        "modes": {
            "full_cli": {
                "tiers": {
                    "full": {
                        "supervisor": {
                            "executor_type": executor_type,
                            "cli_agent": "hermes",
                            "cli_command": 'hermes -z "Read {task_packet_path}"',
                            "default": "deepseek_v4_pro",
                        },
                        "coder": {
                            "executor_type": executor_type,
                            "cli_agent": "claude_code",
                            "cli_command": "ccs --output-format json -p \"Read {task_packet_path}\"",
                            "default": "qwen3_coder_plus_dashscope",
                        },
                    },
                    "performance": {
                        "supervisor": {
                            "executor_type": executor_type,
                            "cli_agent": "hermes",
                            "cli_command": 'hermes -z "Read {task_packet_path}"',
                            "default": "deepseek_v4_pro",
                        },
                    },
                    "low": {
                        "supervisor": {
                            "executor_type": executor_type,
                            "cli_agent": "hermes",
                            "cli_command": 'hermes -z "Read {task_packet_path}"',
                            "default": "deepseek_v4_flash",
                        },
                        "interface_mapper": "skip",
                        "researcher": "skip",
                        "verifier": "skip",
                    },
                },
            },
            "full_api": {
                "tiers": {
                    "full": {
                        "supervisor": {
                            "executor_type": "direct_api",
                            "default": "deepseek_v4_pro",
                        },
                    },
                },
            },
            "hybrid_ide": {
                "tiers": {
                    "full": {
                        "coder": {
                            "executor_type": "special",
                            "provider": "external_ide_ai",
                        },
                    },
                },
            },
        },
    }


class TestResolveCliProfileSchemaV4:
    """Prove resolve_cli_profile supports schema v4 modes/tiers layout."""

    def test_real_default_full_cli_supervisor_resolves_to_hermes_codex(self):
        """The real default mode/tier keeps Supervisor on Hermes Codex OAuth."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        root = Path(__file__).resolve().parents[1]
        profiles = yaml.safe_load((root / "config" / "agent_model_profiles.yml").read_text(encoding="utf-8"))

        result = resolve_cli_profile(profiles, agent_role="supervisor")

        assert result is not None
        assert result["resolved_mode"] == "full_cli"
        assert result["resolved_tier"] == "performance"
        assert result["cli_agent"] == "hermes"
        assert result["invocation_contract"] == "hermes"
        assert result["default"] == "codex_gpt_5_5_high_hermes_oauth"
        assert result["fallback_cli_agent"] == "claude_code"
        assert result["fallback_invocation_contract"] == "claude"
        assert result["fallback"] == "deepseek_v4_pro"

    def test_real_default_full_cli_writer_resolves_to_agy_gemini_oauth(self):
        """The real default mode/tier keeps Writer on Agy Gemini OAuth."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        root = Path(__file__).resolve().parents[1]
        profiles = yaml.safe_load((root / "config" / "agent_model_profiles.yml").read_text(encoding="utf-8"))

        result = resolve_cli_profile(profiles, agent_role="writer")

        assert result is not None
        assert result["resolved_mode"] == "full_cli"
        assert result["resolved_tier"] == "performance"
        assert result["cli_agent"] == "agy"
        assert result["invocation_contract"] == "agy_writer"
        assert result["default"] == "gemini_3_5_flash_high_agy_oauth"
        assert result["fallback_cli_agent"] == "claude_code"
        assert result["fallback_invocation_contract"] == "claude"
        assert result["fallback"] == "deepseek_v4_flash"

    def test_full_cli_full_supervisor_resolves_cli(self):
        """Schema v4 full_cli/full/supervisor returns CLI profile with hermes."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        profiles = _sample_modes_v4("cli_agent")
        result = resolve_cli_profile(
            profiles, agent_role="supervisor", budget_mode="full", mode="full_cli"
        )
        assert result is not None, "full_cli/full/supervisor should resolve to CLI"
        assert result["cli_agent"] == "hermes"
        assert "hermes" in result["cli_command"]
        assert result["default"] == "deepseek_v4_pro"
        assert result["resolved_schema"] == "modes_v4"
        assert result["resolved_mode"] == "full_cli"
        assert result["resolved_tier"] == "full"

    def test_performance_tier_resolves_correct_cli(self):
        """Schema v4 full_cli/performance/supervisor resolves from performance tier."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        profiles = _sample_modes_v4("cli_agent")
        result = resolve_cli_profile(
            profiles, agent_role="supervisor", budget_mode="performance", mode="full_cli"
        )
        assert result is not None, "performance tier supervisor should resolve to CLI"
        assert result["cli_agent"] == "hermes"
        assert result["resolved_tier"] == "performance"

    def test_low_tier_skip_returns_none(self):
        """Schema v4 low tier with interface_mapper: skip returns None."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        profiles = _sample_modes_v4("cli_agent")
        result = resolve_cli_profile(
            profiles, agent_role="interface_mapper", budget_mode="low", mode="full_cli"
        )
        assert result is None, "interface_mapper: skip should return None"

    def test_direct_api_role_does_not_become_cli(self):
        """Schema v4 full_api/full/supervisor (executor_type: direct_api) returns None."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        profiles = _sample_modes_v4("cli_agent")
        result = resolve_cli_profile(
            profiles, agent_role="supervisor", budget_mode="full", mode="full_api"
        )
        assert result is None, "direct_api role should NOT become CLI"

    def test_legacy_profiles_still_work(self):
        """Old profiles schema still resolves with profile_name kwarg."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        profiles = _sample_profiles("cli_agent")
        result = resolve_cli_profile(
            profiles, agent_role="supervisor", profile_name="balanced"
        )
        assert result is not None
        assert result["cli_agent"] == "hermes"
        assert result["resolved_schema"] == "legacy_profiles"

    def test_no_auto_model_injection_into_cli_command(self):
        """CLI command does NOT contain -m or --model unless template has it."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        profiles = _sample_modes_v4("cli_agent")
        result = resolve_cli_profile(
            profiles, agent_role="supervisor", budget_mode="full", mode="full_cli"
        )
        assert result is not None
        cli_command = result["cli_command"]
        # Must NOT contain auto-injected -m or --model
        assert "-m deepseek_v4_pro" not in cli_command, (
            f"CLI command must not auto-inject -m: {cli_command}"
        )
        assert "--model deepseek_v4_pro" not in cli_command, (
            f"CLI command must not auto-inject --model: {cli_command}"
        )

    def test_budget_mode_frugal_maps_to_low_tier(self):
        """budget_mode='frugal' maps to 'low' tier via budget_mode_to_tier."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        profiles = _sample_modes_v4("cli_agent")
        result = resolve_cli_profile(
            profiles, agent_role="supervisor", budget_mode="frugal", mode="full_cli"
        )
        assert result is not None
        assert result["resolved_tier"] == "low"
        assert result["default"] == "deepseek_v4_flash"

    def test_invocation_contract_resolves_cli_template(self, tmp_path):
        """CLI profiles can reference worker_invocation_contracts.yml."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _resolve_invocation_contract_template

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "worker_invocation_contracts.yml").write_text(
            """
contracts:
  hermes:
    template: 'hermes -z "Read {task_packet_path}"'
""",
            encoding="utf-8",
        )

        template = _resolve_invocation_contract_template(
            {
                "executor_type": "cli_agent",
                "cli_agent": "hermes",
                "invocation_contract": "hermes",
            },
            tmp_path,
        )

        assert template == 'hermes -z "Read {task_packet_path}"'


# ---------------------------------------------------------------------------
# _write_task_packet
# ---------------------------------------------------------------------------

class TestWriteTaskPacket:
    def test_writes_json_with_required_fields(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _write_task_packet

        plan = _make_plan(tmp_path)
        run_dir = tmp_path / "runs" / "task_test_001"
        run_dir.mkdir(parents=True)

        packet_path = _write_task_packet(run_dir, "Supervisor", plan)
        assert packet_path.exists()

        data = json.loads(packet_path.read_text())
        assert data["agent"] == "Supervisor"
        assert data["project"] == "TestProject"
        assert data["task_id"] == "task_test_001"
        assert "generated_at" in data

    def test_packet_path_uses_agent_name(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _write_task_packet

        plan = _make_plan(tmp_path)
        run_dir = tmp_path / "runs"
        run_dir.mkdir(parents=True)

        path = _write_task_packet(run_dir, "Coder", plan)
        assert path.name == "task_packet_coder.json"

    def test_writer_sealed_packet_omits_project_paths(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _write_task_packet

        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True)
        messages = [
            {"role": "system", "content": "Use only injected context."},
            {"role": "user", "content": "Write the candidate chapter."},
        ]

        packet_path = _write_task_packet(run_dir, "Writer", plan, sealed_messages=messages)
        packet = json.loads(packet_path.read_text(encoding="utf-8"))

        assert packet["packet_type"] == "agentlab_sealed_role_session"
        assert packet["messages"] == messages
        assert packet["context_policy"]["additional_file_reads_allowed"] is False
        assert "agentlab_root" not in packet
        assert "project_root" not in packet
        assert "run_dir" not in packet
        assert "user_request_path" not in packet

    def test_production_pack_role_packet_is_bounded_to_embedded_contract(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _write_task_packet

        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True)
        messages = [
            {"role": "system", "content": "ArtifactProducer contract."},
            {"role": "user", "content": "Return exactly three candidate files."},
        ]

        packet_path = _write_task_packet(
            run_dir,
            "ArtifactProducer",
            plan,
            task_messages=messages,
        )
        packet = json.loads(packet_path.read_text(encoding="utf-8"))

        assert packet["packet_type"] == "agentlab_production_pack_role_session"
        assert packet["messages"] == messages
        assert packet["context_policy"]["returned_artifacts_require_agentlab_materialization"] is True
        assert packet["context_policy"]["read_scope"] == ["this_task_packet"]
        assert packet["context_policy"]["additional_file_reads_allowed"] is False
        assert "agentlab_root" not in packet
        assert "project_root" not in packet
        assert "run_dir" not in packet
        assert "user_request_path" not in packet


# ---------------------------------------------------------------------------
# _render_command
# ---------------------------------------------------------------------------

class TestRenderCommand:
    def test_substitutes_placeholder(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _render_command

        argv = _render_command('hermes -z "You are an AgentLab CLI executor. Read the JSON task packet at {task_packet_path}, perform the requested AgentLab role work, and return a concise markdown report with findings, actions taken, verification, and blockers."', tmp_path / "pkt.json")
        assert argv[0] == "hermes"
        assert any(str(tmp_path / "pkt.json") in arg for arg in argv)

    def test_appends_path_when_no_placeholder(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _render_command

        argv = _render_command("agent-cli --task", tmp_path / "pkt.json")
        assert str(tmp_path / "pkt.json") in argv

    def test_substitutes_workspace_path(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _render_command

        workspace = tmp_path / "workspace"
        argv = _render_command(
            'codex exec -C "{workspace_path}" "Read {task_packet_path}"',
            tmp_path / "pkt.json",
            workspace_path=workspace,
        )

        assert str(workspace) in argv
        assert any(str(tmp_path / "pkt.json") in arg for arg in argv)

    def test_substitutes_declared_model_placeholders(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _render_command

        argv = _render_command(
            'hermes --provider {provider} -m {model_id} -z "Read {task_packet_path}"',
            tmp_path / "pkt.json",
            provider="openai-codex",
            model_id="gpt-5.5",
            model_key="codex_gpt_5_5_high_hermes_oauth",
        )

        assert argv[:5] == ["hermes", "--provider", "openai-codex", "-m", "gpt-5.5"]
        assert any(str(tmp_path / "pkt.json") in arg for arg in argv)

    def test_rejects_unresolved_placeholders(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _render_command

        with pytest.raises(ValueError, match="frontdesk_session_path"):
            _render_command(
                'agy --sandbox -p "Read {frontdesk_session_path}"',
                tmp_path / "pkt.json",
            )


# ---------------------------------------------------------------------------
# run_cli_agent — binary not found
# ---------------------------------------------------------------------------

class TestRunCliAgentBinaryNotFound:
    def test_returns_not_available_when_binary_missing(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import CliAgentNotAvailable, run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "hermes",
            "cli_command": "hermes_binary_does_not_exist_xyz --task {task_packet_path}",
            "default": "deepseek_v4_pro",
        }

        with patch("cli_executor.shutil.which", return_value=None):
            result = run_cli_agent(plan, "Supervisor", role_profile)

        assert isinstance(result, CliAgentNotAvailable)
        assert "hermes" in result.cli_agent or "not_found" in result.reason

    def test_returns_not_available_on_filenotfounderror(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import CliAgentNotAvailable, run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "hermes",
            "cli_command": 'hermes -z "You are an AgentLab CLI executor. Read the JSON task packet at {task_packet_path}, perform the requested AgentLab role work, and return a concise markdown report with findings, actions taken, verification, and blockers."',
            "default": "deepseek_v4_pro",
        }

        with patch("cli_executor.shutil.which", return_value="/usr/bin/hermes"), \
             patch("cli_executor.subprocess.run", side_effect=FileNotFoundError("hermes")):
            result = run_cli_agent(plan, "Supervisor", role_profile)

        assert isinstance(result, CliAgentNotAvailable)


# ---------------------------------------------------------------------------
# run_cli_agent — subprocess success and failure
# ---------------------------------------------------------------------------

class TestRunCliAgentSubprocess:
    def _mock_proc(self, returncode: int, stdout: str = "", stderr: str = ""):
        proc = MagicMock()
        proc.returncode = returncode
        proc.stdout = stdout
        proc.stderr = stderr
        return proc

    def test_completed_on_exit_0(self, tmp_path):
        import sys
        import yaml
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        run_dir = tmp_path / "projects" / "TestProject" / "runs" / "task_test_001"
        run_dir.mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "hermes",
            "cli_command": 'hermes -z "You are an AgentLab CLI executor. Read the JSON task packet at {task_packet_path}, perform the requested AgentLab role work, and return a concise markdown report with findings, actions taken, verification, and blockers."',
            "default": "deepseek_v4_pro",
        }

        mock_proc = self._mock_proc(0, stdout="# Supervisor Report\n\nAll good.")

        with patch("cli_executor.shutil.which", return_value="/usr/bin/hermes"), \
             patch("cli_executor.subprocess.run", return_value=mock_proc):
            result = run_cli_agent(plan, "Supervisor", role_profile)

        assert result.status == "completed"
        assert result.provider == "agentlab-cli-executor"
        assert result.model == "hermes"
        assert result.input_tokens is not None
        assert result.output_tokens is not None
        assert result.total_tokens == result.input_tokens + result.output_tokens
        assert result.raw_usage["usage_source"] == "external_cli_estimate"
        assert result.raw_usage["exact_usage_available"] is False
        assert result.raw_usage["exact_cost_available"] is False
        assert result.raw_usage["token_estimation_method"] == "chars_div_4_packet_command_stdout_stderr"
        assert "Supervisor Report" in result.content
        assert "command_id" in result.raw_usage
        assert f"command_id {result.raw_usage['command_id']}" in result.content
        execution_log = yaml.safe_load((run_dir / "execution_log.yml").read_text(encoding="utf-8"))
        assert execution_log["commands"][0]["command_id"] == result.raw_usage["command_id"]
        assert execution_log["commands"][0]["exit_code"] == 0

    def test_writer_cli_uses_sealed_packet_and_isolated_workspace(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        source = run_dir / "chapter_packet.yml"
        source.write_text("chapter: 1\n", encoding="utf-8")
        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "agy",
            "cli_command": 'agy --sandbox -p "Read only {task_packet_path}"',
        }
        observed: dict[str, object] = {}

        def fake_run(argv, **kwargs):
            packet_path = Path(kwargs["cwd"]) / "task_packet_writer.json"
            observed["packet"] = json.loads(packet_path.read_text(encoding="utf-8"))
            observed["workspace"] = Path(kwargs["cwd"])
            observed["packet_path"] = packet_path
            return self._mock_proc(0, stdout="writer output", stderr="")

        with patch("cli_executor.shutil.which", return_value="/usr/bin/agy"), \
             patch("cli_executor.subprocess.run", side_effect=fake_run):
            result = run_cli_agent(
                plan,
                "Writer",
                role_profile,
                sealed_messages=[{"role": "user", "content": "sealed chapter context"}],
                outbound_source_paths=[source],
            )

        assert result.status == "completed"
        assert result.raw_usage["sealed_context"] is True
        assert result.raw_usage["execution_workspace_isolated"] is True
        assert observed["workspace"] != Path(plan.agentlab_root)
        assert observed["packet_path"].parent == observed["workspace"]
        assert observed["packet"]["context_policy"]["read_scope"] == ["this_task_packet"]
        assert not Path(observed["workspace"]).exists()
        manifest = yaml.safe_load(
            (run_dir / "outbound_context_manifest_writer.yml").read_text(encoding="utf-8")
        )
        assert manifest["status"] == "pass"
        assert manifest["context_boundary"]["execution_workspace_isolated"] is True

    def test_production_pack_cli_blocks_before_subprocess_without_scoped_approval(
        self, tmp_path
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent
        from outbound_context import PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME

        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        source = run_dir / "domain_research_brief.md"
        source.write_text("# Domain research\n", encoding="utf-8")
        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "agy",
            "cli_command": 'agy --sandbox -p "Read only {task_packet_path}"',
        }

        with patch.dict(
            "os.environ",
            {PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME: "0"},
            clear=False,
        ), patch("cli_executor.shutil.which", return_value="/usr/bin/agy"), patch(
            "cli_executor.subprocess.run"
        ) as subprocess_run:
            result = run_cli_agent(
                plan,
                "ArtifactProducer",
                role_profile,
                task_messages=[
                    {"role": "user", "content": "Return candidate YAML blocks."}
                ],
                outbound_source_paths=[source],
            )

        assert result.status == "blocked_user_decision"
        assert result.error == "artifactproducer_outbound_context_gate_blocked"
        subprocess_run.assert_not_called()
        assert not (run_dir / "task_packet_artifactproducer.json").exists()
        manifest = yaml.safe_load(
            (run_dir / "outbound_context_manifest_artifactproducer.yml").read_text(
                encoding="utf-8"
            )
        )
        assert manifest["status"] == "pending_approval"
        assert manifest["authorization"]["approval_env_name"] == (
            PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME
        )

    def test_approved_production_pack_cli_is_packet_only_and_isolated(
        self, tmp_path
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent
        from outbound_context import PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME

        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        source = run_dir / "domain_research_brief.md"
        source.write_text("# Domain research\n", encoding="utf-8")
        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "agy",
            "cli_command": 'agy --sandbox -p "Read only {task_packet_path}"',
        }
        observed: dict[str, object] = {}

        def fake_run(argv, **kwargs):
            packet_path = Path(kwargs["cwd"]) / "task_packet_artifactproducer.json"
            observed["packet"] = json.loads(
                packet_path.read_text(encoding="utf-8")
            )
            observed["workspace"] = Path(kwargs["cwd"])
            return self._mock_proc(0, stdout="candidate blocks", stderr="")

        with patch.dict(
            "os.environ",
            {PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME: "1"},
            clear=False,
        ), patch("cli_executor.shutil.which", return_value="/usr/bin/agy"), patch(
            "cli_executor.subprocess.run", side_effect=fake_run
        ):
            result = run_cli_agent(
                plan,
                "ArtifactProducer",
                role_profile,
                task_messages=[
                    {"role": "user", "content": "Return candidate YAML blocks."}
                ],
                outbound_source_paths=[source],
            )

        assert result.status == "completed"
        assert result.raw_usage["sealed_context"] is True
        assert result.raw_usage["execution_workspace_isolated"] is True
        assert observed["workspace"] != Path(plan.agentlab_root)
        packet = observed["packet"]
        assert isinstance(packet, dict)
        assert packet["packet_type"] == "agentlab_production_pack_role_session"
        assert packet["context_policy"]["read_scope"] == ["this_task_packet"]
        assert "agentlab_root" not in packet
        assert not Path(observed["workspace"]).exists()
        manifest = yaml.safe_load(
            (run_dir / "outbound_context_manifest_artifactproducer.yml").read_text(
                encoding="utf-8"
            )
        )
        assert manifest["status"] == "pass"
        assert manifest["payload"]["kind"] == (
            "production_pack_cli_role_session_packet"
        )
        assert manifest["source_inventory"]["count"] == 1

    def test_production_pack_cli_blocks_secret_even_with_approval(
        self, tmp_path
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent
        from outbound_context import PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME

        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        source = run_dir / "domain_research_brief.md"
        source.write_text("# Domain research\n", encoding="utf-8")
        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "agy",
            "cli_command": 'agy --sandbox -p "Read only {task_packet_path}"',
        }
        secret = "sk-" + ("a" * 40)

        with patch.dict(
            "os.environ",
            {PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME: "1"},
            clear=False,
        ), patch("cli_executor.subprocess.run") as subprocess_run:
            result = run_cli_agent(
                plan,
                "Verifier",
                role_profile,
                task_messages=[
                    {"role": "user", "content": f"credential: {secret}"}
                ],
                outbound_source_paths=[source],
            )

        assert result.status == "blocked_user_decision"
        subprocess_run.assert_not_called()
        manifest_text = (
            run_dir / "outbound_context_manifest_verifier.yml"
        ).read_text(encoding="utf-8")
        assert "secret_pattern_detected" in manifest_text
        assert secret not in manifest_text

    def test_completed_uses_reported_usage_sidecar(self, tmp_path):
        import json
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        run_dir = tmp_path / "projects" / "TestProject" / "runs" / "task_test_001"
        run_dir.mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "hermes",
            "cli_command": 'hermes -z "task {task_packet_path}"',
            "default": "deepseek_v4_pro",
        }
        mock_proc = self._mock_proc(0, stdout="# Supervisor Report\n\nAll good.")

        def _write_usage(*args, **kwargs):
            (run_dir / "usage_supervisor.json").write_text(
                json.dumps({
                    "agentlab_usage": {
                        "input_tokens": 111,
                        "output_tokens": 22,
                        "total_tokens": 133,
                        "estimated_cost": 0.0042,
                        "currency": "USD",
                    }
                }),
                encoding="utf-8",
            )
            return mock_proc

        with patch("cli_executor.shutil.which", return_value="/usr/bin/hermes"), \
             patch("cli_executor.subprocess.run", side_effect=_write_usage):
            result = run_cli_agent(plan, "Supervisor", role_profile)

        assert result.input_tokens == 111
        assert result.output_tokens == 22
        assert result.total_tokens == 133
        assert result.raw_usage["usage_source"] == "external_cli_reported"
        assert result.raw_usage["exact_usage_available"] is True
        assert result.raw_usage["estimated_cost"] == 0.0042

    def test_blocked_on_nonzero_exit(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "hermes",
            "cli_command": 'hermes -z "You are an AgentLab CLI executor. Read the JSON task packet at {task_packet_path}, perform the requested AgentLab role work, and return a concise markdown report with findings, actions taken, verification, and blockers."',
        }

        mock_proc = self._mock_proc(1, stdout="", stderr="fatal error")

        with patch("cli_executor.shutil.which", return_value="/usr/bin/hermes"), \
             patch("cli_executor.subprocess.run", return_value=mock_proc):
            result = run_cli_agent(plan, "Supervisor", role_profile)

        assert result.status == "blocked_user_decision"
        assert result.error is not None

    def test_auth_failure_is_classified_without_raw_stderr_in_decision_reason(
        self, tmp_path
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(
            parents=True, exist_ok=True
        )
        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "agy",
            "cli_command": 'agy --sandbox -p "Read {task_packet_path}"',
        }
        stderr = "Authentication required. You are not logged into Antigravity."
        mock_proc = self._mock_proc(1, stdout="", stderr=stderr)

        with patch("cli_executor.shutil.which", return_value="/usr/bin/agy"), \
             patch("cli_executor.subprocess.run", return_value=mock_proc):
            result = run_cli_agent(plan, "ArtifactProducer", role_profile)

        assert result.status == "blocked_user_decision"
        assert result.raw_usage["failure_class"] == "auth_required"
        assert result.error == "CLI agent auth_required (exit 1)."
        assert stderr not in result.error

    def test_blocked_on_timeout(self, tmp_path):
        import subprocess
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "hermes",
            "cli_command": 'hermes -z "You are an AgentLab CLI executor. Read the JSON task packet at {task_packet_path}, perform the requested AgentLab role work, and return a concise markdown report with findings, actions taken, verification, and blockers."',
        }

        with patch("cli_executor.shutil.which", return_value="/usr/bin/hermes"), \
             patch("cli_executor.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="hermes", timeout=600)):
            result = run_cli_agent(plan, "Supervisor", role_profile, timeout=600)

        assert result.status == "blocked_user_decision"
        assert "timeout" in result.content.lower() or "timed out" in result.error.lower()

    def test_exit_127_returns_not_available(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import CliAgentNotAvailable, run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "hermes",
            "cli_command": 'hermes -z "You are an AgentLab CLI executor. Read the JSON task packet at {task_packet_path}, perform the requested AgentLab role work, and return a concise markdown report with findings, actions taken, verification, and blockers."',
        }

        mock_proc = self._mock_proc(127, stdout="", stderr="hermes: command not found")

        with patch("cli_executor.shutil.which", return_value="/usr/bin/hermes"), \
             patch("cli_executor.subprocess.run", return_value=mock_proc):
            result = run_cli_agent(plan, "Supervisor", role_profile)

        assert isinstance(result, CliAgentNotAvailable)

    def test_argparse_usage_error_returns_not_available(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import CliAgentNotAvailable, run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "hermes",
            "cli_command": "hermes --task {task_packet_path}",
        }

        mock_proc = self._mock_proc(
            2,
            stdout="",
            stderr="usage: hermes [-h] [-z PROMPT] ...\nhermes: error: unrecognized arguments: --task",
        )

        with patch("cli_executor.shutil.which", return_value="/usr/bin/hermes"), \
             patch("cli_executor.subprocess.run", return_value=mock_proc):
            result = run_cli_agent(plan, "Supervisor", role_profile)

        assert isinstance(result, CliAgentNotAvailable)
        assert result.reason == "invalid_cli_invocation"

    def test_raw_usage_contains_metadata(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "claude_code",
            "cli_command": "claude --task {task_packet_path}",
        }

        mock_proc = self._mock_proc(0, stdout="# Coder Report\n\nDone.")

        with patch("cli_executor.shutil.which", return_value="/usr/bin/claude"), \
             patch("cli_executor.subprocess.run", return_value=mock_proc):
            result = run_cli_agent(plan, "Coder", role_profile)

        assert "cli_agent" in result.raw_usage
        assert result.raw_usage["exit_code"] == 0
        assert "task_packet_path" in result.raw_usage


# ---------------------------------------------------------------------------
# Missing cli_agent / cli_command fields
# ---------------------------------------------------------------------------

class TestRunCliAgentMissingConfig:
    def test_missing_cli_command_returns_not_available(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import CliAgentNotAvailable, run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "hermes",
            # cli_command deliberately missing
        }

        result = run_cli_agent(plan, "Supervisor", role_profile)
        assert isinstance(result, CliAgentNotAvailable)

    def test_unrenderable_invocation_contract_returns_not_available(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import CliAgentNotAvailable, run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)
        (tmp_path / "config").mkdir(parents=True, exist_ok=True)
        (tmp_path / "config" / "worker_invocation_contracts.yml").write_text(
            """
contracts:
  agy:
    template: 'agy --sandbox -p "Read {frontdesk_session_path}"'
""",
            encoding="utf-8",
        )

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "agy",
            "invocation_contract": "agy",
        }

        result = run_cli_agent(plan, "RepoScout", role_profile)

        assert isinstance(result, CliAgentNotAvailable)
        assert result.reason == "invalid_cli_template"
        assert "frontdesk_session_path" in result.detail


# ---------------------------------------------------------------------------
# _resolve_binary_candidate unit tests
# ---------------------------------------------------------------------------

class TestResolveBinaryCandidate:
    def test_returns_first_available(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _resolve_binary_candidate

        with patch("cli_executor.shutil.which", side_effect=lambda x: {
            "claude": None,
            "ccs": "/usr/bin/ccs",
            "other": "/usr/bin/other",
        }.get(x)):
            result = _resolve_binary_candidate(["claude", "ccs", "other"])
            assert result == "ccs"

    def test_returns_none_when_none_available(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _resolve_binary_candidate

        with patch("cli_executor.shutil.which", return_value=None):
            result = _resolve_binary_candidate(["claude", "ccs"])
            assert result is None

    def test_empty_candidates_returns_none(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _resolve_binary_candidate

        result = _resolve_binary_candidate([])
        assert result is None


# ---------------------------------------------------------------------------
# binary_candidates resolution in run_cli_agent
# ---------------------------------------------------------------------------

class TestBinaryCandidateResolution:
    """Tests for binary_candidates field in role profiles."""

    def _mock_proc(self, returncode: int, stdout: str = "", stderr: str = ""):
        proc = MagicMock()
        proc.returncode = returncode
        proc.stdout = stdout
        proc.stderr = stderr
        return proc

    def test_canonical_claude_resolved_first(self, tmp_path):
        """When claude is available, argv[0] is claude, not ccs."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "claude_code",
            "binary_candidates": ["claude", "ccs"],
            "cli_command": 'claude -p "Read {task_packet_path}" --output-format json',
            "default": "qwen3_coder_plus_dashscope",
        }

        mock_proc = self._mock_proc(0, stdout="# Done")

        with patch("cli_executor.shutil.which", side_effect=lambda x: {
            "claude": "/usr/local/bin/claude",
            "ccs": "/usr/local/bin/ccs",
        }.get(x)), patch("cli_executor.subprocess.run", return_value=mock_proc) as mock_run:
            result = run_cli_agent(plan, "Coder", role_profile)

        assert result.status == "completed"
        called_argv = mock_run.call_args[0][0]
        assert called_argv[0] == "claude"
        assert result.raw_usage.get("binary") == "claude"
        assert result.raw_usage.get("binary_candidate_used") == "claude"

    def test_legacy_ccs_fallback_when_claude_absent(self, tmp_path):
        """When claude is missing but ccs exists, fall back to ccs."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "claude_code",
            "binary_candidates": ["claude", "ccs"],
            "cli_command": 'claude -p "Read {task_packet_path}" --output-format json',
            "default": "qwen3_coder_plus_dashscope",
        }

        mock_proc = self._mock_proc(0, stdout="# Done via ccs")

        with patch("cli_executor.shutil.which", side_effect=lambda x: {
            "claude": None,
            "ccs": "/usr/local/bin/ccs",
        }.get(x)), patch("cli_executor.subprocess.run", return_value=mock_proc) as mock_run:
            result = run_cli_agent(plan, "Coder", role_profile)

        assert result.status == "completed"
        called_argv = mock_run.call_args[0][0]
        assert called_argv[0] == "ccs"
        assert result.raw_usage.get("binary") == "ccs"
        assert result.raw_usage.get("binary_candidate_used") == "ccs"

    def test_no_candidates_available_returns_not_available(self, tmp_path):
        """When neither claude nor ccs is found, return CliAgentNotAvailable."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import CliAgentNotAvailable, run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "claude_code",
            "binary_candidates": ["claude", "ccs"],
            "cli_command": 'claude -p "Read {task_packet_path}" --output-format json',
            "default": "qwen3_coder_plus_dashscope",
        }

        with patch("cli_executor.shutil.which", return_value=None):
            result = run_cli_agent(plan, "Coder", role_profile)

        assert isinstance(result, CliAgentNotAvailable)
        assert result.reason == "binary_not_found"
        assert "claude" in result.detail
        assert "ccs" in result.detail

    def test_hermes_unaffected_by_candidates(self, tmp_path):
        """Hermes roles with no binary_candidates still work as before."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "hermes",
            "cli_command": 'hermes -z "test"',
            "default": "deepseek_v4_pro",
        }

        mock_proc = self._mock_proc(0, stdout="# Supervisor Report")

        with patch("cli_executor.shutil.which", return_value="/usr/bin/hermes"), \
             patch("cli_executor.subprocess.run", return_value=mock_proc) as mock_run:
            result = run_cli_agent(plan, "Supervisor", role_profile)

        assert result.status == "completed"
        called_argv = mock_run.call_args[0][0]
        assert called_argv[0] == "hermes"
        assert "binary_candidate_used" not in result.raw_usage

    def test_agy_unaffected_by_candidates(self, tmp_path):
        """Agy roles with no binary_candidates still work as before."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "agy",
            "cli_command": 'agy --sandbox -p "test"',
            "default": "qwen3_6_plus_dashscope",
        }

        mock_proc = self._mock_proc(0, stdout="# Done")

        with patch("cli_executor.shutil.which", return_value="/usr/bin/agy"), \
             patch("cli_executor.subprocess.run", return_value=mock_proc) as mock_run:
            result = run_cli_agent(plan, "Reposcout", role_profile)

        assert result.status == "completed"
        called_argv = mock_run.call_args[0][0]
        assert called_argv[0] == "agy"
        assert "--log-file" in called_argv
        log_path = Path(called_argv[called_argv.index("--log-file") + 1])
        assert log_path.name == "agy_cli_agent.log"
        assert log_path.parent.name == "command_logs"
        assert result.raw_usage.get("cli_log_path") == str(log_path)
        assert "binary_candidate_used" not in result.raw_usage

    def test_agy_empty_stderr_uses_cli_log_excerpt(self, tmp_path):
        """Agy can fail before stderr is wired; capture its local log as evidence."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "agy",
            "cli_command": 'agy --sandbox -p "test"',
            "default": "qwen3_6_plus_dashscope",
        }

        def fake_run(argv, **_kwargs):
            log_path = Path(argv[argv.index("--log-file") + 1])
            log_path.write_text(
                "CLI failed to start - listen tcp 127.0.0.1:0: bind: operation not permitted",
                encoding="utf-8",
            )
            return self._mock_proc(1, stdout="", stderr="")

        with patch("cli_executor.shutil.which", return_value="/usr/bin/agy"), \
             patch("cli_executor.subprocess.run", side_effect=fake_run):
            result = run_cli_agent(plan, "Writer", role_profile)

        assert result.status == "blocked_user_decision"
        assert result.error is not None
        assert result.error == "CLI agent permission_denied (exit 1)."
        assert "listen tcp 127.0.0.1:0" not in result.error
        assert result.raw_usage["failure_class"] == "permission_denied"
        assert "agy_cli_agent.log" in result.content
        assert result.raw_usage.get("cli_log_path", "").endswith("agy_cli_agent.log")
