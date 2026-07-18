from __future__ import annotations

import sys
from pathlib import Path

import yaml
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from run_task import app  # noqa: E402


def test_prepare_frugal_budget_persists_and_stdout_is_summary(
    isolated_agentlab_root: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENTLAB_ROOT", str(isolated_agentlab_root))
    task_id = "task_prepare_frugal_summary_regression"
    run_dir = isolated_agentlab_root / "projects" / "AgentLab" / "runs" / task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "user_request.md").write_text(
        "Implement a small AgentLab UI code change and keep this run low cost.",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "prepare",
            "--project",
            "AgentLab",
            "--task-id",
            task_id,
            "--budget",
            "frugal",
            "--write-plan",
            "--overwrite-plan",
        ],
    )

    assert result.exit_code == 0, result.output
    plan = yaml.safe_load((run_dir / "workflow_plan.yml").read_text(encoding="utf-8"))
    assert plan["budget_mode"] == "frugal"
    assert "Workflow plan summary" in result.output
    assert "included_agents" not in result.output
    assert "harness_policy" not in result.output
    assert len(result.output) < 8000
