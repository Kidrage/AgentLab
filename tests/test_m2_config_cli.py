"""M2-5 Config Center — CLI contract tests.

Tests that the CLI commands produce expected output contracts:
config-list, config-get, config-diff, config-validate, config-profiles.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
RUN_TASK = str(ROOT / "agent_runtime" / "run_task.py")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PYTHON, RUN_TASK, "config", *args],
        capture_output=True,
        text=True,
        timeout=30,
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT)},
    )


# ── config-list ──────────────────────────────────────────────────────────


def test_config_list_contract() -> None:
    result = _run("config-list", "--limit", "100")
    assert result.returncode == 0, f"stderr: {result.stderr}"
    output = result.stdout
    assert "Key" in output
    assert "Value" in output
    assert "Source Layer" in output
    assert "Overridden" in output
    assert "global_defaults" in output


def test_config_list_with_project_flag() -> None:
    result = _run("config-list", "--project", "AgentLab", "--limit", "100")
    assert result.returncode == 0


# ── config-get ───────────────────────────────────────────────────────────


def test_config_get_contract() -> None:
    result = _run("config-get", "--key", "routing_policy.default_budget")
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "routing_policy.default_budget" in result.stdout
    assert "balanced" in result.stdout
    assert "Layer:" in result.stdout
    assert "Overridden:" in result.stdout
    assert "Is Secret:" in result.stdout


def test_config_get_nonexistent_key_exits_nonzero() -> None:
    result = _run("config-get", "--key", "nonexistent.ghost.key")
    assert result.returncode != 0


def test_config_get_with_project_flag() -> None:
    result = _run("config-get", "--key", "routing_policy.default_budget", "--project", "AgentLab")
    assert result.returncode == 0


# ── config-diff ──────────────────────────────────────────────────────────


def test_config_diff_contract() -> None:
    # AgentLab is a real project with project_config.yml
    result = _run("config-diff", "--project", "AgentLab")
    assert result.returncode == 0, f"stderr: {result.stderr}"
    output = result.stdout
    assert "Config Diff" in output
    assert "base" in output.lower()
    assert "AgentLab" in output


def test_config_diff_requires_project_flag() -> None:
    result = _run("config-diff")
    assert result.returncode != 0


# ── config-validate ──────────────────────────────────────────────────────


def test_config_validate_exits_and_reports() -> None:
    result = _run("config-validate")
    # May pass or fail depending on whether required keys exist
    output = result.stdout + result.stderr
    assert "valid" in output.lower() or "error" in output.lower()


def test_config_validate_with_project() -> None:
    result = _run("config-validate", "--project", "AgentLab")
    output = result.stdout + result.stderr
    # Should run without crashing
    assert result.returncode in (0, 1)


# ── config-profiles ──────────────────────────────────────────────────────


def test_config_profiles_contract() -> None:
    result = _run("config-profiles")
    assert result.returncode == 0
    output = result.stdout
    assert "dev" in output
    assert "prod" in output
    assert "frugal" in output
    assert "max_quality" in output
    assert "Development profile" in output
    assert "Production profile" in output


# ── Help text ────────────────────────────────────────────────────────────


def test_config_help_lists_all_subcommands() -> None:
    result = _run("--help")
    assert "config-list" in result.stdout
    assert "config-get" in result.stdout
    assert "config-diff" in result.stdout
    assert "config-validate" in result.stdout
    assert "config-profiles" in result.stdout
