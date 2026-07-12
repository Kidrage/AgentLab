from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.crown_candidate_audit import (
    build_crown_completion_batch_audit,
    build_crown_live_candidate_audit,
)
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_crown_live_candidate_audit_checks_candidate_integrity(
    private_crown_project_root: Path,
) -> None:
    report = build_crown_live_candidate_audit(private_crown_project_root)
    by_id = {item["id"]: item for item in report["checks"]}

    assert report["status"] == "pass"
    assert by_id["required_files_present"]["status"] == "pass"
    assert by_id["delivery_protocol_valid"]["status"] == "pass"
    assert by_id["draft_substantial"]["metrics"]["lines"] >= 100
    assert by_id["chapter_packet_reset_baseline"]["status"] == "pass"
    assert by_id["state_transition_candidate_only"]["status"] == "pass"
    assert by_id["production_manuscript_not_modified"]["status"] == "pass"
    assert report["summary"]["candidate_only"] is True


def test_crown_live_candidate_audit_cli_writes_yaml(
    tmp_path: Path,
    private_crown_project_root: Path,
) -> None:
    del private_crown_project_root
    out = tmp_path / "crown_live_candidate_audit.yml"

    result = runner.invoke(app, ["crown-live-candidate-audit", "--out", str(out)])

    assert result.exit_code == 0
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["report_type"] == "agentlab_crown_live_candidate_audit"
    assert report["status"] == "pass"


def _write_batch_chapter(root: Path, chapter: int, eval_id: str) -> None:
    task_id = f"task_narrative_eval_ch{chapter:02d}_{eval_id}"
    run_dir = root / "projects" / "Crown_of_Ash" / "runs" / task_id
    run_dir.mkdir(parents=True)
    previous_id = f"task_narrative_eval_ch{chapter - 1:02d}_{eval_id}"
    previous = [] if chapter == 1 else [
        f"runs/{previous_id}/fiction_draft.md",
        f"runs/{previous_id}/continuity_ledger.yml",
        f"runs/{previous_id}/state_transition_proposal.yml",
    ]
    baseline = "reset" if chapter == 1 else "continuation"
    draft = f"# 第{chapter}章\n\n" + (f"正文{chapter}" * 1100)
    files = {
        "chapter_packet.yml": {
            "chapter": chapter,
            "baseline_mode": baseline,
            "previous_candidate_sources": previous,
            "chapter_intent": {"hard_character_range": [3000, 8000]},
        },
        "continuity_ledger.yml": {
            "schema_version": 1,
            "chapter": chapter,
            "baseline_mode": baseline,
            "timeline": {"monotonic": True},
            "plot_state_changes": [f"plot {chapter}"],
            "character_changes": [f"character {chapter}"],
            "relationship_or_worldline_changes": [f"worldline {chapter}"],
            "foreshadowing": [f"foreshadowing {chapter}"],
        },
        "state_transition_proposal.yml": {
            "schema_version": 1,
            "status": "candidate",
            "chapter": chapter,
            "requires_user_promotion": True,
            "events": [
                {
                    "event_type": "chapter_state_change",
                    "scope": "candidate_only",
                    "summary": f"event {chapter}",
                }
            ],
        },
        "narrative_delivery_receipt.yml": {
            "schema_version": 1,
            "status": "pass",
            "candidate_only": True,
            "checks": {
                "chapter_and_title": "pass",
                "required_beats": "pass",
                "continuity_outputs": "pass",
                "production_untouched": "pass",
                "deprecated_sources_excluded": "pass",
            },
        },
        "writer_output_contract.yml": {
            "schema_version": 1,
            "status": "pass",
            "normalizations": [],
        },
        "candidate_fact_ledger.yml": {
            "schema_version": 1,
            "status": "candidate",
            "promoted": False,
            "through_chapter": chapter - 1,
            "event_count": chapter - 1,
        },
    }
    (run_dir / "fiction_draft.md").write_text(draft, encoding="utf-8")
    for filename, data in files.items():
        (run_dir / filename).write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    log_dir = run_dir / "command_logs"
    log_dir.mkdir()
    (log_dir / "agy_cli_agent.log").write_text(
        'Propagating selected model override to backend: label="Gemini 3.5 Flash (High)"\n',
        encoding="utf-8",
    )


def test_crown_completion_batch_audit_checks_one_continuous_chain(tmp_path: Path) -> None:
    manuscript = tmp_path / "projects" / "Crown_of_Ash" / "production" / "manuscript"
    manuscript.mkdir(parents=True)
    (manuscript / ".gitkeep").write_text("", encoding="utf-8")
    _write_batch_chapter(tmp_path, 1, "fixture")
    _write_batch_chapter(tmp_path, 2, "fixture")

    report = build_crown_completion_batch_audit(
        tmp_path,
        eval_id="fixture",
        through_chapter=2,
    )

    assert report["status"] == "pass"
    assert report["summary"]["valid_chapter_count"] == 2
    assert report["summary"]["total_candidate_events"] == 2
    assert report["summary"]["production_manuscript_files"] == []
    assert report["warnings"] == []
    assert report["issues"] == []
