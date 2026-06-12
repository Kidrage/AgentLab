"""P0 Fix 1: Verify all documented CLI commands exist and --help does not crash."""

from __future__ import annotations

import sys
import re
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


def _canonical_external_skill_urls() -> dict[str, str]:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_match = re.search(
        r"https://raw\.githubusercontent\.com/openclaw/skills/main/skills/killerapp/agentskills-io/SKILL\.md",
        readme_text,
    )
    assert readme_match, "README.md must document the canonical external skill smoke URL"

    policy = yaml.safe_load(
        (ROOT / "config" / "external_skill_import_policy.yml").read_text(encoding="utf-8")
    ) or {}
    policy_urls = policy.get("allowed_url_prefixes") or []
    assert policy_urls, "external_skill_import_policy.yml must allow a canonical URL"

    live_text = (ROOT / "tests" / "test_external_skill_importer_live.py").read_text(encoding="utf-8")
    live_match = re.search(r'LIVE_URL\s*=\s*"([^"]+)"', live_text)
    assert live_match, "test_external_skill_importer_live.py must define LIVE_URL"

    return {
        "readme": readme_match.group(0),
        "policy": policy_urls[0],
        "live_test": live_match.group(1),
    }


def test_skill_import_url_documented_and_url_contract_matches() -> None:
    """README, policy, and live smoke test must share the same canonical URL."""
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "skill-import-url" in readme_text

    urls = _canonical_external_skill_urls()
    assert urls["readme"] == urls["policy"] == urls["live_test"]
