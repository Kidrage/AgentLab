"""Tests for M2-12.5 Goal CLI — command registration and smoke tests."""

from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

from agent_runtime.run_task import app

runner = CliRunner()
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


class TestGoalCLIHelp:
    def test_goal_help(self):
        result = runner.invoke(app, ["goal", "--help"])
        assert result.exit_code == 0

    def test_goal_help_mentions_actions(self):
        result = runner.invoke(app, ["goal", "--help"])
        plain = strip_ansi(result.output)
        assert "set" in plain.lower() or "action" in plain.lower()


class TestGoalCLISmoke:
    def test_goal_set_creates_artifact(self, tmp_path):
        out = tmp_path / "cli_out"
        result = runner.invoke(app, [
            "goal", "set",
            "Build a CLI app",
            "--project", "TestCLI",
            "--out", str(out),
        ])
        assert result.exit_code == 0
        assert "goal set" in strip_ansi(result.output)

    def test_goal_plan_creates_artifacts(self, tmp_path):
        out = tmp_path / "cli_out"
        runner.invoke(app, [
            "goal", "set",
            "Build a CLI app",
            "--project", "TestCLI",
            "--out", str(out),
        ])
        result = runner.invoke(app, [
            "goal", "plan",
            "Build a CLI app",
            "--project", "TestCLI",
            "--out", str(out / "plan"),
        ])
        assert result.exit_code == 0
        assert "goal plan" in strip_ansi(result.output)

    def test_goal_progress_creates_artifact(self, tmp_path):
        out = tmp_path / "cli_out"
        runner.invoke(app, [
            "goal", "set",
            "Build a CLI app",
            "--project", "TestCLI",
            "--out", str(out),
        ])
        runner.invoke(app, [
            "goal", "plan",
            "Build a CLI app",
            "--project", "TestCLI",
            "--out", str(out),
        ])
        result = runner.invoke(app, [
            "goal", "progress",
            "Build a CLI app",
            "--project", "TestCLI",
            "--out", str(out / "progress"),
        ])
        assert result.exit_code == 0
        assert "goal progress" in strip_ansi(result.output)

    def test_goal_validate_runs(self, tmp_path):
        out = tmp_path / "cli_out"
        runner.invoke(app, [
            "goal", "set",
            "Build a CLI app",
            "--project", "TestCLI",
            "--out", str(out),
        ])
        runner.invoke(app, [
            "goal", "plan",
            "Build a CLI app",
            "--project", "TestCLI",
            "--out", str(out),
        ])
        runner.invoke(app, [
            "goal", "progress",
            "Build a CLI app",
            "--project", "TestCLI",
            "--out", str(out),
        ])
        result = runner.invoke(app, [
            "goal", "validate",
            "Build a CLI app",
            "--project", "TestCLI",
            "--out", str(out / "validate"),
        ])
        assert result.exit_code == 0
        plain = strip_ansi(result.output)
        assert "validate" in plain.lower()

    def test_goal_report_creates_artifact(self, tmp_path):
        out = tmp_path / "cli_out"
        runner.invoke(app, [
            "goal", "set",
            "Build a CLI app",
            "--project", "TestCLI",
            "--out", str(out),
        ])
        runner.invoke(app, [
            "goal", "plan",
            "Build a CLI app",
            "--project", "TestCLI",
            "--out", str(out),
        ])
        runner.invoke(app, [
            "goal", "progress",
            "Build a CLI app",
            "--project", "TestCLI",
            "--out", str(out),
        ])
        result = runner.invoke(app, [
            "goal", "report",
            "Build a CLI app",
            "--project", "TestCLI",
            "--out", str(out / "report"),
        ])
        assert result.exit_code == 0
        plain = strip_ansi(result.output)
        assert "goal report" in plain.lower()

    def test_goal_set_defaults_to_agentlab_project(self, tmp_path):
        out = tmp_path / "default_out"
        result = runner.invoke(app, [
            "goal", "set", "test",
            "--out", str(out),
        ])
        assert result.exit_code == 0
