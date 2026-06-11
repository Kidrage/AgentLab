"""P0 Fix 1: Verify all documented CLI commands exist and --help does not crash."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from run_task import app  # noqa: E402

runner = CliRunner()

# Commands that must exist per the task spec
REQUIRED_COMMANDS = (
    "skill-status",
    "skill-request",
    "skill-list",
    "skill-approve",
    "skill-reject",
    "skill-stage",
    "skill-validate",
    "skill-promote",
    "skill-retire",
    "skill-match",
    "skill-inject",
    "skill-usage",
    "learning-review",
    "skill-candidates",
    "skill-candidate-approve",
    "skill-candidate-reject",
    "feedback-status",
    "task-event",
    "decision-list",
    "decision-approve",
    "decision-reject",
    "decision-resume",
    "watchdog-scan",
    "watchdog-status",
    "webhook-test",
    "webhook-status",
    "webhook-redeliver",
    "skill-import-url",
    # Core task commands
    "init-task",
    "prepare",
    "status",
    "run-pipeline",
    "run-agent",
)


def _registered_commands() -> set[str]:
    """Extract command names from the Typer app."""
    return {cmd.name for cmd in app.registered_commands if cmd.name}


def test_required_commands_registered() -> None:
    """Every documented command must be registered in the Typer app."""
    registered = _registered_commands()
    for cmd_name in REQUIRED_COMMANDS:
        assert cmd_name in registered, f"Missing CLI command: {cmd_name}"


def test_top_level_help_does_not_crash() -> None:
    """`python -m agent_runtime.run_task --help` must succeed."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, f"--help crashed: {result.output[:500]}"


@pytest.mark.parametrize("cmd_name", sorted(REQUIRED_COMMANDS))
def test_command_help_does_not_crash(cmd_name: str) -> None:
    """Each command's --help must not crash."""
    result = runner.invoke(app, [cmd_name, "--help"])
    assert result.exit_code == 0, (
        f"Command '{cmd_name} --help' returned exit_code={result.exit_code}. "
        f"Output: {result.output[:500]}"
    )


def test_agentlab_sh_help_does_not_crash() -> None:
    """`./agentlab.sh --help` must exit successfully."""
    import subprocess
    sh_path = ROOT / "agentlab.sh"
    if not sh_path.exists():
        pytest.skip("agentlab.sh not found at repo root")
    result = subprocess.run(
        ["bash", str(sh_path), "--help"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"agentlab.sh --help failed: {result.stderr[:500]}"