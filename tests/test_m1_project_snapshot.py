from __future__ import annotations

from pathlib import Path
import sys
import yaml
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.program_manager.context_compressor import build_project_snapshot, write_snapshot
from run_task import app


def test_build_and_write_snapshot(tmp_path: Path):
    # Setup mock brain files
    (tmp_path / "project_brief.yml").write_text(yaml.dump({"project_id": "test_proj"}), encoding="utf-8")
    (tmp_path / "roadmap.yml").write_text(yaml.dump({"milestones": []}), encoding="utf-8")
    (tmp_path / "current_phase.yml").write_text(yaml.dump({"phase_id": "phase_01"}), encoding="utf-8")

    # Build snapshot
    snapshot = build_project_snapshot(tmp_path)
    assert snapshot["project_brief"]["project_id"] == "test_proj"
    assert snapshot["roadmap"]["milestones"] == []
    assert snapshot["current_phase"]["phase_id"] == "phase_01"

    # Write snapshot
    out_file = write_snapshot(tmp_path, "001", snapshot)
    assert out_file.is_file()
    assert (tmp_path / "context_snapshots" / "snapshot_001.yml").is_file()
    assert (tmp_path / "snapshots" / "snapshot_001.yml").is_file()

    # Load and verify written content
    loaded = yaml.safe_load(out_file.read_text(encoding="utf-8"))
    assert loaded["current_phase"]["phase_id"] == "phase_01"


def test_project_compress_and_snapshot_cli(tmp_path: Path):
    runner = CliRunner()

    # 1. Test project-summarize-phase CLI
    sum_res = runner.invoke(
        app,
        [
            "project-summarize-phase",
            "--project", "DemoProject",
            "--phase", "phase_001",
        ]
    )
    assert sum_res.exit_code == 0
    assert "Phase summary written successfully" in sum_res.output

    # 2. Test project-snapshot CLI
    snap_res = runner.invoke(
        app,
        [
            "project-snapshot",
            "--project", "DemoProject",
            "--name", "002",
        ]
    )
    assert snap_res.exit_code == 0
    assert "Project snapshot generated successfully" in snap_res.output
