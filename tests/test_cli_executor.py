"""Tests for cli_executor.py — the CLI Agent executor dispatch module.

These tests are fully unit-level and offline: no real subprocesses are spawned
against hermes or claude_code binaries; instead subprocess.run is patched.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

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
        assert "Supervisor Report" in result.content
        assert "command_id" in result.raw_usage
        assert f"command_id {result.raw_usage['command_id']}" in result.content
        execution_log = yaml.safe_load((run_dir / "execution_log.yml").read_text(encoding="utf-8"))
        assert execution_log["commands"][0]["command_id"] == result.raw_usage["command_id"]
        assert execution_log["commands"][0]["exit_code"] == 0

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
        assert "binary_candidate_used" not in result.raw_usage
