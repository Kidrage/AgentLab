from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

import yaml
from typer.testing import CliRunner

from agent_runtime.program_manager.phase_acceptance import accept_phase
from agent_runtime.executors.task_packet import create_task_packet
from agent_runtime.program_manager.project_brain import build_project_brain, build_project_next_actions, build_project_plan
from run_task import app


def _mission(path: Path, task_type: str = "creative_longform") -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "task_id": "mission_s7",
                "task_type": task_type,
                "user_goal": "Write a long cyberpunk novel" if task_type == "creative_longform" else "Repair this repo",
                "intent_summary": "Long project that must be planned before execution",
                "required_capabilities": [{"capability": "local_search"}],
                "risk_flags": ["long_running_project"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def test_creative_prompt_becomes_roadmap_not_direct_draft(tmp_path: Path) -> None:
    result = build_project_brain(_mission(tmp_path / "mission.yml"), "NovelDemo", tmp_path / "brain")
    assert result["ok"] is True
    roadmap = yaml.safe_load((tmp_path / "brain" / "roadmap.yml").read_text(encoding="utf-8"))
    assert roadmap["no_direct_execution"] is True
    assert roadmap["milestones"][0]["phase_id"] == "phase_1_foundation"
    assert not (tmp_path / "brain" / "draft.md").exists()


def test_project_plan_has_acceptance_and_context_summary(tmp_path: Path) -> None:
    build_project_brain(_mission(tmp_path / "mission.yml", "coding"), "RepoRepair", tmp_path / "brain")
    phase = build_project_plan(tmp_path / "brain", tmp_path / "plan")
    assert phase["phase_id"] == "phase_1_repo_context"
    assert "all_required_outputs_have_evidence" in phase["acceptance_criteria"]
    assert (tmp_path / "brain" / "phase_summaries" / "phase_1_repo_context.md").is_file()


def test_task_packet_records_project_brain_consumption(tmp_path: Path) -> None:
    build_project_brain(_mission(tmp_path / "mission.yml", "coding"), "RepoRepair", tmp_path / "brain")
    build_project_plan(tmp_path / "brain", tmp_path / "plan")

    packet = create_task_packet(tmp_path / "plan" / "phase_plan.yml", "mock_executor", tmp_path / "packet")
    consumption = packet["task_packet"]["project_brain_consumption"]

    assert consumption["required"] is True
    consumed = "\n".join(consumption["consumed_files"])
    assert "project_brief.yml" in consumed
    assert "roadmap.yml" in consumed
    assert "acceptance_history.yml" in consumed
    assert "next_actions.yml" in consumed
    assert "project_fact_snapshot.yml" in consumed
    assert "project_state_contract.yml" in consumed


def test_phase_acceptance_requires_named_evidence(tmp_path: Path) -> None:
    build_project_brain(_mission(tmp_path / "mission.yml", "coding"), "RepoRepair", tmp_path / "brain")
    phase = build_project_plan(tmp_path / "brain", tmp_path / "plan")
    phase_path = tmp_path / "plan" / "phase_plan.yml"
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    for name in phase["evidence_required"]:
        (evidence / name).write_text("ok: true\n", encoding="utf-8")
    result = accept_phase(phase_path, evidence, tmp_path / "accepted")
    assert result["accepted"] is False
    assert result["verdict"] == "NEEDS_HUMAN_REVIEW"
    assert result["human_approval_required"] is True


def test_project_next_uses_acceptance_history(tmp_path: Path) -> None:
    build_project_brain(_mission(tmp_path / "mission.yml", "coding"), "RepoRepair", tmp_path / "brain")
    history = {"entries": [{"phase_id": "phase_1_repo_context", "accepted": True}]}
    (tmp_path / "brain" / "acceptance_history.yml").write_text(yaml.safe_dump(history), encoding="utf-8")
    next_actions = build_project_next_actions(tmp_path / "brain", tmp_path / "next")
    assert next_actions["next_phase_id"] == "phase_2_patch_packet"


def test_s7_cli_project_brain_and_plan(tmp_path: Path) -> None:
    runner = CliRunner()
    mission = _mission(tmp_path / "mission.yml", "coding")
    init = runner.invoke(app, ["project-brain-init", "--mission-contract", str(mission), "--project", "RepoRepair", "--out", str(tmp_path / "brain")])
    assert init.exit_code == 0, init.output
    plan = runner.invoke(app, ["project-plan", "--project-brain", str(tmp_path / "brain"), "--out", str(tmp_path / "plan")])
    assert plan.exit_code == 0, plan.output
    assert (tmp_path / "plan" / "phase_plan.yml").is_file()
