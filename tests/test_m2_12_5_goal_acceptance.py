"""Tests for M2-12.5 Goal Acceptance — safety tripwires and end-to-end behavior.

These tests prove that the goal pipeline:
- Does not call subprocess
- Does not open network sockets
- Does not dispatch external executors
- Does not trigger automatic skill installation
"""

import pytest

from agent_runtime.goals.action_schema import GoalActionSchema
from agent_runtime.goals.compiler import compile_goal_set, compile_goal_plan
from agent_runtime.goals.progress import compile_goal_progress
from agent_runtime.goals.validation import compile_goal_validate
from agent_runtime.goals.report import compile_goal_report


class TestGoalSafetyTripwires:
    def test_goal_compiler_does_not_call_subprocess(self, monkeypatch, tmp_path):
        import subprocess

        def fail(*args, **kwargs):
            raise AssertionError("goal compiler must not call subprocess")

        monkeypatch.setattr(subprocess, "run", fail)
        monkeypatch.setattr(subprocess, "call", fail)

        action = GoalActionSchema(command="/goal", action="set", text="Test",
                                  project="TestSafety")
        result = compile_goal_set(action, tmp_path)
        assert result.status == "ok"

    def test_goal_plan_does_not_call_subprocess(self, monkeypatch, tmp_path):
        import subprocess

        def fail(*args, **kwargs):
            raise AssertionError("goal plan must not call subprocess")

        monkeypatch.setattr(subprocess, "run", fail)
        action_set = GoalActionSchema(command="/goal", action="set", text="Test",
                                      project="TestSafety")
        compile_goal_set(action_set, tmp_path)
        action = GoalActionSchema(action="plan", project="TestSafety")
        result = compile_goal_plan(action, tmp_path)
        assert result.status == "ok"

    def test_goal_progress_does_not_call_subprocess(self, monkeypatch, tmp_path):
        import subprocess

        def fail(*args, **kwargs):
            raise AssertionError("goal progress must not call subprocess")

        monkeypatch.setattr(subprocess, "run", fail)
        action_set = GoalActionSchema(command="/goal", action="set", text="Test",
                                      project="TestSafety")
        compile_goal_set(action_set, tmp_path)
        compile_goal_plan(GoalActionSchema(action="plan", project="TestSafety"), tmp_path)
        result = compile_goal_progress(GoalActionSchema(action="progress", project="TestSafety"),
                                       tmp_path)
        assert result.status == "ok"

    def test_goal_validate_does_not_call_subprocess(self, monkeypatch, tmp_path):
        import subprocess

        def fail(*args, **kwargs):
            raise AssertionError("goal validate must not call subprocess")

        monkeypatch.setattr(subprocess, "run", fail)
        action_set = GoalActionSchema(command="/goal", action="set", text="Test",
                                      project="TestSafety")
        compile_goal_set(action_set, tmp_path)
        compile_goal_plan(GoalActionSchema(action="plan", project="TestSafety"), tmp_path)
        compile_goal_progress(GoalActionSchema(action="progress", project="TestSafety"),
                              tmp_path)
        result = compile_goal_validate(GoalActionSchema(action="validate", project="TestSafety"),
                                       tmp_path)
        assert result.status in ("ok", "blocked", "pass")

    def test_goal_report_does_not_call_subprocess(self, monkeypatch, tmp_path):
        import subprocess

        def fail(*args, **kwargs):
            raise AssertionError("goal report must not call subprocess")

        monkeypatch.setattr(subprocess, "run", fail)
        action_set = GoalActionSchema(command="/goal", action="set", text="Test",
                                      project="TestSafety")
        compile_goal_set(action_set, tmp_path)
        compile_goal_plan(GoalActionSchema(action="plan", project="TestSafety"), tmp_path)
        compile_goal_progress(GoalActionSchema(action="progress", project="TestSafety"),
                              tmp_path)
        result = compile_goal_report(GoalActionSchema(action="report", project="TestSafety"),
                                     tmp_path)
        assert result.status == "ok"


class TestGoalNetworkSafety:
    def test_goal_pipeline_does_not_use_requests(self, monkeypatch, tmp_path):
        import builtins

        original_import = builtins.__import__

        def guard_import(name, *args, **kwargs):
            if name in ("requests", "urllib.request", "urllib3"):
                raise AssertionError(f"goal pipeline must not import {name}")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", guard_import, raising=False)

        action = GoalActionSchema(command="/goal", action="set", text="Test",
                                  project="TestNet")
        compile_goal_set(action, tmp_path)
        compile_goal_plan(GoalActionSchema(action="plan", project="TestNet"), tmp_path)
        compile_goal_progress(GoalActionSchema(action="progress", project="TestNet"), tmp_path)
        compile_goal_validate(GoalActionSchema(action="validate", project="TestNet"), tmp_path)
        compile_goal_report(GoalActionSchema(action="report", project="TestNet"), tmp_path)


class TestGoalNoExternalDispatch:
    def test_goal_pipeline_no_executor_dispatch(self):
        import inspect
        from agent_runtime.goals import compiler as compiler_mod

        source = inspect.getsource(compiler_mod)
        assert "executor_dispatch" not in source
        assert "run_executor" not in source
        assert "external_executor" not in source

    def test_goal_pipeline_no_auto_skill_install(self):
        import inspect
        from agent_runtime.goals import compiler as compiler_mod

        source = inspect.getsource(compiler_mod)
        assert "skill_install" not in source
        assert "install_skill" not in source
        assert "auto_install" not in source


class TestGoalAcceptanceIntegration:
    def test_full_pipeline_produces_all_expected_artifacts(self, tmp_path):
        project = "TestIntegration"
        action_set = GoalActionSchema(command="/goal", action="set",
                                      text="Build a CLI app", project=project)
        compile_goal_set(action_set, tmp_path)
        compile_goal_plan(GoalActionSchema(action="plan", project=project), tmp_path)
        compile_goal_progress(GoalActionSchema(action="progress", project=project), tmp_path)

        validate_result = compile_goal_validate(
            GoalActionSchema(action="validate", project=project), tmp_path)
        assert validate_result.status in ("ok", "pass")

        report_result = compile_goal_report(
            GoalActionSchema(action="report", project=project), tmp_path)
        assert report_result.status == "ok"

        brain_dir = tmp_path / "projects" / project / "project_brain"
        expected = [
            "goal_contract.yml",
            "mission_contract.yml",
            "workflow_plan.yml",
            "mainline_program.yml",
            "mainline_acceptance_contract.yml",
            "scenario_validation_plan.yml",
            "mainline_progress.yml",
            "mainline_completion_report.md",
        ]
        for filename in expected:
            assert (brain_dir / filename).is_file(), f"Missing: {filename}"

    def test_acceptance_history_has_entries(self, tmp_path):
        project = "TestIntegration"
        action_set = GoalActionSchema(command="/goal", action="set",
                                      text="Integration test", project=project)
        compile_goal_set(action_set, tmp_path)
        compile_goal_plan(GoalActionSchema(action="plan", project=project), tmp_path)
        compile_goal_progress(GoalActionSchema(action="progress", project=project), tmp_path)
        compile_goal_validate(GoalActionSchema(action="validate", project=project), tmp_path)
        compile_goal_report(GoalActionSchema(action="report", project=project), tmp_path)

        import yaml
        brain_dir = tmp_path / "projects" / project / "project_brain"
        hist = yaml.safe_load(
            (brain_dir / "acceptance_history.yml").read_text(encoding="utf-8"))
        items = hist.get("items", [])
        assert len(items) >= 4
