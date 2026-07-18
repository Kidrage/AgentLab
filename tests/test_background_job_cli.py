from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_background_job_cli_is_registered() -> None:
    result = subprocess.run(
        [str(ROOT / "agentlab.sh"), "background-job", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "create-crown" in result.stdout
    assert "tick" in result.stdout
    assert "pause" in result.stdout
    assert "resume" in result.stdout
    assert "retry-blocked" in result.stdout
    assert "run" in result.stdout
