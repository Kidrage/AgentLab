"""Snapshot-bound professional author-team DAGs for durable chapter execution."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from agent_runtime.project_agents import ProjectAgentRegistry
from agent_runtime.project_agents.contract import AgentContract, effective_contract_hash
from agent_runtime.project_truth import ProjectTruthStore
from agent_runtime.task_runtime_v2 import TaskRuntime

from .author_team import REQUIRED_AUTHOR_ROLES


_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "authorial_director": (),
    "canon_timeline_steward": ("authorial_director",),
    "plot_causality_architect": ("canon_timeline_steward",),
    "character_ensemble_director": ("canon_timeline_steward",),
    "relationship_director": ("character_ensemble_director",),
    "world_archaeologist": ("canon_timeline_steward",),
    "foreshadow_mystery_keeper": ("plot_causality_architect",),
    "research_style_curator": ("authorial_director",),
    "arc_scene_planner": (
        "world_archaeologist",
        "relationship_director",
        "foreshadow_mystery_keeper",
        "research_style_curator",
    ),
    "writer": ("arc_scene_planner",),
    "senior_editor": ("writer", "canon_timeline_steward"),
    "reader_simulation_panel": ("writer",),
    "state_projector": ("senior_editor", "reader_simulation_panel"),
}

_ROLE_ORDER = (
    "authorial_director",
    "canon_timeline_steward",
    "plot_causality_architect",
    "character_ensemble_director",
    "relationship_director",
    "world_archaeologist",
    "foreshadow_mystery_keeper",
    "research_style_curator",
    "arc_scene_planner",
    "writer",
    "senior_editor",
    "reader_simulation_panel",
    "state_projector",
)

_KINDS = {
    "authorial_director": "planning",
    "canon_timeline_steward": "expert-check",
    "plot_causality_architect": "expert-check",
    "character_ensemble_director": "expert-check",
    "relationship_director": "expert-check",
    "world_archaeologist": "expert-check",
    "foreshadow_mystery_keeper": "expert-check",
    "research_style_curator": "expert-check",
    "arc_scene_planner": "planning",
    "writer": "prose",
    "senior_editor": "quality-review",
    "reader_simulation_panel": "quality-review",
    "state_projector": "verification",
}


def _work_item_id(chapter: int, role_id: str, revision: int) -> str:
    return f"chapter-{chapter:03d}-{role_id.replace('_', '-')}-v{revision}"


def materialize_professional_chapter_dag(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    job_id: str,
    chapter: int,
    revision: int,
    previous_state_projector_id: str | None,
    idempotency_key: str,
) -> dict[str, Any]:
    """Create or resume one complete 13-role chapter DAG atomically.

    Every generative WorkItem is bound to one current Project Truth snapshot.
    A partially materialized DAG may be resumed only when its existing nodes
    still match that exact snapshot and professional role contract.
    """

    if chapter < 1 or revision < 1:
        raise ValueError("chapter and revision must be positive")
    if chapter > 1 and not str(previous_state_projector_id or "").strip():
        raise ValueError("later chapters require the previous state projector")
    key = str(idempotency_key or "").strip()
    if not key:
        raise ValueError("idempotency_key is required")
    if set(_DEPENDENCIES) != set(REQUIRED_AUTHOR_ROLES) or set(_ROLE_ORDER) != set(
        REQUIRED_AUTHOR_ROLES
    ):
        raise ValueError("professional chapter DAG does not match author-team authority")

    root = Path(agentlab_root).resolve()
    project_root = root / "projects" / project
    runtime = TaskRuntime(root, project=project)
    registry = ProjectAgentRegistry(ProjectTruthStore(project_root))
    projection = runtime.load_task(task_id)
    if job_id not in projection["jobs"]:
        raise ValueError(f"chapter job does not exist: {job_id}")
    manifests = {manifest.id: manifest for manifest in registry.list()}

    with registry.truth.current_snapshot_lease() as current:
        items: list[dict[str, Any]] = []
        for role_id in _ROLE_ORDER:
            manifest = manifests.get(role_id)
            if manifest is None:
                raise ValueError(f"professional role is not registered: {role_id}")
            AgentContract(manifest).assert_active()
            item_id = _work_item_id(chapter, role_id, revision)
            dependencies = [
                _work_item_id(chapter, dependency, revision)
                for dependency in _DEPENDENCIES[role_id]
            ]
            if role_id == "authorial_director" and previous_state_projector_id:
                dependencies = [str(previous_state_projector_id)]
            expected = {
                "job_id": job_id,
                "work_item_id": item_id,
                "kind": _KINDS[role_id],
                "title": f"Chapter {chapter} {manifest.name}",
                "depends_on": dependencies,
                "requires_user_acceptance": role_id == "state_projector",
                "assigned_agent_id": manifest.id,
                "agent_manifest_revision": manifest.manifest_revision,
                "canonical_snapshot_id": current.snapshot_id,
                "effective_contract_hash": effective_contract_hash(manifest),
            }
            existing = projection["work_items"].get(item_id)
            if existing is not None:
                for field, value in expected.items():
                    if field != "title" and existing.get(field) != value:
                        raise ValueError(
                            f"existing professional chapter node is stale: {item_id}:{field}"
                        )
                continue
            items.append(expected)

        if not items:
            return projection
        missing_identity = "\n".join(item["work_item_id"] for item in items)
        batch_hash = hashlib.sha256(missing_identity.encode("utf-8")).hexdigest()[:12]
        return runtime.create_work_items(
            task_id,
            batch_id=f"chapter-{chapter:03d}-professional-v{revision}-{batch_hash}",
            items=items,
            idempotency_key=f"{key[:90]}.{batch_hash}",
        )
