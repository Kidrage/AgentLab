from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from agent_runtime.narrative.state_store import (
    NarrativeStateConflict,
    NarrativeStateStore,
)
from agent_runtime.program_manager.project_fact_state import (
    ProjectFactBootstrapRequired,
    rebuild_project_fact_snapshot,
)


def _source(path: Path) -> dict[str, str]:
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def test_bootstrap_is_hash_bound_idempotent_and_readable(tmp_path: Path) -> None:
    source = tmp_path / "characters.yml"
    source.write_text("lia:\n  age: 18\n", encoding="utf-8")
    store = NarrativeStateStore(tmp_path / "brain", project="Crown_of_Ash")
    manifest = {
        "schema_version": "narrative-bootstrap/v1",
        "project": "Crown_of_Ash",
        "precedence": ["latest_user_lock", "approved_scale", "canonical"],
        "sources": [_source(source)],
        "base_state": {
            "series": {"planned_total_chapters": 1980},
            "characters": {"char_lia": {"age": 18, "age_class": "adult"}},
        },
    }

    first = store.bootstrap(manifest)
    repeated = store.bootstrap(manifest)
    snapshot = store.read()

    assert repeated == first
    assert snapshot["event_count"] == 1
    assert snapshot["series"]["planned_total_chapters"] == 1980
    assert snapshot["characters"]["char_lia"]["age"] == 18
    assert len(snapshot["state_sha256"]) == 64


def test_only_accepted_hash_bound_chapter_commit_updates_state(tmp_path: Path) -> None:
    source = tmp_path / "canon.yml"
    source.write_text("project: Crown_of_Ash\n", encoding="utf-8")
    store = NarrativeStateStore(tmp_path / "brain", project="Crown_of_Ash")
    store.bootstrap(
        {
            "schema_version": "narrative-bootstrap/v1",
            "project": "Crown_of_Ash",
            "precedence": ["canonical"],
            "sources": [_source(source)],
            "base_state": {},
        }
    )
    before = store.read()
    commit = {
        "schema_version": "verified-chapter-commit/v1",
        "project": "Crown_of_Ash",
        "chapter": 1,
        "artifact_sha256": "a" * 64,
        "brief_sha256": "b" * 64,
        "seal": {"status": "accepted", "receipt_sha256": "c" * 64},
        "delta_verification": {"status": "pass", "receipt_sha256": "d" * 64},
        "previous_state_sha256": before["state_sha256"],
        "state_delta": {
            "character_updates": [
                {"id": "char_kain", "current_goal": "查明灰痕来源"}
            ],
            "foreshadow_updates": [
                {
                    "id": "fs_preprinted_name",
                    "status": "seeded",
                    "next_touch_window": [8, 14],
                }
            ],
            "world_updates": [
                {"axis": "church_surveillance", "value": "named_monitoring"}
            ],
            "style_memory_events": [
                {"kind": "accepted_pattern", "value": "blacksmith_causal_lens"}
            ],
        },
    }

    receipt = store.commit(commit)
    after = store.read()

    assert receipt["status"] == "committed"
    assert after["chapters"]["1"]["artifact_sha256"] == "a" * 64
    assert after["characters"]["char_kain"]["current_goal"] == "查明灰痕来源"
    assert after["foreshadowing"]["fs_preprinted_name"]["status"] == "seeded"
    assert after["world_axes"]["church_surveillance"] == "named_monitoring"
    assert after["style_memory"][0]["kind"] == "accepted_pattern"

    assert store.commit(commit) == receipt


def test_rejected_or_stale_commit_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "canon.yml"
    source.write_text("project: Crown_of_Ash\n", encoding="utf-8")
    store = NarrativeStateStore(tmp_path / "brain", project="Crown_of_Ash")
    store.bootstrap(
        {
            "schema_version": "narrative-bootstrap/v1",
            "project": "Crown_of_Ash",
            "precedence": ["canonical"],
            "sources": [_source(source)],
            "base_state": {},
        }
    )
    commit = {
        "schema_version": "verified-chapter-commit/v1",
        "project": "Crown_of_Ash",
        "chapter": 1,
        "artifact_sha256": "a" * 64,
        "brief_sha256": "b" * 64,
        "seal": {"status": "rejected", "receipt_sha256": "c" * 64},
        "delta_verification": {"status": "pass", "receipt_sha256": "d" * 64},
        "previous_state_sha256": "e" * 64,
        "state_delta": {},
    }

    with pytest.raises(NarrativeStateConflict, match="accepted seal"):
        store.commit(commit)
    assert store.read()["event_count"] == 1


def test_rejected_prose_can_contribute_only_hash_bound_editorial_antipatterns(
    tmp_path: Path,
) -> None:
    source = tmp_path / "canon.yml"
    source.write_text("project: Crown_of_Ash\n", encoding="utf-8")
    store = NarrativeStateStore(tmp_path / "brain", project="Crown_of_Ash")
    store.bootstrap(
        {
            "schema_version": "narrative-bootstrap/v1",
            "project": "Crown_of_Ash",
            "precedence": ["canonical"],
            "sources": [_source(source)],
            "base_state": {},
        }
    )

    receipt = store.record_editorial_memory(
        {
            "schema_version": "editorial-memory-event/v1",
            "project": "Crown_of_Ash",
            "rule_id": "crown-dialogue-quotes-001",
            "memory_kind": "anti_pattern",
            "summary": "明确直接对白必须使用中文双引号，不自动补标点",
            "source_artifact_sha256": "a" * 64,
            "source_disposition": "rejected_pre_v3",
            "source_locator": "audit:first-prose:dialogue",
        }
    )

    assert receipt["status"] == "recorded"
    memory = store.read()["style_memory"][0]
    assert memory["polarity"] == "negative"
    assert memory["source_disposition"] == "rejected_pre_v3"
    assert "prose" not in memory


def test_legacy_fact_snapshot_without_events_cannot_be_overwritten(tmp_path: Path) -> None:
    brain = tmp_path / "brain"
    brain.mkdir()
    snapshot_path = brain / "project_fact_snapshot.yml"
    snapshot_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "project": "Crown_of_Ash",
                "facts": [{"id": "fact_character_lia", "value": {"age": 18}}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    before = snapshot_path.read_bytes()

    with pytest.raises(ProjectFactBootstrapRequired):
        rebuild_project_fact_snapshot(brain, project="Crown_of_Ash")

    assert snapshot_path.read_bytes() == before
