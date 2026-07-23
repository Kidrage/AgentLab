from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from agent_runtime.narrative.crown_v3_migration import (
    build_crown_bootstrap_manifest,
    crown_feedback_memory_records,
)


def _write_yaml(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, allow_unicode=True), encoding="utf-8")


def _write_fact_authority(
    path: Path,
    *,
    facts: list[dict],
    revision: int = 1,
    supersedes_authority_sha256: str | None = None,
    evidence_policy: dict | None = None,
) -> None:
    document = {
        "schema_version": "narrative-fact-authority/v1",
        "project": "Crown_of_Ash",
        "authority_id": "crown-character-age-standard",
        "revision": revision,
        "status": "active",
        "effective_at": "2026-07-23T00:00:00Z",
        "supersedes_authority_sha256": supersedes_authority_sha256,
        "facts": facts,
    }
    if evidence_policy is not None:
        document["evidence_policy"] = evidence_policy
    _write_yaml(path, document)


def _register_fact_authority(project: Path) -> None:
    authority_path = project / "production" / "fact_authority.yml"
    authority = yaml.safe_load(authority_path.read_text(encoding="utf-8"))
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
                    "production_sha256": hashlib.sha256(
                        authority_path.read_bytes()
                    ).hexdigest(),
                    "authority_id": authority["authority_id"],
                    "authority_revision": authority["revision"],
                }
            ],
            "current": {
                "crown_fact_authority_01": "production/fact_authority.yml"
            },
        },
    )


def test_crown_bootstrap_manifest_is_hash_bound_and_locks_approved_scale(
    tmp_path: Path,
) -> None:
    project = tmp_path / "Crown_of_Ash"
    canonical = project / "production" / "canonical"
    _write_yaml(
        project / "production" / "series_scale_decision.yml",
        {
            "planned_total_chapters": 1980,
            "parts": [
                {"part": 1, "chapter_start": 1, "chapter_end": 650},
                {"part": 2, "chapter_start": 651, "chapter_end": 1310},
                {"part": 3, "chapter_start": 1311, "chapter_end": 1980},
            ],
        },
    )
    _write_yaml(canonical / "part_arcs.yml", {"records": []})
    _write_yaml(
        canonical / "characters.yml",
        {
            "records": [
                {
                    "id": "char_lia",
                    "kind": "character",
                    "age": 18,
                    "age_class": "adult",
                    "physique": "naturally_small_thin_fine_boned",
                }
            ]
        },
    )
    for filename in ("relationships.yml", "foreshadowing.yml", "worldlines.yml"):
        _write_yaml(canonical / filename, {"records": []})
    _write_yaml(
        project / "project_brain" / "fact_distillation.yml",
        {"schema_version": 1, "facts": []},
    )
    _write_fact_authority(
        project / "production" / "fact_authority.yml",
        facts=[
            {
                "fact_id": "char_lia.age",
                "target": "characters",
                "entity_id": "char_lia",
                "field": "age",
                "value": 18,
            }
        ],
    )
    _register_fact_authority(project)

    manifest = build_crown_bootstrap_manifest(project)

    assert manifest["base_state"]["series"]["planned_total_chapters"] == 1980
    assert manifest["base_state"]["series"]["macro_arc_count"] == 45
    assert manifest["base_state"]["characters"]["char_lia"]["age"] == 18
    assert len(manifest["sources"]) == 8
    assert all(len(source["sha256"]) == 64 for source in manifest["sources"])
    assert (
        manifest["fact_authority"]["authority_id"]
        == "crown-character-age-standard"
    )
    assert manifest["fact_authority"]["source_path"] == (
        "production/fact_authority.yml"
    )
    assert all(not Path(source["path"]).is_absolute() for source in manifest["sources"])
    assert manifest["base_state"]["series"]["prose_generation_allowed"] is False


def test_crown_bootstrap_rejects_stale_character_age_projection(tmp_path: Path) -> None:
    project = tmp_path / "Crown_of_Ash"
    canonical = project / "production" / "canonical"
    _write_yaml(
        project / "production" / "series_scale_decision.yml",
        {
            "planned_total_chapters": 1980,
            "parts": [
                {"part": 1, "chapter_start": 1, "chapter_end": 650},
                {"part": 2, "chapter_start": 651, "chapter_end": 1310},
                {"part": 3, "chapter_start": 1311, "chapter_end": 1980},
            ],
        },
    )
    _write_yaml(canonical / "part_arcs.yml", {"records": []})
    _write_yaml(
        canonical / "characters.yml",
        {
            "records": [
                {
                    "id": "char_lia",
                    "kind": "character",
                    "age": 18,
                    "age_class": "adult",
                },
                {
                    "id": "char_alicia",
                    "kind": "character",
                    "age": 31,
                    "age_class": "adult",
                },
            ]
        },
    )
    for filename in ("relationships.yml", "foreshadowing.yml", "worldlines.yml"):
        _write_yaml(canonical / filename, {"records": []})
    _write_yaml(
        project / "project_brain" / "fact_distillation.yml",
        {"schema_version": 1, "facts": []},
    )
    _write_fact_authority(
        project / "production" / "fact_authority.yml",
        facts=[
            {
                "fact_id": "char_lia.age",
                "target": "characters",
                "entity_id": "char_lia",
                "field": "age",
                "value": 18,
            },
            {
                "fact_id": "char_alicia.age",
                "target": "characters",
                "entity_id": "char_alicia",
                "field": "age",
                "value": 24,
            },
        ],
    )
    _register_fact_authority(project)

    with pytest.raises(ValueError, match="fact authority projection mismatch"):
        build_crown_bootstrap_manifest(project)


def test_crown_bootstrap_rejects_stale_declared_authority_projection(
    tmp_path: Path,
) -> None:
    project = tmp_path / "Crown_of_Ash"
    canonical = project / "production" / "canonical"
    _write_yaml(
        project / "production" / "series_scale_decision.yml",
        {
            "planned_total_chapters": 1980,
            "parts": [
                {"part": 1, "chapter_start": 1, "chapter_end": 650},
                {"part": 2, "chapter_start": 651, "chapter_end": 1310},
                {"part": 3, "chapter_start": 1311, "chapter_end": 1980},
            ],
        },
    )
    _write_yaml(canonical / "part_arcs.yml", {"records": []})
    _write_yaml(
        canonical / "characters.yml",
        {
            "records": [
                {
                    "id": "char_lia",
                    "kind": "character",
                    "age": 18,
                    "age_class": "adult",
                }
            ]
        },
    )
    for filename in ("relationships.yml", "foreshadowing.yml", "worldlines.yml"):
        _write_yaml(canonical / filename, {"records": []})
    _write_yaml(
        project / "project_brain" / "fact_distillation.yml",
        {"schema_version": 1, "facts": []},
    )
    _write_yaml(
        project / "project_brain" / "narrative_state_snapshot.yml",
        {
            "schema_version": "narrative-state/v3",
            "project": "Crown_of_Ash",
            "characters": {"char_lia": {"age": 16, "age_class": "minor"}},
        },
    )
    _write_fact_authority(
        project / "production" / "fact_authority.yml",
        facts=[
            {
                "fact_id": "char_lia.age",
                "target": "characters",
                "entity_id": "char_lia",
                "field": "age",
                "value": 18,
            },
            {
                "fact_id": "char_lia.age_class",
                "target": "characters",
                "entity_id": "char_lia",
                "field": "age_class",
                "value": "adult",
            },
        ],
        evidence_policy={
            "sole_semantic_authority": "project_brain/narrative_state_events.jsonl",
            "projections": [
                "project_brain/narrative_state_snapshot.yml",
            ],
            "registries": [],
        },
    )
    _register_fact_authority(project)

    with pytest.raises(ValueError, match="fact authority projection mismatch"):
        build_crown_bootstrap_manifest(project)


def test_rejected_chapter_feedback_becomes_traceable_prose_free_memory() -> None:
    records = crown_feedback_memory_records(
        artifact_sha256="a" * 64,
        feedback_sha256="b" * 64,
    )

    assert len(records) == 7
    assert {record["memory_kind"] for record in records} == {
        "anti_pattern",
        "mechanical_policy",
        "editorial_guidance",
    }
    assert all(record["source_disposition"] == "rejected_pre_v3" for record in records)
    assert all(
        not ({"prose", "excerpt", "text"} & set(record)) for record in records
    )
