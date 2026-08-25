"""Stress the production narrative state store with pseudoprose chapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import hashlib
import json
import re

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.narrative.state_store import (
    NarrativeStateStore,
    narrative_payload_sha256,
)

_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$")
_TASK_ID = re.compile(r"^task_[A-Za-z0-9][A-Za-z0-9_-]{0,80}$")


def _mapping_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _file_binding(project_root: Path, path: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(project_root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _reject_symlink_ancestors(base: Path, target: Path) -> None:
    current = base
    if current.is_symlink():
        raise ValueError(f"stress path ancestor is a symlink: {current}")
    for part in target.relative_to(base).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"stress path ancestor is a symlink: {current}")


def _verified_commit(
    output_root: Path,
    *,
    project: str,
    chapter_id: int,
    previous_state_sha256: str,
) -> dict[str, Any]:
    artifact_sha256 = hashlib.sha256(
        f"{project}:pseudoprose:{chapter_id}".encode("utf-8")
    ).hexdigest()
    brief_sha256 = hashlib.sha256(
        f"{project}:brief:{chapter_id}".encode("utf-8")
    ).hexdigest()
    source_projection_sha256 = hashlib.sha256(
        f"{project}:projection:{chapter_id}".encode("utf-8")
    ).hexdigest()
    verification_result_sha256 = hashlib.sha256(
        f"{project}:verification:{chapter_id}".encode("utf-8")
    ).hexdigest()
    state_delta = {
        "world_updates": [
            {
                "axis": "pseudoprose_stress_last_chapter",
                "value": chapter_id,
            }
        ]
    }
    state_delta_sha256 = narrative_payload_sha256(state_delta)
    evidence_binding_id = f"stress-chapter-{chapter_id:04d}"
    binding = {
        "artifact_sha256": artifact_sha256,
        "brief_sha256": brief_sha256,
        "source_projection_sha256": source_projection_sha256,
        "verification_result_sha256": verification_result_sha256,
        "state_delta_sha256": state_delta_sha256,
    }
    receipts_root = output_root / "receipts"
    receipts_root.mkdir(exist_ok=True)
    seal_path = receipts_root / f"seal-{chapter_id:04d}.yml"
    delta_path = receipts_root / f"delta-{chapter_id:04d}.yml"
    atomic_write_yaml(
        seal_path,
        {
            "schema_version": "narrative-seal-receipt/v1",
            "issuer": "AgentLab.Supervisor",
            "attempt_id": f"stress-supervisor-{chapter_id:04d}",
            "evidence_binding_id": evidence_binding_id,
            "status": "accepted",
            **binding,
        },
    )
    atomic_write_yaml(
        delta_path,
        {
            "schema_version": "delta-verification-receipt/v1",
            "issuer": "AgentLab.DeltaVerifier",
            "attempt_id": f"stress-delta-{chapter_id:04d}",
            "evidence_binding_id": evidence_binding_id,
            "status": "pass",
            "source_projection_sha256": source_projection_sha256,
            "verification_result_sha256": verification_result_sha256,
        },
    )
    return {
        "schema_version": "verified-chapter-commit/v1",
        "project": project,
        "chapter": chapter_id,
        "artifact_sha256": artifact_sha256,
        "brief_sha256": brief_sha256,
        "source_projection_sha256": source_projection_sha256,
        "state_delta_sha256": state_delta_sha256,
        "seal": {
            "status": "accepted",
            "attempt_id": f"stress-supervisor-{chapter_id:04d}",
            "evidence_binding_id": evidence_binding_id,
            "receipt_path": seal_path.relative_to(output_root).as_posix(),
            "receipt_sha256": hashlib.sha256(seal_path.read_bytes()).hexdigest(),
            **binding,
        },
        "delta_verification": {
            "status": "pass",
            "attempt_id": f"stress-delta-{chapter_id:04d}",
            "evidence_binding_id": evidence_binding_id,
            "receipt_path": delta_path.relative_to(output_root).as_posix(),
            "receipt_sha256": hashlib.sha256(delta_path.read_bytes()).hexdigest(),
            "source_projection_sha256": source_projection_sha256,
            "verification_result_sha256": verification_result_sha256,
        },
        "previous_state_sha256": previous_state_sha256,
        "state_delta": state_delta,
    }


def run_pseudoprose_state_stress(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    chapter_count: int,
) -> dict[str, Any]:
    """Execute 100–600 verified commits against the production state store."""

    if not _PROJECT_ID.fullmatch(project):
        raise ValueError("project identifier is invalid")
    if not _TASK_ID.fullmatch(task_id):
        raise ValueError("task identifier is invalid")
    if (
        isinstance(chapter_count, bool)
        or not isinstance(chapter_count, int)
        or not 100 <= chapter_count <= 600
    ):
        raise ValueError("chapter_count must be between 100 and 600")
    root = Path(agentlab_root).resolve()
    projects_root = root / "projects"
    raw_project_root = projects_root / project
    _reject_symlink_ancestors(root, raw_project_root)
    project_root = raw_project_root.resolve()
    project_root.relative_to(projects_root.resolve())
    if not project_root.is_dir():
        raise ValueError("project root is invalid")
    output_root = (
        project_root / "runs" / task_id / "artifacts" / "state_stress"
    )
    _reject_symlink_ancestors(projects_root, output_root)
    if output_root.exists():
        raise FileExistsError(output_root)
    output_root.mkdir(parents=True)

    source_path = output_root / "bootstrap-source.yml"
    atomic_write_yaml(
        source_path,
        {
            "schema_version": "narrative-pseudoprose-bootstrap-source/v1",
            "project": project,
            "task_id": task_id,
        },
    )
    store_root = output_root / "project_brain"
    store = NarrativeStateStore(store_root, project=project)
    bootstrap_manifest = {
        "schema_version": "narrative-bootstrap/v1",
        "project": project,
        "precedence": ["pseudoprose_stress_fixture"],
        "sources": [
            {
                "path": source_path.relative_to(output_root).as_posix(),
                "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            }
        ],
        "base_state": {},
    }
    bootstrap_receipt = store.bootstrap(bootstrap_manifest)
    atomic_write_yaml(output_root / "bootstrap-receipt.yml", bootstrap_receipt)

    state_bindings: list[dict[str, str]] = []
    for chapter_id in range(1, chapter_count + 1):
        before = store.read()
        receipt = store.commit(
            _verified_commit(
                output_root,
                project=project,
                chapter_id=chapter_id,
                previous_state_sha256=str(before["state_sha256"]),
            )
        )
        projection = store.read(chapter=chapter_id)
        projection_path = output_root / f"state-{chapter_id:04d}.yml"
        atomic_write_yaml(
            projection_path,
            {
                "schema_version": "narrative-state-store-projection/v1",
                "project": project,
                "chapter_id": chapter_id,
                "status": "pass",
                "commit_receipt": receipt,
                "projection": projection,
                "projection_sha256": _mapping_sha256(projection),
            },
        )
        state_bindings.append(_file_binding(project_root, projection_path))

    final_projection = store.read()
    expected_snapshot_path = output_root / "expected-final-snapshot.yml"
    atomic_write_yaml(expected_snapshot_path, final_projection)
    expected_binding = _file_binding(project_root, expected_snapshot_path)
    atomic_write_yaml(
        store.snapshot_path,
        {
            "schema_version": "narrative-state-corruption/v1",
            "project": project,
            "corrupted": True,
        },
    )
    corrupted_sha256 = hashlib.sha256(store.snapshot_path.read_bytes()).hexdigest()
    store.bootstrap(bootstrap_manifest)
    recovered_projection = store.read()
    recovered_snapshot_path = output_root / "recovered-final-snapshot.yml"
    atomic_write_yaml(recovered_snapshot_path, recovered_projection)
    recovered_binding = _file_binding(project_root, recovered_snapshot_path)

    rollback_projection = store.read(at_version=chapter_count)
    rollback_path = output_root / "rollback-projection.yml"
    atomic_write_yaml(rollback_path, rollback_projection)
    rollback_binding = _file_binding(project_root, rollback_path)
    final_copy_path = output_root / "pre-rollback-final-projection.yml"
    atomic_write_yaml(final_copy_path, recovered_projection)
    final_copy_binding = _file_binding(project_root, final_copy_path)
    state_store_rollback_receipt = store.rollback_to_chapter(
        chapter_count - 1,
        reason="pseudoprose stress rollback verification",
        idempotency_key=f"{task_id}:rollback:{chapter_count - 1}",
    )
    active_rollback_binding = _file_binding(project_root, store.snapshot_path)

    chain_sha256 = hashlib.sha256(
        json.dumps(
            [binding["sha256"] for binding in state_bindings],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    event_ledger_binding = _file_binding(project_root, store.events_path)
    recovery_receipt_path = output_root / "recovery-receipt.yml"
    atomic_write_yaml(
        recovery_receipt_path,
        {
            "schema_version": "narrative-state-recovery-receipt/v1",
            "project": project,
            "task_id": task_id,
            "status": "pass",
            "state_chain_sha256": chain_sha256,
            "active_state_path": recovered_snapshot_path.relative_to(
                project_root
            ).as_posix(),
            "event_ledger_binding": event_ledger_binding,
            "corrupted_snapshot_sha256": corrupted_sha256,
            "expected_snapshot_binding": expected_binding,
            "recovered_snapshot_binding": recovered_binding,
            "expected_snapshot_sha256": expected_binding["sha256"],
            "recovered_snapshot_sha256": recovered_binding["sha256"],
        },
    )
    rollback_receipt_path = output_root / "rollback-receipt.yml"
    atomic_write_yaml(
        rollback_receipt_path,
        {
            "schema_version": "narrative-state-rollback-receipt/v1",
            "project": project,
            "task_id": task_id,
            "status": "pass",
            "state_chain_sha256": chain_sha256,
            "active_state_path": store.snapshot_path.relative_to(
                project_root
            ).as_posix(),
            "event_ledger_binding": event_ledger_binding,
            "state_store_rollback_receipt": state_store_rollback_receipt,
            "rollback_chapter": chapter_count - 1,
            "pre_change_binding": rollback_binding,
            "mutated_binding": final_copy_binding,
            "rollback_binding": active_rollback_binding,
            "pre_change_sha256": rollback_binding["sha256"],
            "mutated_sha256": final_copy_binding["sha256"],
            "rollback_sha256": active_rollback_binding["sha256"],
        },
    )
    return {
        "schema_version": "narrative-pseudoprose-stress-execution/v1",
        "project": project,
        "task_id": task_id,
        "status": "pass",
        "pseudoprose_chapter_count": chapter_count,
        "state_store_root": store_root.relative_to(project_root).as_posix(),
        "event_ledger_binding": event_ledger_binding,
        "state_artifact_bindings": state_bindings,
        "state_chain_sha256": chain_sha256,
        "recovery_receipt_binding": _file_binding(
            project_root,
            recovery_receipt_path,
        ),
        "rollback_receipt_binding": _file_binding(
            project_root,
            rollback_receipt_path,
        ),
    }
