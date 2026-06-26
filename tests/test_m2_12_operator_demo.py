from pathlib import Path

from typer.testing import CliRunner

from agent_runtime.m2_operator_demo import run_m2_operator_demo
from agent_runtime.run_task import app

runner = CliRunner()
ROOT = Path(__file__).resolve().parents[1]


def test_m2_operator_demo_module_writes_report(tmp_path):
    summary = run_m2_operator_demo(ROOT, tmp_path / "demo", project="AgentLab")
    assert summary["status"] == "pass"
    assert summary["migration"]["strict_migration"] is False
    assert "demo_blocking_failures" in summary["migration"]
    assert "private_infra_deferred_items" in summary["migration"]
    assert "warnings" in summary["migration"]
    assert (tmp_path / "demo" / "M2_OPERATOR_OS_EXECUTION_ECONOMY_REPORT.md").is_file()
    assert (tmp_path / "demo" / "route_decision.yml").is_file()
    assert summary["acceptance"]["all roles have capability requirements"] is True


def test_m2_operator_demo_cli_writes_report(tmp_path):
    out = tmp_path / "cli_demo"
    result = runner.invoke(app, ["m2-operator-demo", "--out", str(out), "--project", "AgentLab"])
    assert result.exit_code == 0
    assert "M2-12 operator demo status: pass" in result.output
    assert (out / "M2_OPERATOR_OS_EXECUTION_ECONOMY_REPORT.md").is_file()


def test_m2_operator_demo_cli_strict_flag_is_exposed():
    result = runner.invoke(app, ["m2-operator-demo", "--help"])
    assert result.exit_code == 0
    # Strip ANSI escape sequences so substring checks work in CI
    # (Rich may emit color codes that break contiguous flag strings).
    import re

    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert "--strict-migration" in plain
