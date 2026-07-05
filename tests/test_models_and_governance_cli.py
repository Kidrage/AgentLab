from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yaml
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.cli.governance import build_revision_intake, run_governance_doctor
from agent_runtime.program_manager.project_fact_state import append_project_fact_events, rebuild_project_fact_snapshot
from agent_runtime.protocols import build_role_session
from agent_runtime.pipeline_runner import run_full_pipeline
from agent_runtime.revision_governance import (
    apply_revision,
    check_revision_conflicts,
    revision_dispatch_status,
    validate_revision,
    write_revision_intake,
)
from agent_runtime.run_task import app


runner = CliRunner()


def _copy_config_root(tmp_path: Path) -> Path:
    root = tmp_path / "AgentLab"
    (root / "config").mkdir(parents=True)
    for name in [
        "agent_model_profiles.yml",
        "model_catalog.yml",
        "model_providers.yml",
        "agent_registry.yml",
        "agent_role_bindings.yml",
        "frontdesk_policy.yml",
        "content_project_governance.yml",
    ]:
        shutil.copy(ROOT / "config" / name, root / "config" / name)
    return root


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_models_show_lists_writer_deepseek_default():
    result = runner.invoke(app, ["models", "show", "--role", "Writer"])

    assert result.exit_code == 0
    assert "writer" in result.output
    assert "deepseek_v4_flash" in result.output


def test_model_proposal_round_trip_on_temp_root(tmp_path):
    from agent_runtime.cli.models import _proposal_dir, register_model_commands
    import typer
    from rich.console import Console

    root = _copy_config_root(tmp_path)
    local_app = typer.Typer()
    register_model_commands(local_app, root, Console(width=120))

    proposed = runner.invoke(
        local_app,
        ["models", "propose", "--role", "Writer", "--cli", "agy", "--model", "deepseek_v4_flash"],
    )
    assert proposed.exit_code == 0
    data = yaml.safe_load(proposed.output)
    proposal_id = data["proposal_id"]
    profiles_before = (root / "config" / "agent_model_profiles.yml").read_text(encoding="utf-8")
    assert (_proposal_dir(root) / f"{proposal_id}.yml").exists()
    assert (root / "config" / "agent_model_profiles.yml").read_text(encoding="utf-8") == profiles_before

    applied = runner.invoke(local_app, ["models", "apply", "--proposal", proposal_id])
    assert applied.exit_code == 0
    proposal = yaml.safe_load((_proposal_dir(root) / f"{proposal_id}.yml").read_text(encoding="utf-8"))
    assert proposal["status"] == "applied"


def test_governance_doctor_detects_legacy_and_multiple_current(tmp_path):
    root = _copy_config_root(tmp_path)
    project = root / "projects" / "NovelGen"
    (project / "foo_rebuild").mkdir(parents=True)
    _write_yaml(
        project / "project_artifact_index.yml",
        {
            "artifacts": [
                {"artifact_id": "bible", "status": "current", "production_path": "production/bible/main.yml"},
                {"artifact_id": "bible", "status": "current", "production_path": "v2_rebuild/main.yml"},
            ]
        },
    )

    result = run_governance_doctor(root, "NovelGen")

    assert result["status"] == "fail"
    assert any(issue["check"] == "legacy_fact_dir" for issue in result["issues"])
    assert any(issue["check"] == "single_current_artifact" for issue in result["issues"])
    assert any(issue["check"] == "current_formal_fact_root" for issue in result["issues"])
    assert result["migration_report"]["safe_by_default"] is True
    assert result["migration_report"]["legacy_directories"][0]["path"] == "projects/NovelGen/foo_rebuild"
    assert result["migration_report"]["current_artifact_groups"][0]["current_count"] == 2
    assert any(action["action_id"] == "dedupe_current_artifact_bible" for action in result["remediation_plan"])
    assert any(action["action_id"] == "retire_legacy_current_artifact_bible" for action in result["remediation_plan"])


def test_governance_doctor_reports_revision_migration_actions(tmp_path):
    root = _copy_config_root(tmp_path)
    run_dir = root / "projects" / "NovelGen" / "runs" / "task_revision"
    run_dir.mkdir(parents=True)
    (run_dir / "user_request.md").write_text("Please revise the character motive.", encoding="utf-8")

    result = run_governance_doctor(root, "NovelGen")

    assert result["status"] == "pass"
    assert result["migration_report"]["pending_revision_runs"] == [
        {
            "task_id": "task_revision",
            "path": "projects/NovelGen/runs/task_revision",
            "missing": "change_request.yml",
        }
    ]
    issue = next(item for item in result["issues"] if item["check"] == "revision_change_request")
    assert issue["command"].startswith("./agentlab.sh governance revision-intake --project NovelGen")
    assert any(action["action_id"] == "intake_revision_task_revision" for action in result["remediation_plan"])


def test_governance_doctor_write_report(tmp_path):
    import typer
    from rich.console import Console
    from agent_runtime.cli.governance import register_governance_commands

    root = _copy_config_root(tmp_path)
    (root / "projects" / "NovelGen").mkdir(parents=True)
    local_app = typer.Typer()
    register_governance_commands(local_app, root, Console(width=120))

    result = runner.invoke(local_app, ["governance", "doctor", "--project", "NovelGen", "--write-report"])

    assert result.exit_code == 0
    report_path = root / "projects" / "NovelGen" / "project_brain" / "governance_migration_report.yml"
    assert report_path.exists()
    report = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    assert report["migration_report"]["safe_by_default"] is True


def test_revision_intake_builds_change_request_and_transition():
    change_request, transition = build_revision_intake("Crown_of_Ash", "task_1", "Revise role motive\nAdjust chapter 3 outline")

    assert change_request["change_items"][0]["text"] == "Revise role motive"
    body = transition["state_transition_proposal"]
    assert body["source_change_request"] == "change_request.yml"
    assert body["requires_conflict_check"] is True
    assert body["events"][0]["event_type"] == "propose_revision"


def test_revision_apply_merges_events_and_unblocks_dispatch(tmp_path):
    root = _copy_config_root(tmp_path)
    write_revision_intake(root, "NovelGen", "task_revision", "Revise role motive")

    pending = revision_dispatch_status(root, "NovelGen", "task_revision")
    validation = validate_revision(root, "NovelGen", "task_revision")

    assert pending["blocked"] is True
    assert validation["valid"] is True

    result = apply_revision(root, "NovelGen", "task_revision", accepted_by="pytest")
    ready = revision_dispatch_status(root, "NovelGen", "task_revision")

    assert result["applied"] is True
    assert ready["blocked"] is False
    assert (root / "projects" / "NovelGen" / "project_brain" / "project_fact_events.jsonl").exists()
    assert (root / "projects" / "NovelGen" / "project_brain" / "revision_log.jsonl").exists()


def test_revision_conflict_checker_detects_snapshot_fact_conflict(tmp_path):
    root = _copy_config_root(tmp_path)
    brain = root / "projects" / "NovelGen" / "project_brain"
    append_project_fact_events(
        brain,
        [
            {
                "event_type": "create",
                "target_kind": "entity",
                "target_type": "character",
                "target_id": "hero",
                "to_status": "active",
                "facts": {"motive": "revenge"},
                "evidence_refs": ["chapter_01.md"],
            }
        ],
    )
    snapshot = rebuild_project_fact_snapshot(brain, project="NovelGen")
    proposal = {
        "events": [
            {
                "event_type": "revise",
                "target_kind": "entity",
                "target_type": "character",
                "target_id": "hero",
                "to_status": "active",
                "facts": {"motive": "mercy"},
                "evidence_refs": ["change_request.yml"],
            }
        ]
    }

    result = check_revision_conflicts(snapshot, proposal)

    assert result["valid"] is False
    assert "conflicts with current snapshot" in result["conflicts"][0]["message"]


def test_pending_revision_blocks_coder_role_session(tmp_path):
    root = _copy_config_root(tmp_path)
    write_revision_intake(root, "NovelGen", "task_revision", "Revise role motive")

    blocked = build_role_session(root, "Coder", "codex", project="NovelGen", task_id="task_revision")
    apply_revision(root, "NovelGen", "task_revision", accepted_by="pytest")
    allowed = build_role_session(root, "Coder", "codex", project="NovelGen", task_id="task_revision")

    assert blocked["binding"]["allowed"] is False
    assert "revision governance blocks Coder dispatch" in blocked["binding"]["reason"]
    assert allowed["binding"]["allowed"] is True


def test_pending_revision_blocks_execute_pipeline_direct_call(tmp_path):
    root = _copy_config_root(tmp_path)
    write_revision_intake(root, "NovelGen", "task_revision", "Revise role motive")

    result = run_full_pipeline(root, "NovelGen", "task_revision", dry_run=False, fake_provider=False, max_steps=1)

    assert result["success"] is False
    assert result["blocked_type"] == "revision_governance"
