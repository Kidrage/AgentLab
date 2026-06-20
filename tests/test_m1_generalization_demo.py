from __future__ import annotations

from pathlib import Path
import sys
import yaml
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.evaluation.m1_demo_runner import run_all_demos
from run_task import app


def test_m1_demo_runner(tmp_path: Path):
    out_dir = tmp_path / "out"
    summary = run_all_demos(tmp_path, out_dir)
    
    assert summary["suite"] == "m1_generalization_demo"
    assert summary["verdict"] == "PASS"
    assert summary["total"] == 4
    assert summary["passed"] == 4
    
    # Check output report
    report_file = out_dir / "M1_GENERALIZATION_DEMO_REPORT.md"
    assert report_file.is_file()
    assert "# AgentLab M1 Generalization Demo Suite Report" in report_file.read_text(encoding="utf-8")


def test_m1_demo_cli(tmp_path: Path):
    runner = CliRunner()
    out_dir = tmp_path / "out"
    
    res = runner.invoke(
        app,
        [
            "m1-demo",
            "--suite", "all",
            "--out", str(out_dir),
        ]
    )
    
    assert res.exit_code == 0
    assert "M1 generalization demo suite finished with verdict: PASS" in res.output
