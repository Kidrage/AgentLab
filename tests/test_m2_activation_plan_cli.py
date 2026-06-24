"""Tests for compile_activation_plan and Typer CLI commands."""

from pathlib import Path
import yaml
from typer.testing import CliRunner
from agent_runtime.run_task import app
from agent_runtime.execution_economy.activation_plan import compile_activation_plan

def test_compile_activation_plan_and_cli(tmp_path):
    # 1. Create a mock task packet
    packet_data = {
        "task_packet": {
            "packet_id": "test_proj_phase1_task",
            "project_id": "test_proj",
            "phase_id": "phase1",
            "objective": "Build a small, clean function to parse yaml strings."
        }
    }

    packet_path = tmp_path / "task_packet.yml"
    packet_path.write_text(yaml.safe_dump(packet_data), encoding="utf-8")

    # Run compiler
    plan = compile_activation_plan(packet_path, tmp_path)

    assert plan["activation_plan"]["project_id"] == "test_proj"
    assert plan["activation_plan"]["task_size"] == "small"
    assert len(plan["activation_plan"]["decisions"]) == 9

    # Verify outputs are written
    ee_dir = tmp_path / "projects" / "test_proj" / "execution_economy"
    assert (ee_dir / "activation_plan.yml").is_file()
    assert (ee_dir / "role_coalescing.yml").is_file()
    assert (ee_dir / "context_reuse_plan.yml").is_file()
    assert (ee_dir / "cache_profile_report.yml").is_file()
    assert (ee_dir / "escalation_ladder.yml").is_file()
    assert (ee_dir / "execution_economy_report.md").is_file()
    assert (ee_dir / "activation_decisions" / "supervisor.yml").is_file()

    # 2. Test CLI commands via CliRunner
    runner = CliRunner()

    # Test activation-plan
    result = runner.invoke(app, ["activation-plan", "--task-packet", str(packet_path)])
    assert result.exit_code == 0
    assert "activation_plan" in result.stdout

    # Test activation-explain
    decision_file = ee_dir / "activation_decisions" / "supervisor.yml"
    result = runner.invoke(app, ["activation-explain", "--decision", str(decision_file)])
    assert result.exit_code == 0
    assert "Role: Supervisor" in result.stdout

    # Test estimate-spawn-cost
    result = runner.invoke(app, ["estimate-spawn-cost", "--worker", "claude_code", "--role", "Coder"])
    assert result.exit_code == 0
    assert "worker_id: claude_code" in result.stdout

    # Test cache-profile-report
    result = runner.invoke(app, ["cache-profile-report", "--worker", "claude_code"])
    assert result.exit_code == 0
    assert "worker_id: claude_code" in result.stdout
