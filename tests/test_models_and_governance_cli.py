from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yaml
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.cli.governance import build_revision_intake, run_governance_doctor
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


def test_revision_intake_builds_change_request_and_transition():
    change_request, transition = build_revision_intake("Crown_of_Ash", "task_1", "Revise role motive\nAdjust chapter 3 outline")

    assert change_request["change_items"][0]["text"] == "Revise role motive"
    assert transition["source_change_request"] == "change_request.yml"
    assert transition["requires_conflict_check"] is True
