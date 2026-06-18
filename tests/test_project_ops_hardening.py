from __future__ import annotations

import subprocess
from pathlib import Path

import yaml
from typer.testing import CliRunner

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))
sys.modules.pop("atomic_io", None)

from project_ops import init_project, route_invocation_to_project  # noqa: E402
from repo_hygiene import check_repo_hygiene  # noqa: E402
from run_task import app  # noqa: E402
from task_compaction import append_agent_contribution, compact_task, project_status  # noqa: E402


def test_creative_longform_routes_to_new_project_not_agentlab() -> None:
    route = route_invocation_to_project(
        {
            "task_type": "creative_longform",
            "title": "Long novel with stable worldbuilding",
            "user_goal": "Plan and write a long novel with persistent memory.",
        },
        existing_projects={"AgentLab"},
    )
    assert route.action == "create_new_project"
    assert route.project_id is not None
    assert route.project_id.startswith("creative_")
    assert route.project_id != "AgentLab"


def test_self_development_signal_routes_to_agentlab() -> None:
    route = route_invocation_to_project(
        {
            "task_type": "local_ops",
            "user_goal": "修 AgentLab 的 repo hygiene 和 ProjectOps",
        },
        existing_projects={"AgentLab"},
    )
    assert route.action == "self_development_project"
    assert route.project_id == "AgentLab"


def test_ambiguous_coding_does_not_default_to_agentlab() -> None:
    route = route_invocation_to_project(
        {
            "task_type": "coding",
            "user_goal": "Fix the login bug.",
        },
        existing_projects={"AgentLab"},
    )
    assert route.action == "ambiguous_requires_user_decision"
    assert route.project_id is None


def test_project_init_and_task_compaction_create_expected_foundation(tmp_path: Path) -> None:
    init_project(tmp_path, "creative_memory_novel", "creative_longform", "Memory Novel")
    project_root = tmp_path / "projects" / "creative_memory_novel"
    assert (project_root / "project_manifest.yml").exists()
    assert (project_root / "agent_docs" / "PROJECT_BRIEF.md").exists()

    run_dir = project_root / "runs" / "task_0001"
    run_dir.mkdir(parents=True)
    (run_dir / "user_request.md").write_text("Write chapter one.", encoding="utf-8")
    (run_dir / "state.yml").write_text("status: completed\n", encoding="utf-8")
    append_agent_contribution(
        tmp_path,
        "creative_memory_novel",
        "task_0001",
        {
            "agent_id": "creative_worker",
            "role": "creative",
            "status": "completed",
            "summary": "drafted outline",
            "accepted_by_supervisor": True,
        },
    )

    result = compact_task(tmp_path, "creative_memory_novel", "task_0001")
    compact_dir = Path(result["compact_dir"])
    assert (compact_dir / "task_summary.md").exists()
    assert (compact_dir / "artifact_index.yml").exists()
    contributions = yaml.safe_load((compact_dir / "agent_contribution_summary.yml").read_text(encoding="utf-8"))
    assert contributions["accepted_count"] == 1

    status = project_status(tmp_path, "creative_memory_novel")
    assert status["counts"]["closed_tasks"] == 1
    assert status["counts"]["compacted_tasks"] == 1


def test_repo_hygiene_flags_root_pollution_and_missing_agentlab_ignore(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, stdout=subprocess.PIPE)
    (tmp_path / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
    (tmp_path / "agentlab.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (tmp_path / "agent_runtime").mkdir()
    (tmp_path / "scratch_notes.md").write_text("temporary", encoding="utf-8")

    report = check_repo_hygiene(tmp_path)
    codes = {issue["code"] for issue in report["issues"]}
    assert report["status"] == "fail"
    assert "agentlab_runtime_not_ignored" in codes
    assert "unknown_root_entry" in codes
    assert "forbidden_root_artifact" in codes


def test_new_projectops_cli_commands_are_registered(tmp_path: Path) -> None:
    contract = tmp_path / "mission.yml"
    contract.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "mission_id": "mission_novel",
                "task_type": "creative_longform",
                "user_goal": "Write a long novel.",
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()
    for cmd in [
        "repo-hygiene-check",
        "project-route",
        "project-init",
        "task-compact",
        "agent-contributions",
        "project-status",
    ]:
        result = runner.invoke(app, [cmd, "--help"])
        assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["project-route", "--mission-contract", str(contract), "--json"])
    assert result.exit_code == 0, result.output
    assert "create_new_project" in result.output
