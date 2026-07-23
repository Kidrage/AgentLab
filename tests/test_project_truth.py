from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_runtime.project_truth import (
    ChangeSet,
    FactChange,
    ProjectTruthConflict,
    ProjectTruthIntegrityError,
    ProjectTruthStore,
    ProjectTruthValidationError,
    ResourceChange,
)


def _store(tmp_path: Path) -> ProjectTruthStore:
    project_root = tmp_path / "projects" / "dark_fantasy_rpg"
    project_root.mkdir(parents=True)
    return ProjectTruthStore(project_root)


def test_commit_replaces_current_fact_and_preserves_immutable_history(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    initial = store.initialize("dark_fantasy_rpg")

    first = store.commit(
        ChangeSet(
            project_id="dark_fantasy_rpg",
            expected_snapshot_id=initial.current_snapshot_id,
            actor_id="user",
            idempotency_key="set-length-v1",
            reason="Set the first accepted project length.",
            facts=(
                FactChange(
                    key="novel.total_word_count",
                    value=120_000,
                    owner="project.editorial",
                ),
            ),
        )
    )
    second = store.commit(
        ChangeSet(
            project_id="dark_fantasy_rpg",
            expected_snapshot_id=first.snapshot_id,
            actor_id="user",
            idempotency_key="set-length-v2",
            reason="Approve the revised project length.",
            facts=(
                FactChange(
                    key="novel.total_word_count",
                    value=150_000,
                    owner="project.editorial",
                ),
            ),
        )
    )

    current = store.current()
    assert current.snapshot_id == second.snapshot_id
    assert current.facts["novel.total_word_count"].value == 150_000
    assert list(current.facts) == ["novel.total_word_count"]
    assert [item.value for item in store.fact_history("novel.total_word_count")] == [
        150_000,
        120_000,
    ]

    pointer = yaml.safe_load(
        (store.project_root / "project_truth.yml").read_text(encoding="utf-8")
    )
    assert pointer["current_snapshot_id"] == second.snapshot_id
    assert len(list((store.truth_root / "snapshots").glob("*.yml"))) == 3


def test_stale_compare_and_swap_fails_without_changing_current_truth(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    initial = store.initialize("dark_fantasy_rpg")
    accepted = store.commit(
        ChangeSet(
            project_id="dark_fantasy_rpg",
            expected_snapshot_id=initial.current_snapshot_id,
            actor_id="user",
            idempotency_key="accepted-world-rule",
            resources=(
                ResourceChange(
                    key="world.rules.magic",
                    content={"cost": "memory"},
                ),
            ),
        )
    )

    with pytest.raises(ProjectTruthConflict, match="stale canonical snapshot"):
        store.commit(
            ChangeSet(
                project_id="dark_fantasy_rpg",
                expected_snapshot_id=initial.current_snapshot_id,
                actor_id="agent.world",
                idempotency_key="stale-world-rule",
                resources=(
                    ResourceChange(
                        key="world.rules.magic",
                        content={"cost": "blood"},
                    ),
                ),
            )
        )

    assert store.current().snapshot_id == accepted.snapshot_id
    assert store.current().resources["world.rules.magic"].content == {
        "cost": "memory"
    }


def test_duplicate_semantic_keys_are_rejected_before_pointer_update(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    initial = store.initialize("dark_fantasy_rpg")

    with pytest.raises(ProjectTruthValidationError, match="duplicate fact key"):
        store.commit(
            ChangeSet(
                project_id="dark_fantasy_rpg",
                expected_snapshot_id=initial.current_snapshot_id,
                actor_id="user",
                idempotency_key="ambiguous-length",
                facts=(
                    FactChange(
                        key="novel.total_word_count",
                        value=120_000,
                        owner="project.editorial",
                    ),
                    FactChange(
                        key="novel.total_word_count",
                        value=150_000,
                        owner="project.editorial",
                    ),
                ),
            )
        )

    assert store.current().snapshot_id == initial.current_snapshot_id


def test_idempotent_retry_returns_the_original_receipt(tmp_path: Path) -> None:
    store = _store(tmp_path)
    initial = store.initialize("dark_fantasy_rpg")
    change_set = ChangeSet(
        project_id="dark_fantasy_rpg",
        expected_snapshot_id=initial.current_snapshot_id,
        actor_id="user",
        idempotency_key="character-age-v1",
        facts=(
            FactChange(
                key="character.aria.age",
                value=27,
                owner="agent.character",
            ),
        ),
    )

    first = store.commit(change_set)
    retried = store.commit(change_set)

    assert retried == first
    assert len(list((store.truth_root / "receipts").glob("*.yml"))) == 1
    assert store.audit()["status"] == "pass"


def test_invalid_multi_resource_change_does_not_publish_partial_truth(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    initial = store.initialize("dark_fantasy_rpg")

    with pytest.raises(
        ProjectTruthValidationError, match="must be JSON-compatible"
    ):
        store.commit(
            ChangeSet(
                project_id="dark_fantasy_rpg",
                expected_snapshot_id=initial.current_snapshot_id,
                actor_id="user",
                idempotency_key="invalid-batch",
                resources=(
                    ResourceChange(
                        key="world.rules.magic",
                        content={"cost": "memory"},
                    ),
                    ResourceChange(
                        key="characters.aria",
                        content={"unserializable": {object()}},
                    ),
                ),
            )
        )

    assert store.current().snapshot_id == initial.current_snapshot_id
    assert not list((store.truth_root / "objects").rglob("*.json"))


def test_idempotency_key_cannot_be_reused_for_different_content(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    initial = store.initialize("dark_fantasy_rpg")
    store.commit(
        ChangeSet(
            project_id="dark_fantasy_rpg",
            expected_snapshot_id=initial.current_snapshot_id,
            actor_id="user",
            idempotency_key="one-decision",
            facts=(
                FactChange(
                    key="novel.total_word_count",
                    value=120_000,
                    owner="project.editorial",
                ),
            ),
        )
    )

    with pytest.raises(ProjectTruthConflict, match="idempotency key"):
        store.commit(
            ChangeSet(
                project_id="dark_fantasy_rpg",
                expected_snapshot_id=initial.current_snapshot_id,
                actor_id="user",
                idempotency_key="one-decision",
                facts=(
                    FactChange(
                        key="novel.total_word_count",
                        value=150_000,
                        owner="project.editorial",
                    ),
                ),
            )
        )


def test_audit_detects_tampered_content_object(tmp_path: Path) -> None:
    store = _store(tmp_path)
    initial = store.initialize("dark_fantasy_rpg")
    store.commit(
        ChangeSet(
            project_id="dark_fantasy_rpg",
            expected_snapshot_id=initial.current_snapshot_id,
            actor_id="user",
            idempotency_key="world-rule",
            resources=(
                ResourceChange(
                    key="world.rules.magic",
                    content={"cost": "memory"},
                ),
            ),
        )
    )
    object_path = next((store.truth_root / "objects").rglob("*.json"))
    object_path.write_text('{"content":{"cost":"blood"}}', encoding="utf-8")

    with pytest.raises(ProjectTruthIntegrityError, match="hash mismatch"):
        store.audit()
