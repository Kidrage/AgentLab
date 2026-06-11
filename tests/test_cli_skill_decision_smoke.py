from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

import cost_tracker
import run_task
from feedback_manager import create_decision_card, load_pending_decision_cards


def _write_pricing(root: Path) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "model_pricing.yml").write_text(
        yaml.safe_dump({
            "version": 1,
            "currency": "USD",
            "models": {
                "deepseek/deepseek-v4-pro": {
                    "input_per_1m": 1.0,
                    "output_per_1m": 2.0,
                },
            },
        }, sort_keys=False),
        encoding="utf-8",
    )
    cost_tracker._PRICE_CACHE = None
    cost_tracker._PRICE_ROOT = None


@pytest.mark.parametrize(
    "command",
    [
        "skill-list",
        "skill-request",
        "skill-approve",
        "skill-reject",
        "skill-stage",
        "skill-validate",
        "skill-promote",
        "skill-retire",
        "skill-match",
        "skill-inject",
        "skill-usage",
        "learning-review",
        "skill-candidates",
        "skill-candidate-approve",
        "skill-candidate-reject",
        "decision-list",
        "decision-approve",
        "decision-reject",
        "decision-resume",
        "watchdog-scan",
        "watchdog-status",
        "webhook-test",
        "webhook-status",
        "webhook-redeliver",
    ],
)
def test_task2_task3_cli_help_commands_exist(command: str) -> None:
    runner = CliRunner()
    result = runner.invoke(run_task.app, [command, "--help"])
    assert result.exit_code == 0, result.output
    assert "Usage:" in result.output


def test_skill_lifecycle_cli_smoke(tmp_path: Path) -> None:
    _write_pricing(tmp_path)
    runner = CliRunner()

    with patch.object(run_task, "runtime_context", return_value=(tmp_path, "Demo")):
        result = runner.invoke(
            run_task.app,
            [
                "skill-request",
                "--project", "Demo",
                "--name", "demo-skill",
                "--source", "manual://demo",
                "--purpose", "CLI smoke test skill.",
            ],
        )
        assert result.exit_code == 0, result.output

        request_files = list((tmp_path / "projects" / "Demo" / "skill_requests").glob("*.yml"))
        assert len(request_files) == 1
        request = yaml.safe_load(request_files[0].read_text(encoding="utf-8"))
        request_id = request["id"]

        for args in [
            ["skill-approve", "--project", "Demo", "--request-id", request_id],
            ["skill-stage", "--project", "Demo", "--request-id", request_id],
        ]:
            result = runner.invoke(run_task.app, args)
            assert result.exit_code == 0, result.output

        staged_request = yaml.safe_load(request_files[0].read_text(encoding="utf-8"))
        skill_id = staged_request["skill_id"]

        for args in [
            ["skill-validate", "--skill-id", skill_id, "--fake-sandbox"],
            ["skill-promote", "--skill-id", skill_id],
            ["skill-retire", "--skill-id", skill_id, "--reason", "CLI smoke complete."],
        ]:
            result = runner.invoke(run_task.app, args)
            assert result.exit_code == 0, result.output

    active_dir = tmp_path / "skills" / "active" / skill_id
    retired_dir = tmp_path / "skills" / "retired" / skill_id
    assert active_dir.exists()
    assert retired_dir.exists()
    registry = yaml.safe_load((tmp_path / "skills" / "registry.yml").read_text(encoding="utf-8"))
    assert any(item["skill_id"] == skill_id for item in registry["retired_skills"])


def test_decision_cli_approval_smoke(tmp_path: Path) -> None:
    runner = CliRunner()
    task_id = "task_0001_cli-decision"
    run_dir = tmp_path / "projects" / "Demo" / "runs" / task_id
    run_dir.mkdir(parents=True)
    (run_dir / "USER_DECISION_REQUIRED.md").write_text("# User Decision Required\n", encoding="utf-8")
    card, _path = create_decision_card(
        run_dir,
        task_id=task_id,
        card_type="user_decision",
        title="Approval required",
        reason="CLI smoke decision.",
        stage="blocked_user_decision",
        options=[
            {"id": "approve_resume", "label": "Approve resume", "risk": "medium"},
            {"id": "stop_task", "label": "Stop task", "risk": "none"},
        ],
    )

    with patch.object(run_task, "runtime_context", return_value=(tmp_path, "Demo")):
        result = runner.invoke(run_task.app, ["decision-list", "--project", "Demo", "--task-id", task_id])
        assert result.exit_code == 0, result.output
        assert "'count': 1" in result.output

        result = runner.invoke(
            run_task.app,
            [
                "decision-approve",
                card["id"],
                "--project", "Demo",
                "--task-id", task_id,
                "--option", "approve_resume",
            ],
        )
        assert result.exit_code == 0, result.output

    assert load_pending_decision_cards(run_dir) == []
    assert not (run_dir / "USER_DECISION_REQUIRED.md").exists()
    resolved = yaml.safe_load((run_dir / "decision_cards" / f"{card['id']}.yml").read_text(encoding="utf-8"))
    assert resolved["status"] == "approved"
    assert resolved["selected_option"] == "approve_resume"
