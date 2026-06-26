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
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

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
