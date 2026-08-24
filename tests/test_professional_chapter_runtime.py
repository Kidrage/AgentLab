from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.narrative.author_team import (
    REQUIRED_AUTHOR_ROLES,
    materialize_author_team_contract,
    register_author_team_proposal,
)
from agent_runtime.narrative.professional_chapter_runtime import (
    materialize_professional_chapter_dag,
)
from agent_runtime.project_truth import ProjectTruthStore
from agent_runtime.project_agents import ProjectAgentRegistry
from agent_runtime.project_agents.contract import effective_contract_hash
from agent_runtime.task_runtime_v2 import TaskRuntime


ROOT = Path(__file__).resolve().parents[1]
BASE_CHAPTER_ROLES = {
    "authorial_director",
    "canon_timeline_steward",
    "arc_scene_planner",
    "writer",
    "senior_editor",
    "state_projector",
}


def _professional_project(root: Path) -> tuple[TaskRuntime, str]:
    config = root / "config"
    config.mkdir()
    for name in (
        "narrative_author_team.yml",
        "agent_registry.yml",
        "agent_model_profiles.yml",
    ):
        (config / name).write_bytes((ROOT / "config" / name).read_bytes())
    project = root / "projects" / "Novel"
    project.mkdir(parents=True)
    (project / "project.yml").write_text(
        yaml.safe_dump(
            {
                "project_id": "Novel",
                "features": {
                    "project_truth_mode": "enforced",
                    "enable_project_agents": True,
                },
                "workspace": {"isolation": "required"},
            }
        ),
        encoding="utf-8",
    )
    truth = ProjectTruthStore(project)
    pointer = truth.initialize("Novel")
    proposed = materialize_author_team_contract(
        root,
        project="Novel",
        task_id="task_author_team",
        template_path=config / "narrative_author_team.yml",
    )
    register_author_team_proposal(
        root,
        project="Novel",
        proposal_path=root / proposed["proposal_path"],
        expected_proposal_sha256=proposed["proposal_sha256"],
        expected_snapshot_id=pointer.current_snapshot_id,
        actor_id="user",
        approved=True,
    )
    runtime = TaskRuntime(root, project="Novel")
    runtime.create_task(
        task_id="task-part-one",
        title="Complete part one",
        user_goal="Write all chapters in order.",
        idempotency_key="create-part-one",
    )
    runtime.create_job(
        "task-part-one",
        job_id="job-chapter-002",
        kind="candidate",
        strategy="professional-chapter",
        idempotency_key="job-chapter-002",
    )
    registry = ProjectAgentRegistry(truth)
    projector = registry.get("state_projector")
    snapshot_id = truth.current().snapshot_id
    runtime.create_work_item(
        "task-part-one",
        job_id="job-main",
        work_item_id="chapter-001-state-projector",
        kind="verification",
        title="Accepted chapter 1 state",
        assigned_agent_id=projector.id,
        agent_manifest_revision=projector.manifest_revision,
        canonical_snapshot_id=snapshot_id,
        effective_contract_hash=effective_contract_hash(projector),
        idempotency_key="chapter-001-state-projector",
    )
    runtime.transition_work_item(
        "task-part-one",
        work_item_id="chapter-001-state-projector",
        status="running",
        idempotency_key="chapter-001-state-projector-running",
    )
    runtime.transition_work_item(
        "task-part-one",
        work_item_id="chapter-001-state-projector",
        status="accepted",
        idempotency_key="chapter-001-state-projector-accepted",
    )
    return runtime, snapshot_id


def test_materializes_snapshot_bound_minimum_professional_chapter_dag(
    tmp_path: Path,
) -> None:
    runtime, snapshot_id = _professional_project(tmp_path)

    projection = materialize_professional_chapter_dag(
        tmp_path,
        project="Novel",
        task_id="task-part-one",
        job_id="job-chapter-002",
        chapter=2,
        revision=3,
        previous_state_projector_id="chapter-001-state-projector",
        idempotency_key="chapter-002-professional-v3",
    )

    prefix = "chapter-002-"
    chapter_items = {
        key: value
        for key, value in projection["work_items"].items()
        if key.startswith(prefix) and key.endswith("-v3")
    }
    assert len(chapter_items) == len(BASE_CHAPTER_ROLES)
    assert {item["assigned_agent_id"] for item in chapter_items.values()} == BASE_CHAPTER_ROLES
    assert {item["canonical_snapshot_id"] for item in chapter_items.values()} == {
        snapshot_id
    }
    director = chapter_items["chapter-002-authorial-director-v3"]
    writer = chapter_items["chapter-002-writer-v3"]
    projector = chapter_items["chapter-002-state-projector-v3"]
    assert director["depends_on"] == ["chapter-001-state-projector"]
    assert writer["depends_on"] == ["chapter-002-arc-scene-planner-v3"]
    assert projector["depends_on"] == ["chapter-002-senior-editor-v3"]
    assert projector["requires_user_acceptance"] is True
    assert director["status"] == "ready"


def test_resumes_after_preexisting_director_without_duplicate_role(
    tmp_path: Path,
) -> None:
    runtime, _ = _professional_project(tmp_path)
    first = materialize_professional_chapter_dag(
        tmp_path,
        project="Novel",
        task_id="task-part-one",
        job_id="job-chapter-002",
        chapter=2,
        revision=3,
        previous_state_projector_id="chapter-001-state-projector",
        idempotency_key="chapter-002-professional-v3",
    )
    second = materialize_professional_chapter_dag(
        tmp_path,
        project="Novel",
        task_id="task-part-one",
        job_id="job-chapter-002",
        chapter=2,
        revision=3,
        previous_state_projector_id="chapter-001-state-projector",
        idempotency_key="chapter-002-professional-v3",
    )

    assert second == first


def test_materializes_full_team_only_for_declared_major_risk(tmp_path: Path) -> None:
    _professional_project(tmp_path)

    projection = materialize_professional_chapter_dag(
        tmp_path,
        project="Novel",
        task_id="task-part-one",
        job_id="job-chapter-002",
        chapter=2,
        revision=3,
        previous_state_projector_id="chapter-001-state-projector",
        idempotency_key="chapter-002-battle-v3",
        risk_flags=("battle",),
    )

    chapter_items = {
        value["assigned_agent_id"]
        for key, value in projection["work_items"].items()
        if key.startswith("chapter-002-") and key.endswith("-v3")
    }
    assert chapter_items == set(REQUIRED_AUTHOR_ROLES)
