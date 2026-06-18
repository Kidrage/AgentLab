from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_command(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    """Run a repository-local command for S0 smoke tests."""

    return subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_s0_stable_baseline_script_returns_pass() -> None:
    result = _run_command(
        [sys.executable, "scripts/s0_stable_baseline_check.py"],
        timeout=60,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "PASS"
    assert payload["checks"]


def test_agentlab_cli_help_smoke() -> None:
    for args in (["--help"], ["run-pipeline", "--help"]):
        result = _run_command(
            [str(ROOT / "agentlab.sh"), *args],
            timeout=30,
        )
        assert result.returncode == 0, result.stderr or result.stdout