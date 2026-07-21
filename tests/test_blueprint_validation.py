from __future__ import annotations

from pathlib import Path
import hashlib
import os
import subprocess

import pytest
import yaml
from click.utils import strip_ansi

from agent_runtime.narrative.blueprint_validation import (
    seal_crown_blueprint,
    validate_crown_blueprint,
)


def _write_yaml(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _valid_blueprint(root: Path) -> tuple[Path, list[dict]]:
    project = root / "projects" / "Crown_of_Ash"
    evidence = [{"source": "distilled-facts", "conclusion": "density supports decision"}]
    _write_yaml(
        project / "production" / "series_scale_decision.yml",
        {
            "schema_version": 1,
            "status": "approved",
            "decision_maker": "AgentLab.Supervisor",
            "evidence": evidence,
            "planned_total_chapters": 1920,
            "parts": [
                {"id": "part_1", "planned_chapters": 640},
                {"id": "part_2", "planned_chapters": 640},
                {"id": "part_3", "planned_chapters": 640},
            ],
            "constraints": {"three_parts": True, "anti_padding": True},
        },
    )
    _write_yaml(
        project / "production" / "chapter_length_policy.yml",
        {
            "schema_version": 1,
            "status": "approved",
            "decision_maker": "AgentLab.Supervisor",
            "evidence": evidence,
            "unit": "cjk_characters",
            "soft_min": 2100,
            "target": 2700,
            "soft_max": 3400,
            "anti_padding": {
                "prohibit_filler": True,
                "allow_scene_density_override": True,
            },
        },
    )
    _write_yaml(
        project / "project_brain" / "fact_distillation.yml",
        {
            "schema_version": 1,
            "status": "approved",
            "legacy_prose_retained": False,
            "facts": [
                {
                    "id": "fact.origin",
                    "kind": "world_fact",
                    "value": {"worldline_ref": "worldline.primary"},
                    "source_hashes": ["a" * 64],
                    "conflict_status": "resolved",
                    "conflict_conclusion": "canonical origin retained",
                }
            ],
        },
    )
    _write_yaml(
        project / "project_brain" / "project_fact_snapshot.yml",
        {
            "schema_version": 1,
            "project": "Crown_of_Ash",
            "facts": [{"id": "fact.origin"}],
            "source_hashes": {"fact.origin": ["a" * 64]},
            "conflicts": [],
        },
    )
    records = [
        {"id": "character.kane", "kind": "character", "age": 30, "current_state": {"alive": True}},
        {"id": "character.isabella", "kind": "character", "age": 28, "current_state": {"alive": True}},
        {
            "id": "relationship.kane_isabella",
            "kind": "relationship",
            "participants": ["character.kane", "character.isabella"],
            "adult_intimacy": True,
        },
        {"id": "faction.ash_court", "kind": "faction", "refs": ["character.kane"]},
        {"id": "location.black_salt", "kind": "location"},
        {"id": "magic.ash_oath", "kind": "magic_rule"},
        {
            "id": "item.ash_crown",
            "kind": "item",
            "current_state": {"owner_ref": "character.kane"},
        },
        {
            "id": "event.opening",
            "kind": "event",
            "worldline_ref": "worldline.primary",
            "time_index": 1,
            "refs": ["location.black_salt", "magic.ash_oath"],
            "state_updates": [
                {"subject_ref": "character.kane", "field": "alive", "value": True},
                {"subject_ref": "item.ash_crown", "field": "owner_ref", "value": "character.kane"},
            ],
        },
        {
            "id": "knowledge.crown_secret",
            "kind": "knowledge",
            "visibility_refs": ["character.kane"],
        },
        {"id": "worldline.primary", "kind": "worldline"},
        {"id": "foreshadowing.broken_bell", "kind": "foreshadowing", "refs": ["event.opening"]},
        {"id": "arc.part_1", "kind": "part_arc", "refs": ["foreshadowing.broken_bell"]},
    ]
    fragment = project / "production" / "canonical" / "core.yml"
    _write_yaml(fragment, {"schema_version": 1, "records": records})
    fragment_hash = hashlib.sha256(fragment.read_bytes()).hexdigest()
    _write_yaml(
        project / "production" / "canonical" / "index.yml",
        {
            "schema_version": 1,
            "fragments": [
                {"path": "production/canonical/core.yml", "sha256": fragment_hash}
            ],
        },
    )
    _write_yaml(
        project / "production" / "chapter_cards" / "index.yml",
        {
            "schema_version": 1,
            "project": "Crown_of_Ash",
            "status": "candidate",
            "candidate_only": True,
            "production_modified": False,
            "chapter_range": [1, 20],
            "chapters": list(range(1, 21)),
            "target_character_range": [2100, 3400],
            "hard_character_range": [1800, 3800],
            "chapter_state_plan": [
                {
                    "chapter": chapter,
                    "title": f"Chapter {chapter}",
                    "volume": "Part I",
                    "phase": "opening",
                    "timeline_slot": f"primary.day1.slot{chapter:02d}",
                    "pov": "Kane",
                    "opening_state": f"opening state {chapter}",
                    "scene_goal": f"irreversible scene goal {chapter}",
                    "irreversible_plot_change": f"plot change {chapter}",
                    "character_state_change": f"character change {chapter}",
                    "relationship_or_worldline_change": f"relationship change {chapter}",
                    "foreshadowing_action": f"foreshadowing action {chapter}",
                    "closing_state": f"closing state {chapter}",
                    "must_not_repeat": f"climax pattern {chapter}",
                }
                for chapter in range(1, 21)
            ],
            "validation_contract": {
                "exact_chapter_count": 20,
                "ordered_unique_chapters": True,
                "unique_scene_goals": True,
                "unique_irreversible_plot_changes": True,
                "monotonic_story_state": True,
            },
        },
    )
    for chapter in range(1, 21):
        _write_yaml(
            project / "production" / "chapter_cards" / f"ch{chapter:03d}.yml",
            {
                "schema_version": 1,
                "chapter": chapter,
                "timeline_slot": f"primary.day1.slot{chapter:02d}",
                "scene_goal": f"irreversible scene goal {chapter}",
                "pov_ref": "character.kane",
                "knowledge_requirements": {
                    "character_state": ["production/canonical/core.yml"],
                    "timeline_world_rules": ["production/canonical/core.yml"],
                    "foreshadowing": ["production/canonical/core.yml"],
                },
            },
        )
    return fragment, records


def test_validates_agentlab_decisions_canon_invariants_and_twenty_chapter_cards(
    tmp_path: Path,
) -> None:
    _valid_blueprint(tmp_path)

    result = validate_crown_blueprint(tmp_path)

    assert result == {
        "schema_version": 1,
        "status": "pass",
        "project": "Crown_of_Ash",
        "chapter_range": [1, 20],
        "record_count": 12,
        "fragment_count": 1,
        "chapter_card_count": 20,
        "issues": [],
    }


def test_blocks_duplicate_ids_dangling_refs_and_underage_intimacy(tmp_path: Path) -> None:
    fragment, records = _valid_blueprint(tmp_path)
    records[1]["age"] = 17
    records.append({"id": "character.kane", "kind": "character"})
    records[3]["refs"].append("character.missing")
    _write_yaml(fragment, {"schema_version": 1, "records": records})
    index = fragment.parent / "index.yml"
    _write_yaml(
        index,
        {
            "fragments": [
                {
                    "path": "production/canonical/core.yml",
                    "sha256": hashlib.sha256(fragment.read_bytes()).hexdigest(),
                }
            ]
        },
    )

    result = validate_crown_blueprint(tmp_path)

    assert result["status"] == "blocked"
    assert "canonical:duplicate_id:character.kane" in result["issues"]
    assert "canonical:dangling_ref:faction.ash_court:character.missing" in result["issues"]
    assert (
        "canonical:adult_boundary:relationship.kane_isabella:character.isabella"
        in result["issues"]
    )


def test_validate_blueprint_cli_is_registered() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [str(root / "agentlab.sh"), "narrative", "validate-blueprint", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env={
            **{
                key: value
                for key, value in os.environ.items()
                if key not in {"FORCE_COLOR", "CLICOLOR_FORCE"}
            },
            "COLUMNS": "180",
            "NO_COLOR": "1",
        },
    )

    assert result.returncode == 0, result.stderr
    stdout = strip_ansi(result.stdout)
    assert "--chapter-start" in stdout
    assert "--chapter-end" in stdout


def test_seal_blueprint_hashes_agentlab_fragments_and_registers_only_blueprint_roots(
    tmp_path: Path,
) -> None:
    fragment, _records = _valid_blueprint(tmp_path)
    project = fragment.parents[2]
    index = fragment.parent / "index.yml"
    raw_index = yaml.safe_load(index.read_text(encoding="utf-8"))
    raw_index["fragments"][0]["sha256"] = "pending"
    _write_yaml(index, raw_index)

    result = seal_crown_blueprint(tmp_path, project="Crown_of_Ash")

    assert result["status"] == "sealed"
    sealed_index = yaml.safe_load(index.read_text(encoding="utf-8"))
    assert sealed_index["fragments"][0]["sha256"] == hashlib.sha256(
        fragment.read_bytes()
    ).hexdigest()
    artifact_index = yaml.safe_load(
        (project / "project_artifact_index.yml").read_text(encoding="utf-8")
    )
    paths = {item["production_path"] for item in artifact_index["artifacts"]}
    assert paths == {
        "production/series_scale_decision.yml",
        "production/chapter_length_policy.yml",
        "production/canonical",
        "production/chapter_cards",
    }
    receipt = yaml.safe_load(
        (project / "project_brain" / "blueprint_validation_receipt.yml").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["status"] == "pass"
    assert receipt["validation"]["status"] == "pass"
    assert all(item["status"] == "current" for item in artifact_index["artifacts"])
    assert validate_crown_blueprint(tmp_path)["status"] == "pass"


def test_seal_refuses_invalid_blueprint_before_registering_artifacts(
    tmp_path: Path,
) -> None:
    fragment, records = _valid_blueprint(tmp_path)
    records.append({"id": "character.kane", "kind": "character"})
    _write_yaml(fragment, {"schema_version": 1, "records": records})
    project = fragment.parents[2]

    with pytest.raises(ValueError, match="blueprint validation blocked"):
        seal_crown_blueprint(tmp_path)

    assert not (project / "project_artifact_index.yml").exists()
    assert not (
        project / "project_brain" / "blueprint_validation_receipt.yml"
    ).exists()


def test_blueprint_validation_blocks_malformed_model_numbers_without_traceback(
    tmp_path: Path,
) -> None:
    _fragment, _records = _valid_blueprint(tmp_path)
    project = tmp_path / "projects" / "Crown_of_Ash"
    scale_path = project / "production" / "series_scale_decision.yml"
    scale = yaml.safe_load(scale_path.read_text(encoding="utf-8"))
    scale["planned_total_chapters"] = "many"
    scale["parts"][0]["planned_chapters"] = {"invalid": True}
    _write_yaml(scale_path, scale)
    card_path = project / "production" / "chapter_cards" / "ch001.yml"
    card = yaml.safe_load(card_path.read_text(encoding="utf-8"))
    card["chapter"] = "first"
    _write_yaml(card_path, card)

    result = validate_crown_blueprint(tmp_path)

    assert result["status"] == "blocked"
    assert any("invalid_integer" in issue for issue in result["issues"])


def test_fact_distillation_requires_unique_ids_conclusions_and_closed_schema(
    tmp_path: Path,
) -> None:
    _fragment, _records = _valid_blueprint(tmp_path)
    distillation_path = (
        tmp_path
        / "projects"
        / "Crown_of_Ash"
        / "project_brain"
        / "fact_distillation.yml"
    )
    distillation = yaml.safe_load(distillation_path.read_text(encoding="utf-8"))
    distillation["facts"] = [
        {
            "id": "fact.duplicate",
            "source_hashes": ["a" * 64],
            "conflict_status": "resolved",
            "conflict_conclusion": "",
            "legacy_excerpt": "forbidden prose",
        },
        {
            "id": "fact.duplicate",
            "source_hashes": ["a" * 64],
            "conflict_status": "resolved",
            "conflict_conclusion": "same id",
        },
    ]
    _write_yaml(distillation_path, distillation)

    result = validate_crown_blueprint(tmp_path)

    assert result["status"] == "blocked"
    assert "fact_distillation:duplicate_id:fact.duplicate" in result["issues"]
    assert "fact_distillation:missing_conflict_conclusion:fact.duplicate" in result["issues"]
    assert "fact_distillation:forbidden_field:fact.duplicate:legacy_excerpt" in result["issues"]


def test_blueprint_seal_binds_distillation_and_fact_snapshot_hashes(
    tmp_path: Path,
) -> None:
    _fragment, _records = _valid_blueprint(tmp_path)
    seal_crown_blueprint(tmp_path)
    project = tmp_path / "projects" / "Crown_of_Ash"
    distillation_path = project / "project_brain" / "fact_distillation.yml"
    distillation = yaml.safe_load(distillation_path.read_text(encoding="utf-8"))
    distillation["facts"][0]["value"] = {"worldline_ref": "worldline.alternate"}
    _write_yaml(distillation_path, distillation)

    from agent_runtime.narrative.blueprint_validation import validate_blueprint_seal

    result = validate_blueprint_seal(tmp_path)

    assert result["status"] == "blocked"
    assert "blueprint_artifact_hash_drift" in result["issues"]
