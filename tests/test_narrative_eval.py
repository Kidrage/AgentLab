from __future__ import annotations

import shutil
import sys
from pathlib import Path

import typer
import yaml
from rich.console import Console
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.cli.narrative_eval import register_narrative_eval_commands
from agent_runtime.narrative_eval import run_narrative_eval


runner = CliRunner()


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _copy_config_root(tmp_path: Path) -> Path:
    root = tmp_path / "AgentLab"
    (root / "config").mkdir(parents=True)
    for name in [
        "content_project_governance.yml",
        "agent_role_bindings.yml",
        "frontdesk_policy.yml",
    ]:
        shutil.copy(ROOT / "config" / name, root / "config" / name)
    return root


def _make_crown_project(root: Path) -> Path:
    project_root = root / "projects" / "Crown_of_Ash"
    (project_root / "production" / "bible").mkdir(parents=True)
    (project_root / "production" / "outlines").mkdir(parents=True)
    (project_root / "production" / "manuscript").mkdir(parents=True)
    (project_root / "production" / "bible" / "roles.md").write_text("# Roles\n", encoding="utf-8")
    (project_root / "production" / "outlines" / "main_outline.md").write_text("# Outline\n", encoding="utf-8")
    for chapter in range(1, 11):
        (project_root / "production" / "manuscript" / f"第{chapter:02d}章_旧稿.md").write_text(
            f"# Old Ch{chapter}\n旧稿作废。\n",
            encoding="utf-8",
        )
    _write_yaml(
        project_root / "project_artifact_index.yml",
        {
            "artifacts": [
                {"artifact_id": "project_bible", "status": "current", "production_path": "production/bible/"},
                {"artifact_id": "outline_set", "status": "current", "production_path": "production/outlines/"},
                {"artifact_id": "manuscript_series", "status": "deprecated", "production_path": "production/manuscript/"},
            ]
        },
    )
    _write_yaml(project_root / "project_brain" / "project_fact_snapshot.yml", {"project": "Crown_of_Ash", "event_count": 0})
    (project_root / "project_brain" / "project_fact_events.jsonl").write_text("", encoding="utf-8")
    (project_root / "project_brain" / "revision_log.jsonl").write_text("", encoding="utf-8")
    return project_root


def test_narrative_eval_reset_mock_generates_candidate_chapters_without_production_writes(tmp_path: Path) -> None:
    root = _copy_config_root(tmp_path)
    project_root = _make_crown_project(root)
    production_before = {
        path.relative_to(project_root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted((project_root / "production" / "manuscript").glob("*.md"))
    }

    result = run_narrative_eval(
        root,
        "Crown_of_Ash",
        suite="crown_reset_acceptance_v1",
        mode="mock",
        chapters=[1, 2, 3],
        timestamp="20260705T000000Z",
    )

    eval_dir = root / result["acceptance_run_dir"]
    assert result["status"] == "warn"
    assert result["baseline"]["old_chapters_used_as_continuity_source"] is False
    assert (eval_dir / "longform_eval_report.yml").exists()
    assert (eval_dir / "chapter_quality_matrix.yml").exists()
    assert (eval_dir / "continuity_failure_report.yml").exists()
    assert (eval_dir / "series_scale_simulation.yml").exists()
    assert (eval_dir / "manuscript_reset_proposal.yml").exists()

    reset_proposal = yaml.safe_load((eval_dir / "manuscript_reset_proposal.yml").read_text(encoding="utf-8"))
    assert len(reset_proposal["deprecated_sources"]) == 10
    assert reset_proposal["production_modified"] is False

    l2_chapters = result["layers"]["L2_real_chapter_sample"]["chapters"]
    assert [item["chapter"] for item in l2_chapters] == [1, 2, 3]
    for item in l2_chapters:
        run_dir = root / item["run_dir"]
        packet = yaml.safe_load((run_dir / "chapter_packet.yml").read_text(encoding="utf-8"))
        assert packet["baseline_mode"] == "reset"
        assert not any(source.startswith("production/manuscript/") for source in packet["previous_chapters"])
        assert item["delivery"]["valid"] is True
        assert (run_dir / "narrative_delivery_receipt.yml").exists()

    ch1_packet = yaml.safe_load((root / l2_chapters[0]["run_dir"] / "chapter_packet.yml").read_text(encoding="utf-8"))
    ch2_packet = yaml.safe_load((root / l2_chapters[1]["run_dir"] / "chapter_packet.yml").read_text(encoding="utf-8"))
    assert ch1_packet["previous_chapters"] == []
    assert any("runs/narrative_eval_ch01_20260705T000000Z/fiction_draft.md" == source for source in ch2_packet["previous_chapters"])

    production_after = {
        path.relative_to(project_root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted((project_root / "production" / "manuscript").glob("*.md"))
    }
    assert production_after == production_before


def test_narrative_eval_blocks_generation_when_fact_snapshot_missing(tmp_path: Path) -> None:
    root = _copy_config_root(tmp_path)
    project_root = _make_crown_project(root)
    (project_root / "project_brain" / "project_fact_snapshot.yml").unlink()

    result = run_narrative_eval(root, "Crown_of_Ash", mode="mock", timestamp="20260705T010000Z")

    assert result["status"] == "fail"
    assert result["layers"]["L0_fact_source_health"]["live_generation_blocked"] is True
    assert result["layers"]["L2_real_chapter_sample"]["status"] == "blocked"
    generated_runs = list((project_root / "runs").glob("narrative_eval_ch*")) if (project_root / "runs").exists() else []
    assert generated_runs == []


def test_narrative_eval_scale_simulation_has_1500_chapter_ledgers(tmp_path: Path) -> None:
    root = _copy_config_root(tmp_path)
    _make_crown_project(root)

    result = run_narrative_eval(root, "Crown_of_Ash", mode="audit-only", timestamp="20260705T020000Z")
    eval_dir = root / result["acceptance_run_dir"]
    simulation = yaml.safe_load((eval_dir / "series_scale_simulation.yml").read_text(encoding="utf-8"))

    assert simulation["chapter_count"] == 1500
    assert simulation["timeline_monotonic"] is True
    assert simulation["foreshadowing_statuses_valid"] is True
    assert simulation["character_arcs_have_phase_changes"] is True
    for filename in simulation["ledgers"].values():
        assert (eval_dir / filename).exists()


def test_narrative_eval_cli_run_on_temp_root(tmp_path: Path) -> None:
    root = _copy_config_root(tmp_path)
    _make_crown_project(root)
    local_app = typer.Typer()
    register_narrative_eval_commands(local_app, root, Console(width=120))

    result = runner.invoke(
        local_app,
        [
            "narrative-eval",
            "run",
            "--project",
            "Crown_of_Ash",
            "--suite",
            "crown_reset_acceptance_v1",
            "--mode",
            "mock",
            "--chapters",
            "1-3",
            "--timestamp",
            "20260705T030000Z",
        ],
    )

    assert result.exit_code == 0
    data = yaml.safe_load(result.output)
    assert data["acceptance_run_dir"] == "acceptance_runs/narrative_eval/Crown_of_Ash/crown_reset_acceptance_v1/20260705T030000Z"
