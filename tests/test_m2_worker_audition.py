from __future__ import annotations

from pathlib import Path
import pytest
from typer.testing import CliRunner

from agent_runtime.workers.sandbox import AuditionSandbox
from agent_runtime.workers.audition import run_single_audition, run_all_auditions
from agent_runtime.run_task import app


def test_audition_sandbox_creation() -> None:
    with AuditionSandbox() as sandbox:
        assert sandbox.path is not None
        assert sandbox.path.exists()
        
        repo_dir = sandbox.path / "mock_repo"
        assert repo_dir.exists()
        assert (repo_dir / "main.py").exists()
        assert (repo_dir / "tests" / "test_main.py").exists()


def test_mock_audition_runner(tmp_path: Path) -> None:
    # Run a mock single audition
    res = run_single_audition(
        worker_id="claude_code",
        role="Coder",
        level="standard",
        real_execute=False,
        project_root=tmp_path
    )
    
    assert res["worker_id"] == "claude_code"
    assert res["role"] == "Coder"
    assert res["verdict"] == "pass"
    assert "scores" in res
    assert res["scores"]["role_fit_score"] > 0.0

    # Run all auditions in mock mode
    results = run_all_auditions(
        level="quick",
        real_execute=False,
        project_root=tmp_path
    )
    assert len(results) > 0
    assert all(r["verdict"] == "pass" for r in results)


def test_audition_cli_smoke() -> None:
    runner = CliRunner()
    
    # 1. Test worker-audition single
    result1 = runner.invoke(app, ["worker-audition", "--worker", "claude_code", "--role", "Coder", "--level", "quick"])
    assert result1.exit_code == 0
    assert "claude_code" in result1.stdout
    assert "PASS" in result1.stdout

    # 2. Test worker-scorecard
    result2 = runner.invoke(app, ["worker-scorecard"])
    assert result2.exit_code == 0
    assert "claude_code" in result2.stdout
    assert "coder" in result2.stdout
