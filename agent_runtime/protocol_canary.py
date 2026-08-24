"""Deterministic recovery canaries for the shared production-protocol kernel."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from agent_runtime.production_protocols import ProductionProtocolRunner
from agent_runtime.task_runtime_v2 import TaskRuntime


_SHARED_CONFIGS = (
    "production_packs.yml",
    "task_input_tiers.yml",
    "narrative_author_team.yml",
    "agent_registry.yml",
    "agent_model_profiles.yml",
)

_CANARIES: tuple[dict[str, Any], ...] = (
    {
        "name": "NovelCanary",
        "protocol_ref": "narrative.chapter.v1",
        "title": "Write one isolated lighthouse-memory chapter",
        "user_goal": "Produce a reviewed chapter candidate without touching an existing story world.",
        "facts": {
            "kind": "prose_build",
            "scope": "single_chapter",
            "chapter": 1,
            "risk_flags": [],
        },
    },
    {
        "name": "CodeCanary",
        "protocol_ref": "code.large.v1",
        "title": "Build one isolated fixture patch",
        "user_goal": "Produce an independently validated candidate patch for a fixture repository.",
        "facts": {
            "kind": "code_build",
            "scope": "large",
            "repository": "fixture-repository",
        },
    },
)


def _install_canary_authority(source_root: Path, state_root: Path) -> None:
    config_root = state_root / "config"
    config_root.mkdir(parents=True, exist_ok=True)
    for name in _SHARED_CONFIGS:
        source = source_root / "config" / name
        if not source.is_file():
            raise FileNotFoundError(f"canary authority is missing: {source}")
        target = config_root / name
        if target.exists() and target.read_bytes() == source.read_bytes():
            continue
        shutil.copy2(source, target)


def _run_one(
    state_root: Path,
    *,
    canary: dict[str, Any],
    iteration: int,
) -> dict[str, Any]:
    project = f"{canary['name']}{iteration:02d}"
    task_id = f"task_{str(canary['name']).lower()}_{iteration:02d}"
    runtime = TaskRuntime(state_root, project=project)
    runtime.create_task(
        task_id=task_id,
        title=str(canary["title"]),
        user_goal=str(canary["user_goal"]),
        protocol_ref=str(canary["protocol_ref"]),
        input_profile=dict(canary["facts"]),
        idempotency_key=f"create-{task_id}",
    )
    projection = ProductionProtocolRunner(state_root, project=project).prepare(task_id)
    runtime.transition_task(task_id, status="ready", idempotency_key=f"ready-{task_id}")
    runtime.transition_task(task_id, status="running", idempotency_key=f"run-{task_id}")

    ordered_nodes = [
        binding["node_id"]
        for binding in projection["task"]["compiled_protocol"]["role_bindings"]
    ]
    recovery_node = ordered_nodes[0]
    runtime.transition_work_item(
        task_id,
        work_item_id=recovery_node,
        status="blocked",
        idempotency_key=f"block-{task_id}-{recovery_node}",
    )

    # Reconstruct from the append-only ledger before resuming the injected failure.
    runtime = TaskRuntime(state_root, project=project)
    runtime.transition_work_item(
        task_id,
        work_item_id=recovery_node,
        status="ready",
        idempotency_key=f"resume-{task_id}-{recovery_node}",
    )
    for node_id in ordered_nodes:
        runtime.transition_work_item(
            task_id,
            work_item_id=node_id,
            status="running",
            idempotency_key=f"start-{task_id}-{node_id}",
        )
        runtime.transition_work_item(
            task_id,
            work_item_id=node_id,
            status="accepted",
            idempotency_key=f"accept-{task_id}-{node_id}",
        )

    projection = runtime.rebuild_task(task_id)
    repeated = ProductionProtocolRunner(state_root, project=project).prepare(task_id)
    if repeated != projection:
        raise RuntimeError("canary protocol preparation is not idempotent after recovery")
    doctor = runtime.doctor_project()
    accepted = sum(
        item["status"] == "accepted" for item in projection["work_items"].values()
    )
    return {
        "canary": canary["name"],
        "iteration": iteration,
        "project": project,
        "task_id": task_id,
        "protocol_ref": canary["protocol_ref"],
        "recovery_injected": True,
        "doctor_ok": doctor["ok"],
        "work_item_count": len(projection["work_items"]),
        "accepted_work_items": accepted,
        "last_event_sequence": projection["last_event_sequence"],
        "last_event_hash": projection["last_event_hash"],
    }


def run_protocol_canaries(
    agentlab_root: Path,
    *,
    state_root: Path,
    iterations: int = 10,
) -> dict[str, Any]:
    """Run isolated Novel and Code kernel canaries with restart recovery."""

    if iterations < 1:
        raise ValueError("canary iterations must be positive")
    source_root = Path(agentlab_root).resolve()
    isolated_root = Path(state_root).resolve()
    _install_canary_authority(source_root, isolated_root)
    runs = [
        _run_one(isolated_root, canary=canary, iteration=iteration)
        for iteration in range(1, iterations + 1)
        for canary in _CANARIES
    ]
    ok = all(
        run["doctor_ok"]
        and run["accepted_work_items"] == run["work_item_count"]
        for run in runs
    )
    return {
        "schema_version": "protocol-canary-report/v1",
        "ok": ok,
        "iterations": iterations,
        "runs": runs,
    }
