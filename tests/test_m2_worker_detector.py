"""Tests for worker detection and probing."""

import os
from unittest.mock import patch, MagicMock
from agent_runtime.workers.command_probe import probe_command
from agent_runtime.workers.version_probe import probe_version
from agent_runtime.workers.auth_probe import probe_auth
from agent_runtime.workers.health_probe import probe_health
from agent_runtime.workers.detector import scan_workers

def test_probe_command():
    with patch("shutil.which", return_value="/usr/bin/git"):
        assert probe_command("git") is True

    with patch("shutil.which", return_value=None):
        assert probe_command("nonexistent_binary") is False

def test_probe_version_success():
    mock_run = MagicMock()
    mock_run.returncode = 0
    mock_run.stdout = "git version 2.34.1"
    mock_run.stderr = ""

    with patch("subprocess.run", return_value=mock_run):
        assert probe_version("git") == "2.34.1"

def test_probe_version_failure():
    with patch("subprocess.run", side_effect=Exception("error")):
        assert probe_version("any_cmd") is None

def test_probe_auth_yes():
    # Deterministic tools always return yes
    assert probe_auth("git") == "yes"
    assert probe_auth("rg") == "yes"

    # API key present in env
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-123456"}):
        assert probe_auth("claude") == "yes"

def test_probe_auth_no():
    with patch.dict(os.environ, {}, clear=True):
        assert probe_auth("claude") == "no"

def test_probe_health():
    with patch("agent_runtime.workers.health_probe.probe_command", return_value=True), \
         patch("agent_runtime.workers.health_probe.probe_auth", return_value="yes"):
        assert probe_health("git", "git") == "healthy"

    with patch("agent_runtime.workers.health_probe.probe_command", return_value=False):
        assert probe_health("git", "git") == "unhealthy"

def test_scan_workers():
    with patch("agent_runtime.workers.detector.probe_command", return_value=True), \
         patch("agent_runtime.workers.detector.probe_version", return_value="1.0.0"), \
         patch("agent_runtime.workers.detector.probe_auth", return_value="yes"):
        cards = scan_workers()
        assert len(cards) > 0
        for card in cards:
            assert card.installed is True
            assert card.version == "1.0.0"
            assert card.authenticated == "yes"

            # High risk workers must require approval
            if card.risk_level == "high":
                assert card.approval_required is True
