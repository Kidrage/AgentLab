"""Tests for worker CLI commands."""

import sys
from pathlib import Path
from unittest.mock import patch
import pytest
import yaml
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

import run_task

def test_worker_scan_cli():
    runner = CliRunner()
    with patch("agent_runtime.workers.registry.WorkerRegistry.scan_and_register") as mock_scan:
        res = runner.invoke(run_task.app, ["worker-scan"])
        assert res.exit_code == 0
        assert "Scanned system and cached workers" in res.output
        mock_scan.assert_called_once()

def test_worker_list_cli():
    runner = CliRunner()
    with patch("agent_runtime.workers.registry.WorkerRegistry.load_from_cache", return_value=True), \
         patch("agent_runtime.workers.registry.WorkerRegistry.list_workers", return_value=[]):
        res = runner.invoke(run_task.app, ["worker-list"])
        assert res.exit_code == 0

def test_worker_inspect_cli_not_found():
    runner = CliRunner()
    with patch("agent_runtime.workers.registry.WorkerRegistry.load_from_cache", return_value=True), \
         patch("agent_runtime.workers.registry.WorkerRegistry.get_worker", return_value=None):
        res = runner.invoke(run_task.app, ["worker-inspect", "--worker", "nonexistent"])
        assert res.exit_code == 1
        assert "not found" in res.output

def test_worker_contracts_cli():
    runner = CliRunner()
    res = runner.invoke(run_task.app, ["worker-contracts"])
    assert res.exit_code == 0
    data = yaml.safe_load(res.output)
    assert "hermes" in data
    assert "claude" in data
