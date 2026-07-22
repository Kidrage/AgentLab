from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

import agent_runtime.narrative.state_store as state_store_module
from agent_runtime.narrative.state_store import (
    NarrativeStateConflict,
    NarrativeStateStore,
    narrative_payload_sha256,
)
from agent_runtime.narrative.production.chapter_engine import ChapterEngine, ChapterRequest
from agent_runtime.narrative.production.delta_verifier import verify_state_delta
from agent_runtime.program_manager.project_fact_state import (
    ProjectFactBootstrapRequired,
    rebuild_project_fact_snapshot,
)


def _source(path: Path) -> dict[str, str]:
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _verified_commit(
    *,
    root: Path,
    previous_state_sha256: str,
    state_delta: dict,
    seal_status: str = "accepted",
    artifact_sha256: str = "a" * 64,
    brief_sha256: str = "b" * 64,
    source_projection_sha256: str = "e" * 64,
    verification_result_sha256: str = "f" * 64,
) -> dict:
    state_delta_sha256 = narrative_payload_sha256(state_delta)
    binding = {
        "artifact_sha256": artifact_sha256,
        "brief_sha256": brief_sha256,
        "source_projection_sha256": source_projection_sha256,
        "verification_result_sha256": verification_result_sha256,
        "state_delta_sha256": state_delta_sha256,
    }
    receipts = root / "receipts"
    receipts.mkdir(exist_ok=True)
    seal_receipt = receipts / "seal.yml"
    seal_receipt.write_text(
        yaml.safe_dump({"status": seal_status, **binding}, sort_keys=True),
        encoding="utf-8",
    )
    verification_receipt = receipts / "delta.yml"
    verification_receipt.write_text(
        yaml.safe_dump(
            {
                "status": "pass",
                "source_projection_sha256": source_projection_sha256,
                "verification_result_sha256": verification_result_sha256,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return {
        "schema_version": "verified-chapter-commit/v1",
        "project": "Crown_of_Ash",
        "chapter": 1,
        "artifact_sha256": binding["artifact_sha256"],
        "brief_sha256": binding["brief_sha256"],
        "source_projection_sha256": source_projection_sha256,
        "state_delta_sha256": state_delta_sha256,
        "seal": {
            "status": seal_status,
            "receipt_path": seal_receipt.relative_to(root).as_posix(),
            "receipt_sha256": hashlib.sha256(seal_receipt.read_bytes()).hexdigest(),
            **binding,
        },
        "delta_verification": {
            "status": "pass",
            "receipt_path": verification_receipt.relative_to(root).as_posix(),
            "receipt_sha256": hashlib.sha256(
                verification_receipt.read_bytes()
            ).hexdigest(),
            "source_projection_sha256": source_projection_sha256,
            "verification_result_sha256": verification_result_sha256,
        },
        "previous_state_sha256": previous_state_sha256,
        "state_delta": state_delta,
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


def test_idempotent_retry_repairs_snapshot_after_projection_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "characters.yml"
    source.write_text("lia:\n  age: 18\n", encoding="utf-8")
    store = NarrativeStateStore(tmp_path / "brain", project="Crown_of_Ash")
    manifest = {
        "schema_version": "narrative-bootstrap/v1",
        "project": "Crown_of_Ash",
        "precedence": ["canonical"],
        "sources": [_source(source)],
        "base_state": {"characters": {"char_lia": {"age": 18}}},
    }
    original_write = state_store_module.atomic_write_yaml
    attempts = 0

    def fail_once(path: Path, value: dict) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("simulated projection failure")
        original_write(path, value)

    monkeypatch.setattr(state_store_module, "atomic_write_yaml", fail_once)

    with pytest.raises(OSError, match="projection failure"):
        store.bootstrap(manifest)
    assert len(store.events_path.read_text(encoding="utf-8").splitlines()) == 1
    assert not store.snapshot_path.exists()

    receipt = store.bootstrap(manifest)

    assert receipt["status"] == "bootstrapped"
    assert store.snapshot_path.is_file()
    assert store.read()["characters"]["char_lia"]["age"] == 18


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
    commit = _verified_commit(
        root=tmp_path,
        previous_state_sha256=before["state_sha256"],
        state_delta={
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
    )

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
    commit = _verified_commit(
        root=tmp_path,
        previous_state_sha256="9" * 64,
        state_delta={},
        seal_status="rejected",
    )

    with pytest.raises(NarrativeStateConflict, match="accepted seal"):
        store.commit(commit)
    assert store.read()["event_count"] == 1


def test_commit_rejects_state_delta_not_bound_into_accepted_seal(
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
    commit = _verified_commit(
        root=tmp_path,
        previous_state_sha256=store.read()["state_sha256"],
        state_delta={"world_updates": [{"axis": "ash", "value": "awake"}]},
    )
    commit["seal"]["source_projection_sha256"] = "0" * 64

    with pytest.raises(NarrativeStateConflict, match="seal narrative binding"):
        store.commit(commit)

    assert store.read()["event_count"] == 1


def test_chapter_engine_binds_commit_to_current_brief_projection_and_verification(
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
    brief = {
        "schema_version": 2,
        "chapter_id": 1,
        "primary_function": "plot",
        "pov": "char_kain",
        "opposing_wants": "验证灰痕与避开登记",
        "turn": "灰痕回应炉温",
        "cost": "凯恩失去铁匠身份",
        "reader_question": "谁提前登记了凯恩？",
        "must_preserve": [],
        "creative_freedom": [],
        "source_hashes": {
            str(source.resolve()): hashlib.sha256(source.read_bytes()).hexdigest()
        },
    }
    prose = "炉火忽然变冷。\n"
    artifact_sha256 = hashlib.sha256(prose.encode("utf-8")).hexdigest()
    projection = {
        "schema_version": 2,
        "chapter_id": 1,
        "prose_sha256": artifact_sha256,
        "hard_facts": [
            {
                "category": "world_rule",
                "evidence_location": "L1",
                "content": "炉火忽然变冷",
            }
        ],
        "soft_observations": [],
        "node_local_retry_only": True,
    }
    prose_path = tmp_path / "fiction_draft.md"
    prose_path.write_text(prose, encoding="utf-8")
    verification = verify_state_delta(prose_path, projection)
    state_updates = {
        "world_updates": [{"axis": "forge_temperature", "value": "cold"}]
    }
    binding = {
        "artifact_sha256": artifact_sha256,
        "brief_sha256": narrative_payload_sha256(brief),
        "source_projection_sha256": narrative_payload_sha256(projection),
        "verification_result_sha256": narrative_payload_sha256(verification),
        "state_delta_sha256": narrative_payload_sha256(state_updates),
    }
    commit = _verified_commit(
        root=tmp_path,
        previous_state_sha256=store.read()["state_sha256"],
        state_delta=state_updates,
        artifact_sha256=binding["artifact_sha256"],
        brief_sha256=binding["brief_sha256"],
        source_projection_sha256=binding["source_projection_sha256"],
        verification_result_sha256=binding["verification_result_sha256"],
    )
    tampered = {**commit, "source_projection_sha256": "0" * 64}

    blocked = ChapterEngine.run(
        ChapterRequest(
            chapter_id=1,
            creative_brief=brief,
            writer_output={"fiction_draft.md": prose},
            provider="deepseek",
            model="deepseek-v4-pro",
            call_id="call-bound-commit",
            prose_selected=True,
            state_delta=projection,
            narrative_state_store=store,
            verified_commit=tampered,
        )
    )
    assert blocked.status == "blocked"
    assert blocked.issues == ["state_commit_current_run_binding_mismatch"]
    assert store.read()["event_count"] == 1

    accepted = ChapterEngine.run(
        ChapterRequest(
            chapter_id=1,
            creative_brief=brief,
            writer_output={"fiction_draft.md": prose},
            provider="deepseek",
            model="deepseek-v4-pro",
            call_id="call-bound-commit",
            prose_selected=True,
            state_delta=projection,
            narrative_state_store=store,
            verified_commit=commit,
        )
    )
    assert accepted.status == "pass"
    assert accepted.state_commit_receipt["status"] == "committed"
    assert store.read()["world_axes"]["forge_temperature"] == "cold"


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
    bootstrap_bytes = store.events_path.read_bytes()

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
    assert store.events_path.read_bytes().startswith(bootstrap_bytes)


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
