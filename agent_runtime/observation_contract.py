"""Governed, read-only input contracts for Observer tasks."""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

try:
    from agent_runtime.policies import assert_path_allowed
    from agent_runtime.schemas import WorkflowPlan
except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
    from policies import assert_path_allowed
    from schemas import WorkflowPlan


class ObservationContractError(ValueError):
    """Raised when an Observer input contract cannot be trusted."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _route_allows_observation(plan: WorkflowPlan) -> bool:
    return (
        plan.route.route_key == "observation_task"
        and "Observer" in plan.route.agents
        and (plan.production_pack or {}).get("pack_id") == "read_only_observation"
    )


def materialize_observation_contract(
    plan: WorkflowPlan,
    assigned_inputs: Iterable[str | Path],
    *,
    overwrite: bool = False,
) -> Path:
    """Seal explicitly assigned files into a read-only Observer contract.

    The caller must already have selected the configured observation route. Each
    input is copied into the task run, made read-only, and bound by exact size and
    SHA-256. No directory scan or filename inference is performed.
    """
    if not _route_allows_observation(plan):
        raise ObservationContractError(
            "observation inputs require observation_task/read_only_observation"
        )

    root = Path(plan.agentlab_root)
    run_dir = assert_path_allowed(plan.run_dir, root)
    contract_path = assert_path_allowed(
        run_dir / "observation_contract.yml",
        run_dir,
    )
    if contract_path.exists() and not overwrite:
        raise ObservationContractError(
            f"observation contract already exists: {contract_path}"
        )

    explicit_inputs = [Path(item) for item in assigned_inputs]
    if not explicit_inputs:
        raise ObservationContractError("at least one observation input is required")

    input_dir = run_dir / "assigned_inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    input_dir = assert_path_allowed(input_dir, run_dir)
    rows: list[dict[str, Any]] = []
    for index, raw_path in enumerate(explicit_inputs, start=1):
        source = assert_path_allowed(raw_path, root)
        if not source.is_file():
            raise ObservationContractError(f"observation input is not a file: {source}")
        source_size = source.stat().st_size
        source_hash = _sha256(source)
        destination = assert_path_allowed(
            input_dir / f"{index:02d}_{source.name}",
            run_dir,
        )
        if destination.exists():
            destination.chmod(0o600)
            destination.unlink()
        shutil.copy2(source, destination)
        destination.chmod(0o400)
        staged_size = destination.stat().st_size
        staged_hash = _sha256(destination)
        if staged_size != source_size or staged_hash != source_hash:
            raise ObservationContractError(
                f"observation input changed while being sealed: {source.name}"
            )
        rows.append(
            {
                "input_id": f"input_{index:02d}",
                "source_filename": source.name,
                "path": str(destination.relative_to(run_dir)),
                "media_type": source.suffix.lower().lstrip(".") or "unknown",
                "size_bytes": staged_size,
                "sha256": staged_hash,
                "read_only": True,
            }
        )

    packet = {
        "schema_version": 1,
        "packet_type": "agentlab_observation_contract",
        "project": plan.project,
        "task_id": plan.task_id,
        "route_key": plan.route.route_key,
        "production_pack": (plan.production_pack or {}).get("pack_id"),
        "assigned_role": "Observer",
        "candidate_only": True,
        "production_modified": False,
        "self_approval_allowed": False,
        "assigned_inputs": rows,
        "materialized_at": datetime.now(timezone.utc).isoformat(),
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(
        yaml.safe_dump(packet, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return contract_path


def validated_observation_inputs(plan: WorkflowPlan) -> list[Path]:
    """Resolve exact contract inputs, failing closed on path/hash drift."""
    root = Path(plan.agentlab_root)
    run_dir = assert_path_allowed(plan.run_dir, root)
    contract_path = assert_path_allowed(
        run_dir / "observation_contract.yml",
        run_dir,
    )
    if not contract_path.is_file():
        return []
    try:
        packet = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ObservationContractError("observation contract is unreadable") from exc
    if not isinstance(packet, dict) or packet.get("packet_type") != "agentlab_observation_contract":
        raise ObservationContractError("observation contract packet_type is invalid")
    if packet.get("project") != plan.project or packet.get("task_id") != plan.task_id:
        raise ObservationContractError("observation contract task binding is invalid")
    if packet.get("route_key") != "observation_task" or packet.get("assigned_role") != "Observer":
        raise ObservationContractError("observation contract route/role binding is invalid")
    if (
        packet.get("production_pack") != "read_only_observation"
        or packet.get("candidate_only") is not True
        or packet.get("production_modified") is not False
        or packet.get("self_approval_allowed") is not False
    ):
        raise ObservationContractError("observation contract read-only boundary is invalid")
    assigned = packet.get("assigned_inputs")
    if not isinstance(assigned, list) or not assigned:
        raise ObservationContractError("observation contract has no assigned inputs")

    resolved_inputs: list[Path] = []
    for item in assigned:
        if not isinstance(item, dict):
            raise ObservationContractError("observation input row is invalid")
        raw_path = item.get("path")
        expected_hash = str(item.get("sha256") or "")
        try:
            expected_size = int(item.get("size_bytes"))
        except (TypeError, ValueError) as exc:
            raise ObservationContractError("observation input size binding is invalid") from exc
        if not isinstance(raw_path, str) or not raw_path.strip() or len(expected_hash) != 64:
            raise ObservationContractError("observation input path/hash binding is invalid")
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = run_dir / candidate
        resolved = assert_path_allowed(candidate, run_dir)
        if not resolved.is_file():
            raise ObservationContractError(
                f"assigned observation input is missing: {raw_path}"
            )
        if resolved.stat().st_size != expected_size or _sha256(resolved) != expected_hash:
            raise ObservationContractError(
                f"assigned observation input integrity mismatch: {raw_path}"
            )
        if item.get("read_only") is not True or resolved.stat().st_mode & 0o222:
            raise ObservationContractError(
                f"assigned observation input is not read-only: {raw_path}"
            )
        resolved_inputs.append(resolved)
    return resolved_inputs
