"""Materialize approved Project Agent collaboration plans in Task Runtime v2."""

from __future__ import annotations

from agent_runtime.task_runtime_v2 import TaskRuntime

from .collaboration import ExpertCollaborationPlanner
from .contract import AgentContract, effective_contract_hash
from .registry import ProjectAgentRegistry


class ExpertCollaborationScheduler:
    """Compile a collaboration DAG into snapshot-bound Runtime v2 WorkItems."""

    def __init__(
        self,
        planner: ExpertCollaborationPlanner | None = None,
    ) -> None:
        self.planner = planner or ExpertCollaborationPlanner()

    def materialize(
        self,
        runtime: TaskRuntime,
        registry: ProjectAgentRegistry,
        *,
        task_id: str,
        domain: str,
        idempotency_prefix: str,
        job_id: str = "job-main",
    ) -> dict:
        key_prefix = str(idempotency_prefix).strip()
        if not key_prefix:
            raise ValueError("idempotency_prefix is required")
        current = registry.truth.current()
        manifests = {manifest.id: manifest for manifest in registry.list()}
        plan = self.planner.plan(
            domain,
            available_agent_ids=manifests,
        )

        seen: set[str] = set()
        for node in plan.nodes:
            manifest = manifests.get(node.agent_id)
            if manifest is None:
                raise ValueError(
                    f"collaboration agent is not registered: {node.agent_id}"
                )
            AgentContract(manifest).assert_active()
            missing = set(node.depends_on) - seen
            if missing:
                raise ValueError(
                    "collaboration plan is not topologically ordered: "
                    f"{', '.join(sorted(missing))}"
                )
            seen.add(node.id)

        projection = runtime.load_task(task_id)
        for node in plan.nodes:
            manifest = manifests[node.agent_id]
            projection = runtime.create_work_item(
                task_id,
                job_id=job_id,
                work_item_id=node.id,
                kind=node.kind,
                title=f"{manifest.name}: {node.kind}",
                depends_on=list(node.depends_on),
                assigned_agent_id=manifest.id,
                agent_manifest_revision=manifest.manifest_revision,
                canonical_snapshot_id=current.snapshot_id,
                effective_contract_hash=effective_contract_hash(manifest),
                idempotency_key=(
                    f"{key_prefix[:80]}-{node.id}-"
                    f"r{manifest.manifest_revision}"
                ),
            )
        return projection
