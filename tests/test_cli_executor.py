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
                    "cli_command": "hermes --task {task_packet_path}",
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
        result = resolve_cli_profile(profiles, "balanced", "supervisor")
        assert result is not None
        assert result["cli_agent"] == "hermes"

    def test_returns_none_when_direct_api(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        profiles = _sample_profiles("direct_api")
        result = resolve_cli_profile(profiles, "balanced", "supervisor")
        assert result is None

    def test_returns_none_for_frugal_direct_api(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        profiles = _sample_profiles()
        result = resolve_cli_profile(profiles, "frugal", "supervisor")
        assert result is None

    def test_returns_none_for_unknown_profile(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        result = resolve_cli_profile({}, "nonexistent", "supervisor")
        assert result is None


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

        argv = _render_command("hermes --task {task_packet_path}", tmp_path / "pkt.json")
        assert argv[0] == "hermes"
        assert str(tmp_path / "pkt.json") in argv

    def test_appends_path_when_no_placeholder(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _render_command

        argv = _render_command("hermes --task", tmp_path / "pkt.json")
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
            "cli_command": "hermes --task {task_packet_path}",
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
            "cli_command": "hermes --task {task_packet_path}",
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
            "cli_command": "hermes --task {task_packet_path}",
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
            "cli_command": "hermes --task {task_packet_path}",
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
            "cli_command": "hermes --task {task_packet_path}",
        }

        mock_proc = self._mock_proc(127, stdout="", stderr="hermes: command not found")

        with patch("cli_executor.shutil.which", return_value="/usr/bin/hermes"), \
             patch("cli_executor.subprocess.run", return_value=mock_proc):
            result = run_cli_agent(plan, "Supervisor", role_profile)

        assert isinstance(result, CliAgentNotAvailable)

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
