from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_runtime.project_agents import (
    AgentContractViolation,
    AgentLifecycle,
    AgentManifest,
    AgentRegistryConflict,
    ProjectAgentFactory,
    ProjectAgentRegistry,
)
from agent_runtime.project_truth import ProjectTruthStore


def _registry(tmp_path: Path) -> tuple[ProjectAgentRegistry, str]:
    root = tmp_path / "projects" / "rpg"
    root.mkdir(parents=True)
    (root / "project.yml").write_text(
        yaml.safe_dump(
            {
                "project_id": "rpg",
                "features": {
                    "project_truth_mode": "enforced",
                    "enable_project_agents": True,
                },
                "workspace": {"isolation": "required"},
            }
        ),
        encoding="utf-8",
    )
    truth = ProjectTruthStore(root)
    pointer = truth.initialize("rpg")
    return ProjectAgentRegistry(truth), pointer.current_snapshot_id


def _character_agent(**overrides: object) -> AgentManifest:
    values = {
        "id": "character",
        "name": "Character Agent",
        "version": "1.0.0",
        "role": "character_architect",
        "description": "Own character state, motivations, and relationships.",
        "responsibilities": (
            "Maintain character state",
            "Validate character motivation",
        ),
        "runtime_role": "Researcher",
        "read_scope": ("world.rules.*", "character.*"),
        "write_scope": ("character.*",),
        "approval_scope": (),
        "knowledge_binding": {
            "namespace": "agent.rpg.character",
            "documents": ("characters/**",),
            "artifacts": (),
        },
        "model_profile": "balanced",
        "tool_permission": ("knowledge.read",),
        "budget_profile": "standard",
        "status": "active",
        "acceptance_rules": ("character_state_is_consistent",),
        "collaboration": {"consults": ("world",), "reviewed_by": ("reviewer",)},
    }
    values.update(overrides)
    return AgentManifest(**values)


def test_registry_creates_explicit_versioned_agent_resource(tmp_path: Path) -> None:
    registry, snapshot_id = _registry(tmp_path)

    receipt = registry.register(
        _character_agent(),
        expected_snapshot_id=snapshot_id,
        actor_id="user",
        source="user",
        approved=True,
    )

    stored = registry.get("character")
    assert stored.id == "character"
    assert stored.manifest_revision == 1
    assert stored.status == "active"
    assert [agent.id for agent in registry.list()] == ["character"]
    assert registry.truth.current().snapshot_id == receipt.snapshot_id
    assert "agents.manifest.character" in registry.truth.current().resources


def test_registry_rejects_stale_or_implicit_agent_writes(tmp_path: Path) -> None:
    registry, snapshot_id = _registry(tmp_path)
    registry.register(
        _character_agent(),
        expected_snapshot_id=snapshot_id,
        actor_id="user",
        source="user",
        approved=True,
    )

    registry.assert_can_write("character", "character.aria.state")
    with pytest.raises(AgentContractViolation, match="outside write scope"):
        registry.assert_can_write("character", "world.rules.magic")
    with pytest.raises(AgentContractViolation, match="not registered"):
        registry.assert_can_write("unregistered-agent", "character.aria.state")

    with pytest.raises(AgentRegistryConflict, match="stale canonical snapshot"):
        registry.register(
            _character_agent(id="timeline", name="Timeline Agent"),
            expected_snapshot_id=snapshot_id,
            actor_id="user",
            source="user",
            approved=True,
        )


def test_lifecycle_pause_resume_replace_and_archive_are_revisioned(
    tmp_path: Path,
) -> None:
    registry, snapshot_id = _registry(tmp_path)
    created = registry.register(
        _character_agent(),
        expected_snapshot_id=snapshot_id,
        actor_id="user",
        source="user",
        approved=True,
    )
    lifecycle = AgentLifecycle(registry)

    paused = lifecycle.pause(
        "character",
        expected_snapshot_id=created.snapshot_id,
        actor_id="user",
    )
    assert registry.get("character").status == "paused"
    assert registry.get("character").manifest_revision == 2
    with pytest.raises(AgentContractViolation, match="not active"):
        registry.assert_can_write("character", "character.aria.state")

    resumed = lifecycle.resume(
        "character",
        expected_snapshot_id=paused.snapshot_id,
        actor_id="user",
    )
    replaced = lifecycle.replace(
        "character",
        model_profile="high_reasoning",
        expected_snapshot_id=resumed.snapshot_id,
        actor_id="user",
    )
    archived = lifecycle.archive(
        "character",
        expected_snapshot_id=replaced.snapshot_id,
        actor_id="user",
    )

    stored = registry.get("character")
    assert stored.status == "archived"
    assert stored.model_profile == "high_reasoning"
    assert stored.manifest_revision == 5
    assert registry.truth.current().snapshot_id == archived.snapshot_id
    assert len(
        registry.truth.resource_history("agents.manifest.character")
    ) == 5


def test_recommendation_requires_approval(tmp_path: Path) -> None:
    registry, snapshot_id = _registry(tmp_path)

    with pytest.raises(AgentContractViolation, match="requires approval"):
        registry.register(
            _character_agent(),
            expected_snapshot_id=snapshot_id,
            actor_id="agent.timeline",
            source="recommendation",
            approved=False,
        )


def test_registry_mutation_fails_closed_when_feature_is_disabled(
    tmp_path: Path,
) -> None:
    registry, snapshot_id = _registry(tmp_path)
    manifest_path = registry.truth.project_root / "project.yml"
    project = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    project["features"]["enable_project_agents"] = False
    manifest_path.write_text(yaml.safe_dump(project), encoding="utf-8")

    with pytest.raises(AgentContractViolation, match="require enabled agents"):
        registry.register(
            _character_agent(),
            expected_snapshot_id=snapshot_id,
            actor_id="user",
            source="user",
            approved=True,
        )


@pytest.mark.parametrize(
    ("prompt", "expected_ids"),
    (
        (
            "制作一款黑暗幻想 RPG，需要角色、任务和数值设计",
            {"world", "character", "quest", "balance", "reviewer"},
        ),
        (
            "Build a secure web service with tests",
            {"architecture", "coder", "test", "security", "reviewer"},
        ),
        (
            "制作一张音乐专辑并完成混音",
            {"dsp", "mix", "listener_qa", "reviewer"},
        ),
    ),
)
def test_factory_generates_reusable_domain_team(
    prompt: str, expected_ids: set[str]
) -> None:
    proposal = ProjectAgentFactory().propose(prompt, project_id="project_x")

    assert {manifest.id for manifest in proposal.manifests} == expected_ids
    assert proposal.source == "factory"
    assert proposal.requires_approval is True
    assert all(manifest.status == "active" for manifest in proposal.manifests)


def test_factory_can_atomically_register_its_trusted_team(tmp_path: Path) -> None:
    registry, snapshot_id = _registry(tmp_path)

    receipt = ProjectAgentFactory().create_team(
        registry,
        "Build a secure web service with tests",
        expected_snapshot_id=snapshot_id,
        actor_id="user",
        approved=True,
    )

    assert {manifest.id for manifest in registry.list()} == {
        "architecture",
        "coder",
        "test",
        "security",
        "reviewer",
    }
    assert registry.truth.current().snapshot_id == receipt.snapshot_id
    assert len(
        registry.truth.resource_history("agents.manifest.architecture")
    ) == 1
    registry.truth.audit()


def test_factory_adds_prompt_requested_narrative_specialists() -> None:
    proposal = ProjectAgentFactory().propose(
        "创作成人黑暗幻想小说，需要谜团悬念控制与成熟感官美学",
        project_id="adult_narrative",
    )

    by_id = {manifest.id: manifest for manifest in proposal.manifests}

    assert {"mystery_keeper", "style_guardian"} <= set(by_id)
    assert by_id["mystery_keeper"].write_scope == ("mystery.*",)
    assert by_id["style_guardian"].write_scope == ("style.*",)
    assert by_id["writer"].runtime_role == "Writer"
    assert by_id["supervisor"].runtime_role == "Supervisor"
    assert by_id["blueprint_producer"].runtime_role == "ArtifactProducer"
    assert by_id["checker"].runtime_role == "Verifier"
    assert by_id["reviewer"].runtime_role == "Reviewer"
    assert "prompt-requested specialists" in proposal.rationale


def test_factory_maps_software_producers_to_executable_runtime_roles() -> None:
    proposal = ProjectAgentFactory().propose(
        "Build a secure web service with tests",
        project_id="software",
    )
    by_id = {manifest.id: manifest for manifest in proposal.manifests}

    assert by_id["architecture"].runtime_role == "Researcher"
    assert by_id["coder"].runtime_role == "Coder"
    assert by_id["test"].runtime_role == "Verifier"
    assert by_id["security"].runtime_role == "Reviewer"
    assert by_id["reviewer"].runtime_role == "Reviewer"
