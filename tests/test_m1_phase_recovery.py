from __future__ import annotations

from pathlib import Path
import sys
import yaml
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.recovery.phase_recovery import recover_failed_phase
from run_task import app


def test_recover_failed_phase(tmp_path: Path):
    acceptance_path = tmp_path / "acceptance.yml"
    acceptance_data = {
        "phase_id": "phase_001",
        "verdict": "FAIL",
        "missing_evidence": ["test_evidence.yml"],
    }
    acceptance_path.write_text(yaml.safe_dump(acceptance_data), encoding="utf-8")

    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    history_path = brain_dir / "acceptance_history.yml"
    yaml.dump({"entries": []}, history_path.open("w", encoding="utf-8"))

    out_dir = tmp_path / "out"

    res = recover_failed_phase(
        project_brain_dir=brain_dir,
        phase_id="phase_001",
        acceptance_result_path=acceptance_path,
        out_dir=out_dir,
    )

    assert res["phase_id"] == "phase_001"
    assert res["failure_reason"] == "evidence_missing"
    assert res["recommended_next_action"] == "ask_user"
    assert (out_dir / "replan_plan.yml").is_file()


def test_phase_replan_cli(tmp_path: Path):
    runner = CliRunner()

    acceptance_path = tmp_path / "acceptance.yml"
    acceptance_data = {
        "phase_id": "phase_001",
        "verdict": "FAIL",
        "test_results": {"passed": False},
    }
    acceptance_path.write_text(yaml.safe_dump(acceptance_data), encoding="utf-8")

    out_dir = tmp_path / "out"

    result = runner.invoke(
        app,
        [
            "phase-replan",
            "--project", "TestProject",
            "--phase", "phase_001",
            "--acceptance", str(acceptance_path),
            "--out", str(out_dir),
        ]
    )

    assert result.exit_code == 0
    assert "Phase replan generated successfully" in result.output
    assert (out_dir / "replan_plan.yml").is_file()
    assert (out_dir.parent / "brain" / "next_actions.yml").is_file()
