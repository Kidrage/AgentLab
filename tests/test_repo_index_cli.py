from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_repo_index_cli_help_works() -> None:
    result = subprocess.run([sys.executable, "-m", "agent_runtime.repo_index_cli", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "status" in result.stdout


def test_repo_index_status_writes_artifacts(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, "-m", "agent_runtime.repo_index_cli", "--output-dir", str(out), "status", "--repo-path", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert (out / "repo_index_ledger.yml").exists()


def test_real_index_requires_approval(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "agent_runtime.repo_index_cli", "--output-dir", str(tmp_path / "out"), "index", "--repo-path", str(tmp_path), "--execute"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1

