"""Tests for M2-12.5 Goal Acceptance — safety tripwires and end-to-end behavior.

These tests prove that the goal pipeline:
- Does not call subprocess
- Does not open network sockets
- Does not dispatch external executors
- Does not trigger automatic skill installation
"""

from __future__ import annotations

import pytest

from agent_runtime.goals.parser import parse_goal_command
from agent_runtime.goals.compiler import (
    compile_goal_set,
    compile_goal_plan,
    compile_goal_progress,
    compile_goal_report,
    compile_goal_validate,
)


# ── Safety Tripwire Tests ────────────────────────────────────────────


class TestGoalParserSafety:
    def test_goal_parser_does_not_call_subprocess(self, monkeypatch):
        """Goal parser must never call subprocess."""
        import subprocess

        def fail(*args, **kwargs):
            raise AssertionError("goal parser must not call subprocess")

        monkeypatch.setattr(subprocess, "run", fail)
        monkeypatch.setattr(subprocess, "call", fail)
        monkeypatch.setattr(subprocess, "check_call", fail)
        monkeypatch.setattr(subprocess, "check_output", fail)
        monkeypatch.setattr(subprocess, "Popen", fail)

        action = parse_goal_command("/目标 修复 AgentLab M2 主线并验收")
        assert action.action == "set"
        assert "AgentLab M2" in action.text

    def test_goal_parser_does_not_call_subprocess_english(self, monkeypatch):
        import subprocess

        def fail(*args, **kwargs):
            raise AssertionError("goal parser must not call subprocess")

        monkeypatch.setattr(subprocess, "run", fail)
        action = parse_goal_command("/goal set Repair AgentLab M2 mainline")
        assert action.action == "set"


class TestGoalCompilerSafety:
    def test_goal_set_does_not_call_subprocess(self, monkeypatch, tmp_path):
        import subprocess

        def fail(*args, **kwargs):
            raise AssertionError("goal set must not call subprocess")

        monkeypatch.setattr(subprocess, "run", fail)
        monkeypatch.setattr(subprocess, "call", fail)
        monkeypatch.setattr(subprocess, "Popen", fail)

        action = parse_goal_command("/goal set Test project")
        result = compile_goal_set(action, tmp_path, "TestSafety")
        assert result["ok"] is True

    def test_goal_plan_does_not_call_subprocess(self, monkeypatch, tmp_path):
        import subprocess

        def fail(*args, **kwargs):
            raise AssertionError("goal plan must not call subprocess")

        monkeypatch.setattr(subprocess, "run", fail)
        monkeypatch.setattr(subprocess, "call", fail)
        monkeypatch.setattr(subprocess, "Popen", fail)

        action = parse_goal_command("/goal set Test project")
        compile_goal_set(action, tmp_path, "TestSafety")
        result = compile_goal_plan(action, tmp_path, "TestSafety")
        assert result["ok"] is True

    def test_goal_progress_does_not_call_subprocess(self, monkeypatch, tmp_path):
        import subprocess

        def fail(*args, **kwargs):
            raise AssertionError("goal progress must not call subprocess")

        monkeypatch.setattr(subprocess, "run", fail)
        monkeypatch.setattr(subprocess, "call", fail)
        monkeypatch.setattr(subprocess, "Popen", fail)

        action = parse_goal_command("/goal set Test project")
        compile_goal_set(action, tmp_path, "TestSafety")
        compile_goal_plan(action, tmp_path, "TestSafety")
        result = compile_goal_progress(action, tmp_path, "TestSafety")
        assert result["ok"] is True

    def test_goal_validate_does_not_call_subprocess(self, monkeypatch, tmp_path):
        import subprocess

        def fail(*args, **kwargs):
            raise AssertionError("goal validate must not call subprocess")

        monkeypatch.setattr(subprocess, "run", fail)
        monkeypatch.setattr(subprocess, "call", fail)
        monkeypatch.setattr(subprocess, "Popen", fail)

        action = parse_goal_command("/goal set Test project")
        compile_goal_set(action, tmp_path, "TestSafety")
        compile_goal_plan(action, tmp_path, "TestSafety")
        compile_goal_progress(action, tmp_path, "TestSafety")
        result = compile_goal_validate(action, tmp_path, "TestSafety")
        assert result["status"] in ("pass", "blocked")

    def test_goal_report_does_not_call_subprocess(self, monkeypatch, tmp_path):
        import subprocess

        def fail(*args, **kwargs):
            raise AssertionError("goal report must not call subprocess")

        monkeypatch.setattr(subprocess, "run", fail)
        monkeypatch.setattr(subprocess, "call", fail)
        monkeypatch.setattr(subprocess, "Popen", fail)

        action = parse_goal_command("/goal set Test project")
        compile_goal_set(action, tmp_path, "TestSafety")
        compile_goal_plan(action, tmp_path, "TestSafety")
        compile_goal_progress(action, tmp_path, "TestSafety")
        result = compile_goal_report(action, tmp_path, "TestSafety")
        assert result["ok"] is True


class TestGoalNetworkSafety:
    def test_goal_pipeline_does_not_open_network_sockets(self, monkeypatch, tmp_path):
        """Goal pipeline must not make network calls."""
        import socket

        original_connect = socket.socket.connect

        def fail_connect(self, *args, **kwargs):
            raise AssertionError("goal pipeline must not open network sockets")

        monkeypatch.setattr(socket.socket, "connect", fail_connect, raising=False)

        action = parse_goal_command("/goal set Test project --project TestNet")
        compile_goal_set(action, tmp_path, "TestNet")
        compile_goal_plan(action, tmp_path, "TestNet")
        compile_goal_progress(action, tmp_path, "TestNet")
        compile_goal_validate(action, tmp_path, "TestNet")
        compile_goal_report(action, tmp_path, "TestNet")

        # Restore to not break other tests
        monkeypatch.setattr(socket.socket, "connect", original_connect, raising=False)

    def test_goal_pipeline_does_not_use_requests(self, monkeypatch, tmp_path):
        """Goal pipeline must not import/use requests."""
        import builtins

        original_import = builtins.__import__

        def guard_import(name, *args, **kwargs):
            if name in ("requests", "urllib.request", "urllib3"):
                raise AssertionError(f"goal pipeline must not import {name}")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", guard_import, raising=False)

        # Re-import to trigger guard
        from agent_runtime.goals import (
            parse_goal_command,
            compile_goal_set,
            compile_goal_plan,
            compile_goal_progress,
            compile_goal_validate,
            compile_goal_report,
        )

        action = parse_goal_command("/goal set Test project --project TestNet2")
        compile_goal_set(action, tmp_path, "TestNet2")
        compile_goal_plan(action, tmp_path, "TestNet2")
        compile_goal_progress(action, tmp_path, "TestNet2")
        compile_goal_validate(action, tmp_path, "TestNet2")
        compile_goal_report(action, tmp_path, "TestNet2")


class TestGoalNoExternalExecutorDispatch:
    def test_goal_pipeline_does_not_dispatch_external_executor(self, tmp_path):
        """M2-12.5 goal pipeline imports no executor dispatch module and uses
        only deterministic local storage. This is verified by checking that
        the goal pipeline modules don't import external executor symbols."""
        import agent_runtime.goals.compiler as compiler_mod
        import inspect

        # The compiler module should not contain executor dispatch functions
        source = inspect.getsource(compiler_mod)
        assert "executor_dispatch" not in source
        assert "run_executor" not in source
        assert "external_executor" not in source
        assert "skill_install" not in source


class TestGoalNoAutomaticSkillInstallation:
    def test_goal_pipeline_does_not_trigger_skill_installation(self, tmp_path):
        """Goal pipeline must not trigger automatic skill installation."""
        import agent_runtime.goals.compiler as compiler_mod
        import inspect

        source = inspect.getsource(compiler_mod)
        assert "skill_install" not in source
        assert "install_skill" not in source
        assert "auto_install" not in source


class TestGoalAcceptanceIntegration:
    """End-to-end: full goal pipeline with all artifacts."""

    def test_full_pipeline_produces_all_expected_artifacts(self, tmp_path):
        """Full goal lifecycle creates all expected Project Brain files."""
        project = "TestIntegration"
        brain_dir = tmp_path / "projects" / project / "project_brain"

        action = parse_goal_command("/goal set Build a complete CLI application --project TestIntegration")
        compile_goal_set(action, tmp_path, project)
        compile_goal_plan(action, tmp_path, project)
        compile_goal_progress(action, tmp_path, project)
        validate_result = compile_goal_validate(action, tmp_path, project)
        report_result = compile_goal_report(action, tmp_path, project)

        # All stages should pass after full setup
        assert validate_result["status"] == "pass"
        assert report_result["verdict"] == "PASS"

        # Verify all key artifacts
        expected_files = [
            "goal_contract.yml",
            "mission_contract.yml",
            "workflow_plan.yml",
            "mainline_program.yml",
            "mainline_acceptance_contract.yml",
            "scenario_validation_plan.yml",
            "mainline_progress.yml",
            "mainline_completion_report.md",
            "next_actions.yml",
            "decision_log.yml",
            "acceptance_history.yml",
        ]
        for filename in expected_files:
            assert (brain_dir / filename).is_file(), f"Missing: {filename}"

    def test_acceptance_history_has_entries_for_all_actions(self, tmp_path):
        project = "TestIntegration"
        brain_dir = tmp_path / "projects" / project / "project_brain"

        action = parse_goal_command("/goal set Integration test")
        compile_goal_set(action, tmp_path, project)
        compile_goal_plan(action, tmp_path, project)
        compile_goal_progress(action, tmp_path, project)
        compile_goal_validate(action, tmp_path, project)
        compile_goal_report(action, tmp_path, project)

        import yaml
        hist = yaml.safe_load(
            (brain_dir / "acceptance_history.yml").read_text(encoding="utf-8")
        )
        entries = hist.get("entries", [])
        # Should have entries from set, plan, progress, validate, report
        assert len(entries) >= 5
