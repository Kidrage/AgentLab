from __future__ import annotations

from pathlib import Path
import hashlib
import os
import re
import shutil
import subprocess

import pytest
import yaml

from agent_runtime.narrative.blueprint_validation import (
    materialize_crown_blueprint,
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
    evidence = [
        {
            "source": "distilled-facts",
            "source_hashes": ["a" * 64],
            "conclusion": "density supports decision",
        }
    ]
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
            "project": "Crown_of_Ash",
            "status": "approved",
            "decision_maker": "AgentLab.Supervisor",
            "legacy_prose_retained": False,
            "sources": [
                {
                    "path": "production/bible/origin.yml",
                    "sha256": "a" * 64,
                    "status": "verified",
                }
            ],
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
            "conflicts": [],
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
    for record in records:
        record["source_hashes"] = ["a" * 64]
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


def _bundle_from_valid_blueprint(root: Path, task_id: str = "task_parent") -> Path:
    project = root / "projects" / "Crown_of_Ash"
    canonical_index = yaml.safe_load(
        (project / "production" / "canonical" / "index.yml").read_text()
    )
    fragments = [
        {
            "path": item["path"],
            "document": yaml.safe_load((project / item["path"]).read_text()),
        }
        for item in canonical_index["fragments"]
    ]
    bundle = {
        "schema_version": 1,
        "project": "Crown_of_Ash",
        "status": "approved",
        "candidate_only": True,
        "series_scale_decision": yaml.safe_load(
            (project / "production" / "series_scale_decision.yml").read_text()
        ),
        "chapter_length_policy": yaml.safe_load(
            (project / "production" / "chapter_length_policy.yml").read_text()
        ),
        "canonical_fragments": fragments,
        "chapter_cards": {
            "index": yaml.safe_load(
                (project / "production" / "chapter_cards" / "index.yml").read_text()
            ),
            "cards": [
                yaml.safe_load(
                    (
                        project
                        / "production"
                        / "chapter_cards"
                        / f"ch{chapter:03d}.yml"
                    ).read_text()
                )
                for chapter in range(1, 21)
            ],
        },
    }
    bundle_path = project / "runs" / task_id / "artifacts" / "blueprint_bundle.yml"
    _write_yaml(bundle_path, bundle)
    shutil.rmtree(project / "production")
    return bundle_path


def test_materializes_validated_bundle_from_parent_task_atomically(tmp_path: Path) -> None:
    _valid_blueprint(tmp_path)
    bundle = _bundle_from_valid_blueprint(tmp_path)

    result = materialize_crown_blueprint(tmp_path, bundle_path=bundle)

    assert result["status"] == "materialized"
    assert result["validation"]["status"] == "pass"
    assert validate_crown_blueprint(tmp_path)["status"] == "pass"


def test_materializer_rejects_unsafe_fragment_without_writing_production(
    tmp_path: Path,
) -> None:
    _valid_blueprint(tmp_path)
    bundle = _bundle_from_valid_blueprint(tmp_path)
    data = yaml.safe_load(bundle.read_text())
    data["canonical_fragments"][0]["path"] = "../outside.yml"
    _write_yaml(bundle, data)

    with pytest.raises(ValueError, match="unsafe canonical fragment"):
        materialize_crown_blueprint(tmp_path, bundle_path=bundle)

    assert not (tmp_path / "projects" / "Crown_of_Ash" / "production").exists()


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


def test_blocks_blueprint_evidence_not_bound_to_distilled_sources(tmp_path: Path) -> None:
    fragment, records = _valid_blueprint(tmp_path)
    project = tmp_path / "projects" / "Crown_of_Ash"
    scale = yaml.safe_load(
        (project / "production" / "series_scale_decision.yml").read_text()
    )
    scale["evidence"][0]["source_hashes"] = ["b" * 64]
    _write_yaml(project / "production" / "series_scale_decision.yml", scale)
    records[0]["source_hashes"] = ["b" * 64]
    _write_yaml(fragment, {"schema_version": 1, "records": records})
    _write_yaml(
        fragment.parent / "index.yml",
        {
            "schema_version": 1,
            "fragments": [
                {
                    "path": "production/canonical/core.yml",
                    "sha256": hashlib.sha256(fragment.read_bytes()).hexdigest(),
                }
            ],
        },
    )

    result = validate_crown_blueprint(tmp_path)

    assert "series_scale:unbound_evidence_hash:1" in result["issues"]
    assert "canonical:unbound_source_hash:character.kane" in result["issues"]


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
    stdout = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", result.stdout)
    assert "--chapter-start" in stdout
    assert "--chapter-end" in stdout

    authority_result = subprocess.run(
        [
            str(root / "agentlab.sh"),
            "narrative",
            "commit-fact-authority",
            "--help",
        ],
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
    assert authority_result.returncode == 0, authority_result.stderr
    authority_stdout = re.sub(
        r"\x1b\[[0-?]*[ -/]*[@-~]",
        "",
        authority_result.stdout,
    )
    assert "--project" in authority_stdout


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


def test_seal_blueprint_preserves_all_hash_valid_current_artifacts(
    tmp_path: Path,
) -> None:
    fragment, _records = _valid_blueprint(tmp_path)
    project = fragment.parents[2]
    authority = project / "production" / "fact_authority.yml"
    authority.write_text(
        "schema_version: narrative-fact-authority/v1\n"
        "project: Crown_of_Ash\n"
        "authority_id: crown-character-age-standard\n"
        "revision: 1\n"
        "status: active\n"
        "effective_at: '2026-07-23T00:00:00Z'\n"
        "supersedes_authority_sha256: null\n"
        "facts:\n"
        "- fact_id: char_lia.age\n"
        "  target: characters\n"
        "  entity_id: char_lia\n"
        "  field: age\n"
        "  value: 18\n",
        encoding="utf-8",
    )
    authority_sha256 = hashlib.sha256(authority.read_bytes()).hexdigest()
    unrelated = project / "production" / "old_baseline.yml"
    unrelated.write_text("status: current\n", encoding="utf-8")
    _write_yaml(
        project / "project_artifact_index.yml",
        {
            "schema_version": 1,
            "project": "Crown_of_Ash",
            "artifacts": [
                {
                    "artifact_id": "crown_fact_authority_01",
                    "status": "current",
                    "production_path": "production/fact_authority.yml",
                    "production_sha256": authority_sha256,
                    "evidence_only": False,
                    "authority_id": "crown-character-age-standard",
                    "authority_revision": 1,
                },
                {
                    "artifact_id": "old_character_age_baseline",
                    "status": "current",
                    "production_path": "production/old_baseline.yml",
                    "production_sha256": hashlib.sha256(
                        unrelated.read_bytes()
                    ).hexdigest(),
                    "evidence_only": False,
                }
            ],
            "current": {
                "crown_fact_authority_01": "production/fact_authority.yml",
                "old_character_age_baseline": "production/old_baseline.yml",
            },
        },
    )

    seal_crown_blueprint(tmp_path, project="Crown_of_Ash")

    artifact_index = yaml.safe_load(
        (project / "project_artifact_index.yml").read_text(encoding="utf-8")
    )
    by_id = {item["artifact_id"]: item for item in artifact_index["artifacts"]}
    assert by_id["crown_fact_authority_01"]["production_sha256"] == authority_sha256
    assert (
        artifact_index["current"]["crown_fact_authority_01"]
        == "production/fact_authority.yml"
    )
    assert (
        by_id["old_character_age_baseline"]["production_sha256"]
        == hashlib.sha256(unrelated.read_bytes()).hexdigest()
    )
    assert (
        artifact_index["current"]["old_character_age_baseline"]
        == "production/old_baseline.yml"
    )


def test_seal_blueprint_registers_candidate_source_lineage(tmp_path: Path) -> None:
    _fragment, _records = _valid_blueprint(tmp_path)
    task_id = "task_blueprint"
    source_rel = "artifacts/blueprint_bundle.corrected.yml"
    source = (
        tmp_path
        / "projects"
        / "Crown_of_Ash"
        / "runs"
        / task_id
        / source_rel
    )
    source.parent.mkdir(parents=True)
    source.write_text("status: approved\n", encoding="utf-8")

    seal_crown_blueprint(
        tmp_path,
        source_task=task_id,
        source_run_artifact=source_rel,
    )

    artifact_index = yaml.safe_load(
        (
            tmp_path
            / "projects"
            / "Crown_of_Ash"
            / "project_artifact_index.yml"
        ).read_text(encoding="utf-8")
    )
    assert all(item["source_task"] == task_id for item in artifact_index["artifacts"])
    assert all(
        item["source_run_artifact"] == source_rel
        for item in artifact_index["artifacts"]
    )


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
