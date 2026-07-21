from __future__ import annotations

import os
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
        env={**os.environ, "COLUMNS": "180"},
    )
    assert result.returncode == 0, result.stderr
    assert "create-crown" in result.stdout
    assert "tick" in result.stdout
    assert "pause" in result.stdout
    assert "resume" in result.stdout
    assert "retry-blocked" in result.stdout
    assert "run" in result.stdout


def test_create_crown_cli_exposes_parent_and_rag_cadence_contract() -> None:
    result = subprocess.run(
        [str(ROOT / "agentlab.sh"), "background-job", "create-crown", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "COLUMNS": "180"},
    )
    assert result.returncode == 0, result.stderr
    assert "--parent-task-id" in result.stdout
    assert "--continuity-checkpoint-cadence" in result.stdout
    assert "--knowledge-contract-required" in result.stdout
