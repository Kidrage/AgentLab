from pathlib import Path

from typer.testing import CliRunner

from agent_runtime.m2_operator_demo import run_m2_operator_demo
from agent_runtime.run_task import app

runner = CliRunner()
ROOT = Path(__file__).resolve().parents[1]


def test_m2_operator_demo_module_writes_report(tmp_path):
    summary = run_m2_operator_demo(ROOT, tmp_path / "demo", project="AgentLab")
    assert summary["status"] == "pass"
    assert (tmp_path / "demo" / "M2_OPERATOR_OS_EXECUTION_ECONOMY_REPORT.md").is_file()
    assert (tmp_path / "demo" / "route_decision.yml").is_file()
    assert summary["acceptance"]["all 9 roles have capability requirements"] is True


def test_m2_operator_demo_cli_writes_report(tmp_path):
    out = tmp_path / "cli_demo"
    result = runner.invoke(app, ["m2-operator-demo", "--out", str(out), "--project", "AgentLab"])
    assert result.exit_code == 0
    assert "M2-12 operator demo status: pass" in result.output
    assert (out / "M2_OPERATOR_OS_EXECUTION_ECONOMY_REPORT.md").is_file()
