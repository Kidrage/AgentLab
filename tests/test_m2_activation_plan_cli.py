"""Tests for compile_activation_plan and Typer CLI commands."""

from pathlib import Path
import yaml
from typer.testing import CliRunner
from agent_runtime.run_task import app
from agent_runtime.execution_economy.activation_plan import compile_activation_plan
from agent_runtime.routing.route_catalog import RouteCatalog

def test_compile_activation_plan_and_cli(tmp_path):
    # 1. Create a mock task packet
    packet_data = {
        "task_packet": {
            "packet_id": "test_proj_phase1_task",
            "project_id": "test_proj",
            "phase_id": "phase1",
            "objective": "Fix a small typo in one Python file."
        }
    }

    packet_path = tmp_path / "task_packet.yml"
    packet_path.write_text(yaml.safe_dump(packet_data), encoding="utf-8")

    # Run compiler
    plan = compile_activation_plan(packet_path, tmp_path)

    assert plan["activation_plan"]["project_id"] == "test_proj"
    assert plan["activation_plan"]["task_size"] == "small"
    assert plan["activation_plan"]["route_key"] == "small_task"
    expected_roles = RouteCatalog.from_config().agents_for("small_task")
    assert [item["role"] for item in plan["activation_plan"]["decisions"]] == expected_roles
    assert plan["activation_plan"]["cross_role_coalescing"] is False

    # Verify outputs are written
    ee_dir = tmp_path / "projects" / "test_proj" / "runs" / "test_proj_phase1_task" / "execution_economy"
    assert (ee_dir / "activation_plan.yml").is_file()
    assert (ee_dir / "role_session_plan.yml").is_file()
    assert not (ee_dir / "role_coalescing.yml").exists()
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


def test_activation_plan_honors_explicit_catalog_route(tmp_path):
    packet_path = tmp_path / "task_packet.yml"
    packet_path.write_text(
        yaml.safe_dump(
            {
                "task_packet": {
                    "packet_id": "chapter_001",
                    "project_id": "Crown_of_Ash",
                    "objective": "写 Crown 第 1 章。",
                    "route_key": "narrative_light_chapter",
                }
            }
        ),
        encoding="utf-8",
    )

    plan = compile_activation_plan(packet_path, tmp_path)["activation_plan"]

    assert plan["route_key"] == "narrative_light_chapter"
    assert [item["role"] for item in plan["decisions"]] == ["Supervisor", "Writer"]
    assert all(
        item["session_boundary"] == "independent_role_receipt"
        for item in plan["role_sessions"]
    )
