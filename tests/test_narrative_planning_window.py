from __future__ import annotations

from pathlib import Path
import hashlib
import os
import subprocess

import pytest
import yaml

from agent_runtime.narrative.planning_window import (
    PlanningWindowError,
    activate_planning_window,
    complete_planning_window_chapter,
    propose_planning_window,
    seal_planning_window,
)


def _write_yaml(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _blueprint(root: Path, *, chapter_end: int = 25) -> Path:
    project = root / "projects" / "Crown_of_Ash"
    _write_yaml(
        project / "production" / "blueprint_authority.yml",
        {
            "schema_version": "crown-blueprint-authority/v1",
            "project": "Crown_of_Ash",
            "status": "active",
            "scope": {
                "planned_total_chapters": 1980,
                "detailed_chapter_contract_range": [1, chapter_end],
            },
        },
    )
    for chapter in range(1, chapter_end + 1):
        _write_yaml(
            project / "production" / "chapter_cards" / f"ch{chapter:03d}.yml",
            {
                "schema_version": 1,
                "chapter": chapter,
                "scene_goal": f"goal {chapter}",
            },
        )
    _write_yaml(
        project / "project_brain" / "blueprint_validation_receipt.yml",
        {"schema_version": 1, "status": "pass"},
    )
    return project


def test_propose_migrates_first_ten_locked_and_remaining_cards_to_horizon(
    tmp_path: Path,
) -> None:
    project = _blueprint(tmp_path)

    proposal = propose_planning_window(tmp_path, project="Crown_of_Ash")

    assert proposal["schema_version"] == "narrative-planning-window/v1"
    assert proposal["status"] == "proposed"
    assert [item["chapter"] for item in proposal["locked_queue"]] == list(
        range(1, 11)
    )
    assert [item["chapter"] for item in proposal["adjustable_horizon"]] == list(
        range(11, 26)
    )
    assert proposal["source_blueprint"]["sha256"] == hashlib.sha256(
        (project / "production" / "blueprint_authority.yml").read_bytes()
    ).hexdigest()
    assert proposal["superseded_blueprint_seal"]["path"].endswith(
        "blueprint_validation_receipt.yml"
    )
    assert not (project / "production" / "narrative_planning_window.yml").exists()


def test_seal_activate_and_complete_rolls_locked_queue_atomically(
    tmp_path: Path,
) -> None:
    project = _blueprint(tmp_path)
    proposal = propose_planning_window(tmp_path, project="Crown_of_Ash")

    sealed = seal_planning_window(tmp_path, proposal=proposal)
    active = activate_planning_window(tmp_path, project="Crown_of_Ash")
    completed = complete_planning_window_chapter(
        tmp_path,
        project="Crown_of_Ash",
        chapter=1,
    )

    assert sealed["status"] == "sealed"
    assert active["status"] == "active"
    assert completed["completed_chapters"] == [1]
    assert [item["chapter"] for item in completed["locked_queue"]] == list(
        range(2, 12)
    )
    assert [item["chapter"] for item in completed["adjustable_horizon"]] == list(
        range(12, 26)
    )
    current = yaml.safe_load(
        (
            project / "production" / "narrative_planning_window.yml"
        ).read_text(encoding="utf-8")
    )
    assert current == completed
    artifact_index = yaml.safe_load(
        (project / "project_artifact_index.yml").read_text(encoding="utf-8")
    )
    planning_entries = [
        item
        for item in artifact_index["artifacts"]
        if item["artifact_id"] == "crown_of_ash_narrative_planning_window"
    ]
    assert len(planning_entries) == 1
    assert planning_entries[0]["status"] == "current"
    assert planning_entries[0]["production_sha256"] == hashlib.sha256(
        (
            project / "production" / "narrative_planning_window.yml"
        ).read_bytes()
    ).hexdigest()
    history = list(
        (project / "project_brain" / "planning_windows" / "history").glob("*.yml")
    )
    assert len(history) == 2
    assert all(
        yaml.safe_load(path.read_text(encoding="utf-8"))["status"] == "superseded"
        for path in history
    )


def test_replacing_a_locked_queue_requires_supersede_reason(tmp_path: Path) -> None:
    _blueprint(tmp_path)
    proposal = propose_planning_window(tmp_path, project="Crown_of_Ash")
    seal_planning_window(tmp_path, proposal=proposal)
    replacement = {
        **proposal,
        "window_id": "replacement-window",
        "locked_queue": proposal["locked_queue"][:-1],
        "adjustable_horizon": [
            proposal["locked_queue"][-1],
            *proposal["adjustable_horizon"],
        ],
    }

    with pytest.raises(PlanningWindowError, match="supersede_reason"):
        seal_planning_window(tmp_path, proposal=replacement)


def test_seal_rejects_source_blueprint_path_escape(tmp_path: Path) -> None:
    _blueprint(tmp_path)
    proposal = propose_planning_window(tmp_path, project="Crown_of_Ash")
    outside = tmp_path / "outside.yml"
    outside.write_text("scope: {}\n", encoding="utf-8")
    proposal["source_blueprint"] = {
        **proposal["source_blueprint"],
        "path": str(outside),
        "sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
    }

    with pytest.raises(PlanningWindowError, match="escapes project root"):
        seal_planning_window(tmp_path, proposal=proposal)


def test_planning_window_cli_exposes_governed_lifecycle_commands() -> None:
    root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [str(root / "agentlab.sh"), "narrative", "planning-window", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "NO_COLOR": "1", "COLUMNS": "180"},
    )

    assert result.returncode == 0, result.stderr
    for command in ("propose", "seal", "activate", "complete"):
        assert command in result.stdout
