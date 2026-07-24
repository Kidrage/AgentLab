from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_runtime.project_agents import AgentManifest
from agent_runtime.project_truth import (
    ChangeSet,
    FactChange,
    ProjectTruthConflict,
    ProjectTruthAuthorizationError,
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


def test_canonical_boundary_blocks_agent_outside_manifest_write_scope(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    initial = store.initialize("dark_fantasy_rpg")
    registered = store.commit(
        ChangeSet(
            project_id="dark_fantasy_rpg",
            expected_snapshot_id=initial.current_snapshot_id,
            actor_id="user",
            idempotency_key="register-character",
            resources=(
                ResourceChange(
                    key="agents.manifest.character",
                    content=AgentManifest(
                        id="character",
                        name="Character Agent",
                        version="1.0.0",
                        role="character_architect",
                        description="Maintain character state.",
                        responsibilities=("Maintain characters.",),
                        runtime_role="Researcher",
                        read_scope=("character.*",),
                        write_scope=("character.*",),
                        approval_scope=(),
                        knowledge_binding={
                            "namespace": "agent.dark_fantasy_rpg.character",
                            "documents": (),
                            "artifacts": (),
                        },
                        model_profile="balanced",
                        tool_permission=("knowledge.read",),
                        budget_profile="standard",
                        status="active",
                        acceptance_rules=("character_consistent",),
                    ).to_dict(),
                ),
            ),
        )
    )

    with pytest.raises(
        ProjectTruthAuthorizationError, match="outside contract"
    ):
        store.commit(
            ChangeSet(
                project_id="dark_fantasy_rpg",
                expected_snapshot_id=registered.snapshot_id,
                actor_id="agent.character",
                idempotency_key="illegal-world-write",
                facts=(
                    FactChange(
                        key="world.rules.magic",
                        value="blood",
                        owner="agent.character",
                    ),
                ),
            )
        )


def test_reserved_agent_manifest_namespace_rejects_malformed_resource(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    initial = store.initialize("dark_fantasy_rpg")

    with pytest.raises(
        ProjectTruthValidationError, match="must use AgentManifest"
    ):
        store.commit(
            ChangeSet(
                project_id="dark_fantasy_rpg",
                expected_snapshot_id=initial.current_snapshot_id,
                actor_id="user",
                idempotency_key="malformed-agent",
                resources=(
                    ResourceChange(
                        key="agents.manifest.character",
                        content={},
                    ),
                ),
            )
        )


def test_rollback_restores_prior_truth_as_a_new_auditable_snapshot(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    initial = store.initialize("dark_fantasy_rpg")
    first = store.commit(
        ChangeSet(
            project_id="dark_fantasy_rpg",
            expected_snapshot_id=initial.current_snapshot_id,
            actor_id="user",
            idempotency_key="baseline",
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
            idempotency_key="revision",
            facts=(
                FactChange(
                    key="novel.total_word_count",
                    value=150_000,
                    owner="project.editorial",
                ),
                FactChange(
                    key="novel.temporary_note",
                    value="remove me",
                    owner="project.editorial",
                ),
            ),
        )
    )

    restored = store.rollback(
        first.snapshot_id,
        expected_snapshot_id=second.snapshot_id,
        actor_id="user",
        idempotency_key="restore-baseline",
    )
    retried = store.rollback(
        first.snapshot_id,
        expected_snapshot_id=restored.snapshot_id,
        actor_id="user",
        idempotency_key="restore-baseline",
    )

    current = store.current()
    assert retried.receipt_id == restored.receipt_id
    assert restored.snapshot_id == current.snapshot_id
    assert current.parent_snapshot_id == second.snapshot_id
    assert current.facts["novel.total_word_count"].value == 120_000
    assert "novel.temporary_note" not in current.facts
    assert current.generation == 3


def test_rollback_restores_agent_state_with_monotonic_manifest_revision(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    initial = store.initialize("dark_fantasy_rpg")
    manifest = AgentManifest(
        id="character",
        name="Character Agent",
        version="1.0.0",
        role="character_architect",
        description="Maintain character state.",
        responsibilities=("Maintain characters.",),
        runtime_role="Researcher",
        read_scope=("character.*",),
        write_scope=("character.*",),
        approval_scope=(),
        knowledge_binding={
            "namespace": "agent.dark_fantasy_rpg.character",
            "documents": (),
            "artifacts": (),
        },
        model_profile="balanced",
        tool_permission=("knowledge.read",),
        budget_profile="standard",
        status="active",
        acceptance_rules=("character_consistent",),
    )
    registered = store.commit(
        ChangeSet(
            project_id="dark_fantasy_rpg",
            expected_snapshot_id=initial.current_snapshot_id,
            actor_id="user",
            idempotency_key="register-character-for-rollback",
            resources=(
                ResourceChange(
                    key="agents.manifest.character",
                    content=manifest.to_dict(),
                ),
            ),
            facts=(
                FactChange(
                    key="character.aria.state",
                    value="baseline",
                    owner="agent.character",
                ),
            ),
        )
    )
    paused = manifest.evolve(status="paused")
    paused_receipt = store.commit(
        ChangeSet(
            project_id="dark_fantasy_rpg",
            expected_snapshot_id=registered.snapshot_id,
            actor_id="user",
            idempotency_key="pause-character-for-rollback",
            resources=(
                ResourceChange(
                    key="agents.manifest.character",
                    content=paused.to_dict(),
                ),
            ),
        )
    )
    resumed = paused.evolve(status="active")
    changed = store.commit(
        ChangeSet(
            project_id="dark_fantasy_rpg",
            expected_snapshot_id=paused_receipt.snapshot_id,
            actor_id="user",
            idempotency_key="resume-and-change-character",
            resources=(
                ResourceChange(
                    key="agents.manifest.character",
                    content=resumed.to_dict(),
                ),
            ),
            facts=(
                FactChange(
                    key="character.aria.state",
                    value="changed",
                    owner="agent.character",
                ),
            ),
        )
    )

    restored = store.rollback(
        registered.snapshot_id,
        expected_snapshot_id=changed.snapshot_id,
        actor_id="user",
        idempotency_key="restore-agent-baseline",
    )
    retried = store.rollback(
        registered.snapshot_id,
        expected_snapshot_id=restored.snapshot_id,
        actor_id="user",
        idempotency_key="restore-agent-baseline",
    )

    current = store.current()
    restored_manifest = AgentManifest.from_dict(
        current.resources["agents.manifest.character"].content
    )
    assert retried == restored
    assert restored_manifest.status == "active"
    assert restored_manifest.manifest_revision == 4
    assert current.facts["character.aria.state"].value == "baseline"
    assert store.audit()["status"] == "pass"


def test_rollback_before_agent_creation_archives_instead_of_removing_manifest(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    initial = store.initialize("dark_fantasy_rpg")
    manifest = AgentManifest(
        id="character",
        name="Character Agent",
        version="1.0.0",
        role="character_architect",
        description="Maintain character state.",
        responsibilities=("Maintain characters.",),
        runtime_role="Researcher",
        read_scope=("character.*",),
        write_scope=("character.*",),
        approval_scope=(),
        knowledge_binding={
            "namespace": "agent.dark_fantasy_rpg.character",
            "documents": (),
            "artifacts": (),
        },
        model_profile="balanced",
        tool_permission=("knowledge.read",),
        budget_profile="standard",
        status="active",
        acceptance_rules=("character_consistent",),
    )
    registered = store.commit(
        ChangeSet(
            project_id="dark_fantasy_rpg",
            expected_snapshot_id=initial.current_snapshot_id,
            actor_id="user",
            idempotency_key="register-character-before-rollback",
            resources=(
                ResourceChange(
                    key="agents.manifest.character",
                    content=manifest.to_dict(),
                ),
            ),
        )
    )

    store.rollback(
        initial.current_snapshot_id,
        expected_snapshot_id=registered.snapshot_id,
        actor_id="user",
        idempotency_key="rollback-before-agent-creation",
    )

    archived = AgentManifest.from_dict(
        store.current().resources["agents.manifest.character"].content
    )
    assert archived.status == "archived"
    assert archived.manifest_revision == 2
