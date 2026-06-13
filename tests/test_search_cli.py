from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_search_cli_help_works() -> None:
    result = subprocess.run([sys.executable, "-m", "agent_runtime.search_cli", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "search-web" in result.stdout


def test_search_cli_mock_writes_artifacts(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "agent_runtime.search_cli", "--output-dir", str(tmp_path), "search-web", "AgentLab", "--mock"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert (tmp_path / "search_ledger.yml").exists()

