from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.narrative.crown_v3_migration import (
    build_crown_bootstrap_manifest,
    crown_feedback_memory_records,
)


def _write_yaml(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, allow_unicode=True), encoding="utf-8")


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

    manifest = build_crown_bootstrap_manifest(project)

    assert manifest["base_state"]["series"]["planned_total_chapters"] == 1980
    assert manifest["base_state"]["series"]["macro_arc_count"] == 45
    assert manifest["base_state"]["characters"]["char_lia"]["age"] == 18
    assert len(manifest["sources"]) == 7
    assert all(len(source["sha256"]) == 64 for source in manifest["sources"])
    assert manifest["base_state"]["series"]["prose_generation_allowed"] is False


def test_rejected_chapter_feedback_becomes_traceable_prose_free_memory() -> None:
    records = crown_feedback_memory_records(
        artifact_sha256="a" * 64,
        feedback_sha256="b" * 64,
    )

    assert len(records) == 6
    assert {record["memory_kind"] for record in records} == {
        "anti_pattern",
        "mechanical_policy",
        "editorial_guidance",
    }
    assert all(record["source_disposition"] == "rejected_pre_v3" for record in records)
    assert all(
        not ({"prose", "excerpt", "text"} & set(record)) for record in records
    )
