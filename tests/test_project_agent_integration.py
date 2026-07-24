from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_runtime.knowledge_system.models import validate_namespace
from agent_runtime.knowledge_system.sources import SourceCollector
from agent_runtime.knowledge_system.storage import KnowledgeStore
from agent_runtime.project_agents import (
    AgentManifest,
    AgentLifecycle,
    ExpertCollaborationPlanner,
    ProjectAgentMemory,
    ProjectAgentRegistry,
    effective_contract_hash,
)
from agent_runtime.project_ops.project_router import init_project
from agent_runtime.project_truth import ChangeSet, FactChange, ProjectTruthStore
from agent_runtime.task_runtime_v2 import TaskRuntime


def _manifest() -> AgentManifest:
    return AgentManifest(
        id="character",
        name="Character Agent",
        version="1.0.0",
        role="character_architect",
        description="Maintain characters.",
        responsibilities=("Maintain character state.",),
        runtime_role="Researcher",
        read_scope=("world.*", "character.*"),
        write_scope=("character.*",),
        approval_scope=(),
        knowledge_binding={
            "namespace": "agent.Demo.character",
            "documents": (),
            "artifacts": (),
        },
        model_profile="balanced",
        tool_permission=("knowledge.read",),
        budget_profile="standard",
        status="active",
        acceptance_rules=("character_state_is_consistent",),
    )


def test_project_init_defaults_to_legacy_pipeline_with_isolation_required(
    tmp_path: Path,
) -> None:
    init_project(tmp_path, "Demo", "generic", "Demo")

    manifest = yaml.safe_load(
        (tmp_path / "projects" / "Demo" / "project.yml").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["features"] == {
        "project_truth_mode": "legacy",
        "enable_project_agents": False,
    }
    assert manifest["workspace"] == {"isolation": "required"}


def test_agent_namespaces_create_private_physical_memory_shards(
    tmp_path: Path,
) -> None:
    store = KnowledgeStore(tmp_path)

    character = store.ensure_space(validate_namespace("agent.Demo.character"))
    world = store.ensure_space(validate_namespace("agent.Demo.world"))

    assert character != world
    assert character.parent == world.parent == store.spaces_root
    assert character.is_file()
    assert world.is_file()


def test_project_memory_binds_global_project_and_private_agent_layers(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "projects" / "Demo"
    project_root.mkdir(parents=True)
    (project_root / "project.yml").write_text(
        yaml.safe_dump(
            {
                "project_id": "Demo",
                "features": {
                    "project_truth_mode": "enforced",
                    "enable_project_agents": True,
                },
                "workspace": {"isolation": "required"},
            }
        ),
        encoding="utf-8",
    )
    truth = ProjectTruthStore(project_root)
    initial = truth.initialize("Demo")
    registry = ProjectAgentRegistry(truth)
    registry.register(
        _manifest(),
        expected_snapshot_id=initial.current_snapshot_id,
        actor_id="user",
        source="user",
        approved=True,
    )
    memory = ProjectAgentMemory(KnowledgeStore(tmp_path), registry)

    layers = memory.layers_for("character", domain="longform_narrative")

    assert layers == (
        "system.agentlab",
        "domain.longform_narrative",
        "project.Demo",
        "agent.Demo.character",
    )
    assert memory.ensure_private_space("character").is_file()


def test_expert_collaboration_is_a_domain_dag_not_a_reviewer_monolith() -> None:
    narrative = ExpertCollaborationPlanner().plan("narrative")
    by_id = {node.id: node for node in narrative.nodes}

    assert by_id["writer"].depends_on == (
        "world-check",
        "character-check",
        "timeline-check",
        "foreshadow-check",
    )
    assert by_id["reviewer"].depends_on == ("checker",)
    assert by_id["world-check"].agent_id == "world"
    assert by_id["character-check"].agent_id == "character"

    software = ExpertCollaborationPlanner().plan("software")
    assert {node.agent_id for node in software.nodes} == {
        "architecture",
        "coder",
        "test",
        "security",
        "reviewer",
    }


def test_enforced_truth_indexes_only_current_snapshot_as_project_authority(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "projects" / "Demo"
    (project_root / "project_brain").mkdir(parents=True)
    (project_root / "project_brain" / "candidate_plan.yml").write_text(
        "word_count: 120000\n", encoding="utf-8"
    )
    (project_root / "project.yml").write_text(
        yaml.safe_dump(
            {
                "project_id": "Demo",
                "features": {
                    "project_truth_mode": "enforced",
                    "enable_project_agents": True,
                },
                "workspace": {"isolation": "required"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    truth = ProjectTruthStore(project_root)
    initial = truth.initialize("Demo")
    truth.commit(
        ChangeSet(
            project_id="Demo",
            expected_snapshot_id=initial.current_snapshot_id,
            actor_id="user",
            idempotency_key="length-v1",
            facts=(
                FactChange(
                    key="novel.total_word_count",
                    value=150_000,
                    owner="project.editorial",
                ),
            ),
        )
    )

    records = SourceCollector(tmp_path).collect_project(
        "Demo", domain="longform_narrative"
    )
    paths = {record.source.path for record in records}

    assert "projects/Demo/project_truth.yml" in paths
    assert any("/.agentlab/truth/snapshots/" in path for path in paths)
    assert "projects/Demo/project_brain/candidate_plan.yml" not in paths
    assert {record.authority.value for record in records} == {"canonical"}


def test_work_item_binds_registered_agent_contract_and_truth_snapshot(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "projects" / "Demo"
    project_root.mkdir(parents=True)
    (project_root / "project.yml").write_text(
        yaml.safe_dump(
            {
                "project_id": "Demo",
                "features": {
                    "project_truth_mode": "enforced",
                    "enable_project_agents": True,
                },
                "workspace": {"isolation": "required"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    truth = ProjectTruthStore(project_root)
    initial = truth.initialize("Demo")
    registry = ProjectAgentRegistry(truth)
    created = registry.register(
        _manifest(),
        expected_snapshot_id=initial.current_snapshot_id,
        actor_id="user",
        source="user",
        approved=True,
    )
    manifest = registry.get("character")
    runtime = TaskRuntime(tmp_path, project="Demo")
    runtime.create_task(
        task_id="task-demo",
        title="Update character",
        user_goal="Update Aria while preserving canon.",
        idempotency_key="task-create",
        legacy_source={"kind": "binding-test"},
    )

    projection = runtime.create_work_item(
        "task-demo",
        job_id="job-main",
        work_item_id="character-check",
        kind="expert-check",
        title="Character consistency",
        idempotency_key="work-create",
        assigned_agent_id="character",
        agent_manifest_revision=manifest.manifest_revision,
        canonical_snapshot_id=created.snapshot_id,
        effective_contract_hash=effective_contract_hash(manifest),
    )
    work_item = projection["work_items"]["character-check"]

    assert work_item["assigned_agent_id"] == "character"
    assert work_item["agent_manifest_revision"] == 1
    assert work_item["canonical_snapshot_id"] == created.snapshot_id
    assert work_item["effective_contract_hash"] == effective_contract_hash(
        manifest
    )

    with pytest.raises(ValueError, match="runtime role"):
        runtime.schedule_attempt(
            "task-demo",
            work_item_id="character-check",
            attempt_id="attempt-wrong-role",
            worker="codex",
            provider="codex-cli",
            execution_contract={"role": "Writer"},
            idempotency_key="attempt-wrong-role",
        )

    runtime.schedule_attempt(
        "task-demo",
        work_item_id="character-check",
        attempt_id="attempt-bound-agent",
        worker="codex",
        provider="codex-cli",
        execution_contract={"role": "Researcher"},
        idempotency_key="attempt-bound-agent",
    )
    AgentLifecycle(registry).pause(
        "character",
        expected_snapshot_id=created.snapshot_id,
        actor_id="user",
    )
    with pytest.raises(ValueError, match="snapshot binding is stale"):
        runtime.transition_attempt(
            "task-demo",
            attempt_id="attempt-bound-agent",
            status="running",
            idempotency_key="attempt-bound-agent-running",
        )
    with pytest.raises(ValueError, match="snapshot binding is stale"):
        runtime.schedule_attempt(
            "task-demo",
            work_item_id="character-check",
            attempt_id="attempt-stale-agent",
            worker="codex",
            provider="codex-cli",
            execution_contract={"role": "Researcher"},
            idempotency_key="attempt-stale-agent",
        )


def test_project_agents_require_enforced_truth_mode(tmp_path: Path) -> None:
    project_root = tmp_path / "projects" / "Demo"
    project_root.mkdir(parents=True)
    (project_root / "project.yml").write_text(
        yaml.safe_dump(
            {
                "project_id": "Demo",
                "features": {
                    "project_truth_mode": "shadow",
                    "enable_project_agents": True,
                },
                "workspace": {"isolation": "required"},
            }
        ),
        encoding="utf-8",
    )
    runtime = TaskRuntime(tmp_path, project="Demo")
    runtime.create_task(
        task_id="task-demo",
        title="Unsafe config",
        user_goal="This must fail closed.",
        idempotency_key="task-create",
    )

    with pytest.raises(ValueError, match="require enforced project truth"):
        runtime.create_work_item(
            "task-demo",
            job_id="job-main",
            work_item_id="unsafe",
            kind="expert-check",
            title="Unsafe",
            idempotency_key="work-create",
        )
