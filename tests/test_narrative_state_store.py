from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

import agent_runtime.narrative.state_store as state_store_module
from agent_runtime.narrative.state_store import (
    NarrativeStateConflict,
    NarrativeStateIntegrityError,
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


def _register_fact_authority(project_root: Path, authority: Path) -> None:
    document = yaml.safe_load(authority.read_text(encoding="utf-8"))
    (project_root / "project_artifact_index.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "project": "Crown_of_Ash",
                "artifacts": [
                    {
                        "artifact_id": "crown_fact_authority_01",
                        "status": "current",
                        "production_path": "production/fact_authority.yml",
                        "production_sha256": hashlib.sha256(
                            authority.read_bytes()
                        ).hexdigest(),
                        "authority_id": document["authority_id"],
                        "authority_revision": document["revision"],
                    }
                ],
                "current": {
                    "crown_fact_authority_01": "production/fact_authority.yml"
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


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
    chapter: int = 1,
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
    seal_receipt = receipts / f"seal-{chapter:03d}.yml"
    seal_receipt.write_text(
        yaml.safe_dump(
            {
                "schema_version": "narrative-seal-receipt/v1",
                "issuer": "AgentLab.Supervisor",
                "attempt_id": f"supervisor-attempt-{chapter:03d}",
                "evidence_binding_id": f"chapter-{chapter:03d}-evidence-001",
                "status": seal_status,
                **binding,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    verification_receipt = receipts / f"delta-{chapter:03d}.yml"
    verification_receipt.write_text(
        yaml.safe_dump(
            {
                "schema_version": "delta-verification-receipt/v1",
                "issuer": "AgentLab.DeltaVerifier",
                "attempt_id": f"delta-attempt-{chapter:03d}",
                "evidence_binding_id": f"chapter-{chapter:03d}-evidence-001",
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
        "chapter": chapter,
        "artifact_sha256": binding["artifact_sha256"],
        "brief_sha256": binding["brief_sha256"],
        "source_projection_sha256": source_projection_sha256,
        "state_delta_sha256": state_delta_sha256,
        "seal": {
            "status": seal_status,
            "attempt_id": f"supervisor-attempt-{chapter:03d}",
            "evidence_binding_id": f"chapter-{chapter:03d}-evidence-001",
            "receipt_path": seal_receipt.relative_to(root).as_posix(),
            "receipt_sha256": hashlib.sha256(seal_receipt.read_bytes()).hexdigest(),
            **binding,
        },
        "delta_verification": {
            "status": "pass",
            "attempt_id": f"delta-attempt-{chapter:03d}",
            "evidence_binding_id": f"chapter-{chapter:03d}-evidence-001",
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
    event = json.loads(store.events_path.read_text(encoding="utf-8"))
    assert event["payload"]["sources"][0]["path"] == "characters.yml"


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


def test_rollback_to_chapter_changes_active_store_via_immutable_event(
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
    first = store.commit(
        _verified_commit(
            root=tmp_path,
            previous_state_sha256=store.read()["state_sha256"],
            state_delta={
                "world_updates": [{"axis": "stress", "value": 1}]
            },
            chapter=1,
        )
    )
    store.commit(
        _verified_commit(
            root=tmp_path,
            previous_state_sha256=first["state_sha256"],
            state_delta={
                "world_updates": [{"axis": "stress", "value": 2}]
            },
            artifact_sha256="c" * 64,
            brief_sha256="d" * 64,
            source_projection_sha256="1" * 64,
            verification_result_sha256="2" * 64,
            chapter=2,
        )
    )

    receipt = store.rollback_to_chapter(
        1,
        reason="test rollback",
        idempotency_key="rollback-test-1",
    )
    repeated = store.rollback_to_chapter(
        1,
        reason="test rollback",
        idempotency_key="rollback-test-1",
    )
    active = store.read()

    assert receipt["status"] == "rolled_back"
    assert repeated == receipt
    assert active["world_axes"]["stress"] == 1
    assert set(active["chapters"]) == {"1"}
    assert yaml.safe_load(store.snapshot_path.read_text(encoding="utf-8")) == active
    assert len(store.events_path.read_text(encoding="utf-8").splitlines()) == 4

    replacement = store.commit(
        _verified_commit(
            root=tmp_path,
            previous_state_sha256=active["state_sha256"],
            state_delta={
                "world_updates": [{"axis": "stress", "value": "replacement"}]
            },
            artifact_sha256="3" * 64,
            brief_sha256="4" * 64,
            source_projection_sha256="5" * 64,
            verification_result_sha256="6" * 64,
            chapter=2,
        )
    )
    assert replacement["status"] == "committed"
    assert store.read()["world_axes"]["stress"] == "replacement"


def test_repeated_rollback_keeps_superseded_branch_inactive(
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

    first = store.commit(
        _verified_commit(
            root=tmp_path,
            previous_state_sha256=store.read()["state_sha256"],
            state_delta={
                "style_memory_events": [
                    {"kind": "accepted_pattern", "value": "base_branch"}
                ]
            },
            chapter=1,
        )
    )
    store.commit(
        _verified_commit(
            root=tmp_path,
            previous_state_sha256=first["state_sha256"],
            state_delta={
                "style_memory_events": [
                    {"kind": "accepted_pattern", "value": "old_branch"}
                ]
            },
            artifact_sha256="c" * 64,
            brief_sha256="d" * 64,
            source_projection_sha256="1" * 64,
            verification_result_sha256="2" * 64,
            chapter=2,
        )
    )
    store.rollback_to_chapter(
        1,
        reason="replace chapter two",
        idempotency_key="rollback-old-ch2",
    )
    replacement = store.commit(
        _verified_commit(
            root=tmp_path,
            previous_state_sha256=store.read()["state_sha256"],
            state_delta={
                "style_memory_events": [
                    {"kind": "accepted_pattern", "value": "new_branch"}
                ]
            },
            artifact_sha256="3" * 64,
            brief_sha256="4" * 64,
            source_projection_sha256="5" * 64,
            verification_result_sha256="6" * 64,
            chapter=2,
        )
    )
    store.commit(
        _verified_commit(
            root=tmp_path,
            previous_state_sha256=replacement["state_sha256"],
            state_delta={
                "style_memory_events": [
                    {"kind": "accepted_pattern", "value": "chapter_three"}
                ]
            },
            artifact_sha256="7" * 64,
            brief_sha256="8" * 64,
            source_projection_sha256="9" * 64,
            verification_result_sha256="0" * 64,
            chapter=3,
        )
    )

    store.rollback_to_chapter(
        2,
        reason="remove chapter three",
        idempotency_key="rollback-new-ch3",
    )
    active = store.read()
    active_values = [event["value"] for event in active["style_memory"]]

    assert active_values == ["base_branch", "new_branch"]
    assert "old_branch" not in active_values
    assert set(active["chapters"]) == {"1", "2"}


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


def test_commit_rejects_hash_valid_receipt_from_wrong_issuer(tmp_path: Path) -> None:
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
        state_delta={},
    )
    seal_path = tmp_path / commit["seal"]["receipt_path"]
    receipt = yaml.safe_load(seal_path.read_text(encoding="utf-8"))
    receipt["issuer"] = "Untrusted.SelfSeal"
    seal_path.write_text(yaml.safe_dump(receipt, sort_keys=True), encoding="utf-8")
    commit["seal"]["receipt_sha256"] = hashlib.sha256(
        seal_path.read_bytes()
    ).hexdigest()

    with pytest.raises(NarrativeStateIntegrityError, match="issuer mismatch"):
        store.commit(commit)


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


def test_fact_authority_is_single_lineage_and_reprojects_character_age(
    tmp_path: Path,
) -> None:
    source = tmp_path / "characters.yml"
    source.write_text("alicia:\n  age: 31\n", encoding="utf-8")
    store = NarrativeStateStore(tmp_path / "brain", project="Crown_of_Ash")
    store.bootstrap(
        {
            "schema_version": "narrative-bootstrap/v1",
            "project": "Crown_of_Ash",
            "precedence": ["canonical"],
            "sources": [_source(source)],
            "base_state": {
                "characters": {
                    "char_alicia": {
                        "name": "艾莉希亚·暗焰",
                        "age": 31,
                        "age_class": "adult",
                    }
                }
            },
        }
    )
    authority = tmp_path / "production" / "fact_authority.yml"
    authority.parent.mkdir()
    authority.write_text(
        yaml.safe_dump(
            {
                "schema_version": "narrative-fact-authority/v1",
                "project": "Crown_of_Ash",
                "authority_id": "crown-character-age-standard",
                "revision": 1,
                "status": "active",
                "effective_at": "2026-07-23T00:00:00Z",
                "supersedes_authority_sha256": None,
                "evidence_policy": {
                    "sole_semantic_authority": (
                        "project_brain/narrative_state_events.jsonl"
                    ),
                    "projections": ["characters.yml"],
                    "registries": [],
                },
                "facts": [
                    {
                        "fact_id": "char_alicia.age",
                        "target": "characters",
                        "entity_id": "char_alicia",
                        "field": "age",
                        "value": 24,
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(
        NarrativeStateIntegrityError,
        match="project artifact index",
    ):
        store.commit_fact_authority(authority)
    _register_fact_authority(tmp_path, authority)
    index_path = tmp_path / "project_artifact_index.yml"
    competing_index = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    competing_index["artifacts"].append(
        {
            "artifact_id": "competing_fact_authority",
            "status": "current",
            "production_path": "production/competing_fact_authority.yml",
            "production_sha256": "f" * 64,
            "authority_id": "competing-character-age-standard",
            "authority_revision": 1,
        }
    )
    competing_index["current"]["competing_fact_authority"] = (
        "production/competing_fact_authority.yml"
    )
    index_path.write_text(
        yaml.safe_dump(competing_index, sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(
        NarrativeStateIntegrityError,
        match="exactly one current fact authority",
    ):
        store.commit_fact_authority(authority)
    _register_fact_authority(tmp_path, authority)

    first = store.commit_fact_authority(authority)
    repeated = store.commit_fact_authority(authority)

    snapshot = store.read()
    assert first == repeated
    assert first["status"] == "overridden"
    assert snapshot["characters"]["char_alicia"]["age"] == 24
    assert snapshot["fact_authorities"]["crown-character-age-standard"][
        "source_sha256"
    ] == hashlib.sha256(authority.read_bytes()).hexdigest()
    assert snapshot["event_count"] == 2

    original_authority = authority.read_text(encoding="utf-8")
    authority.write_text(
        original_authority
        .replace("revision: 1", "revision: 2")
        .replace("value: 24", "value: 25")
        .replace(
            "supersedes_authority_sha256: null",
            f"supersedes_authority_sha256: {'f' * 64}",
        ),
        encoding="utf-8",
    )
    _register_fact_authority(tmp_path, authority)

    with pytest.raises(NarrativeStateConflict, match="supersedes"):
        store.commit_fact_authority(authority)

    competing = yaml.safe_load(original_authority)
    competing["authority_id"] = "competing-character-age-standard"
    authority.write_text(
        yaml.safe_dump(competing, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    _register_fact_authority(tmp_path, authority)

    with pytest.raises(NarrativeStateConflict, match="single active"):
        store.commit_fact_authority(authority)


def test_fact_authority_revision_continues_directly_from_bootstrap_metadata(
    tmp_path: Path,
) -> None:
    source = tmp_path / "characters.yml"
    source.write_text("alicia:\n  age: 24\n", encoding="utf-8")
    authority_dir = tmp_path / "production"
    authority_dir.mkdir()
    revision_one = authority_dir / "fact_authority_v1.yml"
    revision_one.write_text(
        yaml.safe_dump(
            {
                "schema_version": "narrative-fact-authority/v1",
                "project": "Crown_of_Ash",
                "authority_id": "crown-character-age-standard",
                "revision": 1,
                "status": "active",
                "effective_at": "2026-07-23T00:00:00Z",
                "supersedes_authority_sha256": None,
                "evidence_policy": {
                    "sole_semantic_authority": (
                        "project_brain/narrative_state_events.jsonl"
                    ),
                    "projections": ["characters.yml"],
                    "registries": [],
                },
                "facts": [
                    {
                        "fact_id": "char_alicia.age",
                        "target": "characters",
                        "entity_id": "char_alicia",
                        "field": "age",
                        "value": 24,
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    revision_one_sha256 = hashlib.sha256(revision_one.read_bytes()).hexdigest()
    store = NarrativeStateStore(tmp_path / "brain", project="Crown_of_Ash")
    store.bootstrap(
        {
            "schema_version": "narrative-bootstrap/v1",
            "project": "Crown_of_Ash",
            "precedence": ["single_active_fact_authority"],
            "sources": [_source(source), _source(revision_one)],
            "base_state": {
                "characters": {"char_alicia": {"age": 24}},
                "fact_authorities": {
                    "crown-character-age-standard": {
                        "revision": 1,
                        "source_path": str(revision_one.resolve()),
                        "source_sha256": revision_one_sha256,
                    }
                },
            },
        }
    )
    bootstrap_event = json.loads(
        store.events_path.read_text(encoding="utf-8").splitlines()[0]
    )
    assert (
        bootstrap_event["payload"]["base_state"]["fact_authorities"][
            "crown-character-age-standard"
        ]["source_path"]
        == "production/fact_authority_v1.yml"
    )
    revision_two = authority_dir / "fact_authority.yml"
    revision_two.write_text(
        revision_one.read_text(encoding="utf-8")
        .replace("revision: 1", "revision: 2")
        .replace("value: 24", "value: 23")
        .replace(
            "supersedes_authority_sha256: null",
            f"supersedes_authority_sha256: {revision_one_sha256}",
        ),
        encoding="utf-8",
    )
    _register_fact_authority(tmp_path, revision_two)

    receipt = store.commit_fact_authority(revision_two)

    snapshot = store.read()
    assert receipt["status"] == "overridden"
    assert snapshot["event_count"] == 2
    assert snapshot["characters"]["char_alicia"]["age"] == 23
    assert snapshot["fact_authorities"] == {
        "crown-character-age-standard": {
            "revision": 2,
            "source_path": "production/fact_authority.yml",
            "source_sha256": hashlib.sha256(revision_two.read_bytes()).hexdigest(),
            "event_id": receipt["event_id"],
        }
    }


def test_verified_commit_projects_long_term_state_into_event_snapshot(
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
    delta = {
        "long_term_schema": "narrative-long-term-delta/v1",
        "character_mind_updates": [
            {
                "id": "char_arya",
                "goals": ["protect the archive"],
                "needs": ["accept help"],
                "plans": ["enter through the cistern"],
                "known_facts": ["fact_gate_locked"],
                "false_beliefs": [],
                "secrets": [],
                "fears": [],
                "resources": ["bronze key"],
                "moral_boundaries": ["will not abandon a child"],
                "offstage_actions": [],
                "next_decision_threshold": "the bell rings twice",
                "evidence_location": "chapter:1:lines:1-8",
            }
        ],
        "relationship_edge_updates": [],
        "narrative_entity_updates": [],
        "promise_updates": [],
        "truth_updates": [],
        "active_supporting_characters": [],
        "offstage_action_updates": [],
        "outline_update": {
            "book": "book_1",
            "part": "part_1",
            "volume": "volume_1",
            "arc": "arc_archive",
            "window": "window_1_25",
            "chapter": 1,
            "scenes": ["scene_cistern"],
        },
        "summary_updates": [],
        "exact_name_updates": [],
    }

    receipt = store.commit(
        _verified_commit(
            root=tmp_path,
            previous_state_sha256=store.read()["state_sha256"],
            state_delta=delta,
        )
    )
    snapshot = store.read()

    assert receipt["status"] == "committed"
    assert snapshot["character_minds"]["char_arya"]["resources"] == [
        "bronze key"
    ]
    assert snapshot["outline_tree"]["current"]["chapter"] == 1
    assert snapshot["last_projection"] == {
        "chapter": 1,
        "prose_sha256": "a" * 64,
        "schema_version": "narrative-long-term-delta/v1",
    }
