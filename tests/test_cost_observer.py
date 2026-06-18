from __future__ import annotations

from pathlib import Path
import sys

import yaml
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))
sys.modules.pop("atomic_io", None)

from cost_observer import cost_doctor, cost_status  # noqa: E402
from cost_tracker import append_cost_ledgers, usage_entry  # noqa: E402
from run_task import app  # noqa: E402


def _write_pricing(root: Path) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "model_pricing.yml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "currency": "USD",
                "models": {
                    "known-model": {
                        "input_per_1m_usd": 1.0,
                        "output_per_1m_usd": 2.0,
                        "pricing_confidence": "high",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_usage_entry_marks_source_and_accuracy(tmp_path: Path) -> None:
    _write_pricing(tmp_path)
    entry = usage_entry(
        "Demo",
        "task_cost",
        "Coder",
        "test-provider",
        "known-model",
        "completed",
        input_tokens=1_000_000,
        output_tokens=500_000,
        total_tokens=1_500_000,
        agentlab_root=tmp_path,
    )

    assert entry["usage_source"] == "provider_response"
    assert entry["cost_accuracy"] == "estimated"
    assert entry["estimated_cost"] == 2.0
    assert entry["pricing_confidence"] == "high"


def test_cost_status_summarizes_known_and_unknown_costs(tmp_path: Path) -> None:
    _write_pricing(tmp_path)
    project_root = tmp_path / "projects" / "Demo"
    run_dir = project_root / "runs" / "task_cost"
    run_dir.mkdir(parents=True)

    append_cost_ledgers(
        project_root,
        run_dir,
        usage_entry(
            "Demo",
            "task_cost",
            "Coder",
            "test-provider",
            "known-model",
            "completed",
            input_tokens=1_000_000,
            output_tokens=500_000,
            total_tokens=1_500_000,
            agentlab_root=tmp_path,
        ),
    )
    append_cost_ledgers(
        project_root,
        run_dir,
        usage_entry(
            "Demo",
            "task_cost",
            "ExternalIDE",
            "codex_plus_manual",
            "codex_plus_manual",
            "manual_logged",
            notes="subscription usage not visible",
            agentlab_root=tmp_path,
        ),
    )

    status = cost_status(tmp_path, "Demo", "task_cost")
    assert status["pricing_status"] == "partial"
    assert status["totals"]["known_cost_usd"] == 2.0
    assert status["totals"]["unknown_cost_events"] == 1
    assert status["by_agent"]["Coder"]["known_cost_usd"] == 2.0
    assert status["by_agent"]["ExternalIDE"]["unknown_cost_events"] == 1


def test_cost_doctor_warns_on_unknown_cost(tmp_path: Path) -> None:
    project_root = tmp_path / "projects" / "Demo"
    run_dir = project_root / "runs" / "task_unknown"
    run_dir.mkdir(parents=True)
    append_cost_ledgers(
        project_root,
        run_dir,
        usage_entry(
            "Demo",
            "task_unknown",
            "Researcher",
            "unknown-provider",
            "missing-model",
            "completed",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            agentlab_root=tmp_path,
        ),
    )

    report = cost_doctor(tmp_path, "Demo", "task_unknown")
    codes = {item["code"] for item in report["warnings"]}
    assert report["status"] == "warning"
    assert "unknown_cost" in codes


def test_cost_cli_commands_are_registered() -> None:
    runner = CliRunner()
    for cmd in ["cost-status", "cost-doctor"]:
        result = runner.invoke(app, [cmd, "--help"])
        assert result.exit_code == 0, result.output
