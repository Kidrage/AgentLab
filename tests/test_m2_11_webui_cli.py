import pytest
from typer.testing import CliRunner
from agent_runtime.run_task import app

runner = CliRunner()

def test_webui_cli_rejects_non_localhost():
    """Test that the CLI cleanly rejects non-localhost bindings."""
    result = runner.invoke(app, ["webui", "--host", "0.0.0.0"])
    assert result.exit_code == 1
    assert "M2-11 WebUI is local-only" in result.stdout

def test_webui_cli_rejects_ipv6_any():
    """Test that the CLI cleanly rejects :: bindings."""
    result = runner.invoke(app, ["webui", "--host", "::"])
    assert result.exit_code == 1
    assert "M2-11 WebUI is local-only" in result.stdout

def test_webui_cli_rejects_lan_ip():
    """Test that the CLI cleanly rejects LAN IP bindings."""
    result = runner.invoke(app, ["webui", "--host", "192.168.1.10"])
    assert result.exit_code == 1
    assert "M2-11 WebUI is local-only" in result.stdout

def test_webui_cli_help_is_available():
    """Test that the CLI accepts help path."""
    result = runner.invoke(app, ["webui", "--help"])
    assert result.exit_code == 0
    assert "Start the AgentLab Web User Interface" in result.stdout
