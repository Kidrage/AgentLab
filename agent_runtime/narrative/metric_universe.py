"""Deterministic projector for complete narrative release-metric universes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import hashlib
import json
import os
import re

import yaml

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.task_runtime_v2 import TaskRuntime


TOOL_ID = "agentlab.narrative.metric_universe_projector"
TOOL_VERSION = "1"
_METRIC_ID = re.compile(r"^[a-z][a-z0-9_]{2,80}$")
_SUBJECT_PRODUCERS = {
    "hard_continuity_errors": (
        "narrative-hard-continuity-audit",
        "canon_timeline_steward",
        "Reviewer",
    ),
    "planted_fact_and_promise_recall": (
        "narrative-retrieval-trace",
        "research_style_curator",
        "Researcher",
    ),
    "state_and_retrieval_traceability": (
        "narrative-traceability-record",
        "state_projector",
        "Scribe",
    ),
    "cross_project_knowledge_leaks": (
        "narrative-knowledge-isolation-audit",
        "canon_timeline_steward",
        "Reviewer",
    ),
    "due_promise_resolution_rate": (
        "narrative-promise-disposition",
        "foreshadow_mystery_keeper",
        "Reviewer",
    ),
    "blind_preference_rate": (
        "narrative-blind-review-vote",
        "reader_simulation_panel",
        "Reviewer",
    ),
    "consecutive_windows_without_core_regression": (
        "narrative-window-acceptance",
        "authorial_director",
        "Supervisor",
    ),
}


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _safe_project_path(project_root: Path, path: Path) -> Path:
    root = Path(project_root).resolve(strict=True)
    raw = Path(path)
    selected = raw if raw.is_absolute() else root / raw
    cursor = root
    try:
        relative = selected.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise ValueError("metric universe path must remain inside project") from exc
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("metric universe path may not use symlinks")
    return selected.resolve(strict=False)


def _subject_inventory(
    agentlab_root: Path,
    project_root: Path,
    *,
    metric_id: str,
) -> tuple[str, list[dict[str, str]], str]:
    if (
        not _METRIC_ID.fullmatch(metric_id)
        or metric_id not in _SUBJECT_PRODUCERS
    ):
        raise ValueError("metric_id is invalid")
    root = Path(project_root).resolve(strict=True)
    subject_root = _safe_project_path(
        root,
        Path("acceptance") / "metric-subjects" / metric_id,
    )
    if not subject_root.is_dir():
        raise ValueError("metric subject authority directory is missing")
    subject_paths: list[Path] = []
    for directory, directory_names, file_names in os.walk(
        subject_root,
        followlinks=False,
    ):
        current = Path(directory)
        for name in [*directory_names, *file_names]:
            entry = current / name
            if entry.is_symlink():
                raise ValueError(
                    "metric subject authority may not use symlinks"
                )
        for name in file_names:
            path = current / name
            if path.suffix != ".yml" or not path.is_file():
                raise ValueError(
                    "metric subject authority contains an undeclared file"
                )
            subject_paths.append(path)
    bindings: list[dict[str, str]] = []
    observed_attempts: dict[tuple[str, str], dict[str, str]] = {}
    for path in sorted(subject_paths):
        resolved = _safe_project_path(root, path).resolve(strict=True)
        try:
            document = yaml.safe_load(resolved.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise ValueError("metric subject authority is unreadable") from exc
        if (
            not isinstance(document, Mapping)
            or document.get("project") != root.name
            or document.get("status") != "pass"
        ):
            raise ValueError("metric subject authority contract is invalid")
        runtime_binding = document.get("runtime_binding")
        if not isinstance(runtime_binding, Mapping):
            raise ValueError("metric subject runtime binding is required")
        identity = (
            str(runtime_binding.get("task_id") or ""),
            str(runtime_binding.get("attempt_id") or ""),
        )
        work_item_id = str(runtime_binding.get("work_item_id") or "")
        if (
            not all(identity)
            or not work_item_id
            or identity in observed_attempts
        ):
            raise ValueError("metric subject runtime binding is invalid")
        binding = {
            "path": resolved.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
        }
        bindings.append(binding)
        observed_attempts[identity] = {
            **binding,
            "work_item_id": work_item_id,
        }
    if not bindings:
        raise ValueError("metric subject authority is empty")

    runtime = TaskRuntime(Path(agentlab_root), project=root.name)
    expected_kind, expected_agent_id, expected_role = _SUBJECT_PRODUCERS[
        metric_id
    ]
    expected_attempts: dict[tuple[str, str], dict[str, str]] = {}
    for task in runtime.list_tasks():
        task_id = str(task.get("task_id") or "")
        projection = runtime.load_task(task_id)
        work_items = projection.get("work_items")
        attempts = projection.get("attempts")
        if not isinstance(work_items, Mapping) or not isinstance(
            attempts,
            Mapping,
        ):
            raise ValueError("metric subject runtime projection is invalid")
        for attempt_id, attempt in attempts.items():
            if (
                not isinstance(attempt, Mapping)
                or attempt.get("status") != "succeeded"
            ):
                continue
            work_item_id = str(attempt.get("work_item_id") or "")
            work_item = work_items.get(work_item_id)
            if (
                not isinstance(work_item, Mapping)
                or work_item.get("kind") != expected_kind
            ):
                continue
            execution_contract = attempt.get("execution_contract")
            if (
                work_item.get("assigned_agent_id") != expected_agent_id
                or not isinstance(execution_contract, Mapping)
                or execution_contract.get("role") != expected_role
            ):
                raise ValueError(
                    "metric subject runtime producer is invalid"
                )
            verification = runtime.verify_attempt_execution_receipt(
                task_id,
                str(attempt_id),
            )
            output_sha256 = str(
                verification.get("output_sha256") or ""
            )
            if not re.fullmatch(r"[0-9a-f]{64}", output_sha256):
                raise ValueError(
                    "metric subject runtime receipt is invalid"
                )
            expected_attempts[(task_id, str(attempt_id))] = {
                "work_item_id": work_item_id,
                "sha256": output_sha256,
            }
    if set(expected_attempts) != set(observed_attempts):
        raise ValueError(
            "metric subject set does not match successful runtime attempts"
        )
    for identity, expected in expected_attempts.items():
        observed = observed_attempts[identity]
        if (
            observed["work_item_id"] != expected["work_item_id"]
            or observed["sha256"] != expected["sha256"]
        ):
            raise ValueError("metric subject runtime output mismatch")

    subject_root_relative = subject_root.relative_to(root).as_posix()
    input_tree_sha256 = _sha256_json(
        {
            "metric_id": metric_id,
            "subject_root": subject_root_relative,
            "subject_bindings": bindings,
            "runtime_attempts": [
                {
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    **expected_attempts[(task_id, attempt_id)],
                }
                for task_id, attempt_id in sorted(expected_attempts)
            ],
        }
    )
    return subject_root_relative, bindings, input_tree_sha256


def project_metric_universe(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    attempt_id: str,
    metric_id: str,
    work_item_id: str | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Project every authoritative metric subject into one sealed universe."""

    root = Path(agentlab_root).resolve(strict=True)
    project_root = (root / "projects" / project).resolve(strict=True)
    if project_root.name != project:
        raise ValueError("project path identity mismatch")
    subject_root, bindings, input_tree_sha256 = _subject_inventory(
        root,
        project_root,
        metric_id=metric_id,
    )
    selected_output = _safe_project_path(
        project_root,
        output_path
        or (
            Path("runs")
            / task_id
            / f"metric_universe_{metric_id}.yml"
        ),
    )
    document = {
        "schema_version": "narrative-runtime-stage-evidence/v1",
        "project": project,
        "status": "pass",
        "stage": "P5",
        "task_id": task_id,
        "attempt_id": attempt_id,
        "kind": "metric_universe",
        "work_item_id": work_item_id or f"work-{attempt_id}",
        "metric_id": metric_id,
        "producer": {
            "executor_type": "deterministic_tool",
            "tool_id": TOOL_ID,
            "tool_version": TOOL_VERSION,
            "subject_root": subject_root,
            "input_tree_sha256": input_tree_sha256,
            "input_count": len(bindings),
        },
        "metric_universe": {
            "schema_version": "narrative-release-metric-universe/v1",
            "project": project,
            "metric_id": metric_id,
            "status": "sealed",
            "subject_bindings": bindings,
        },
    }
    selected_output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(selected_output, document)
    return {
        **document,
        "artifact": {
            "path": selected_output.relative_to(project_root).as_posix(),
            "sha256": hashlib.sha256(selected_output.read_bytes()).hexdigest(),
        },
    }


def metric_universe_input_contract(
    agentlab_root: Path,
    *,
    project: str,
    metric_id: str,
) -> dict[str, Any]:
    """Return the exact allowlisted input identity before scheduling execution."""

    root = Path(agentlab_root).resolve(strict=True)
    project_root = (root / "projects" / project).resolve(strict=True)
    subject_root, bindings, input_tree_sha256 = _subject_inventory(
        root,
        project_root,
        metric_id=metric_id,
    )
    return {
        "tool_id": TOOL_ID,
        "tool_version": TOOL_VERSION,
        "metric_id": metric_id,
        "subject_root": subject_root,
        "input_tree_sha256": input_tree_sha256,
        "input_count": len(bindings),
    }


def metric_universe_issues(
    project_root: Path,
    document: Mapping[str, Any],
) -> list[str]:
    """Recompute the authority tree and reject hand-written or stale universes."""

    root = Path(project_root).resolve(strict=True)
    metric_id = str(document.get("metric_id") or "")
    producer = document.get("producer")
    universe = document.get("metric_universe")
    if (
        document.get("schema_version")
        != "narrative-runtime-stage-evidence/v1"
        or document.get("project") != root.name
        or document.get("status") != "pass"
        or document.get("stage") != "P5"
        or document.get("kind") != "metric_universe"
        or not isinstance(producer, Mapping)
        or not isinstance(universe, Mapping)
    ):
        return ["projector_contract_invalid"]
    try:
        subject_root, bindings, input_tree_sha256 = _subject_inventory(
            root.parents[1],
            root,
            metric_id=metric_id,
        )
    except (OSError, ValueError):
        return ["projector_input_invalid"]
    issues: list[str] = []
    if (
        producer.get("executor_type") != "deterministic_tool"
        or producer.get("tool_id") != TOOL_ID
        or producer.get("tool_version") != TOOL_VERSION
    ):
        issues.append("projector_identity_invalid")
    if (
        producer.get("subject_root") != subject_root
        or producer.get("input_tree_sha256") != input_tree_sha256
        or producer.get("input_count") != len(bindings)
    ):
        issues.append("projector_input_binding_invalid")
    if universe.get("subject_bindings") != bindings:
        issues.append("projector_output_mismatch")
    return issues


__all__ = [
    "TOOL_ID",
    "TOOL_VERSION",
    "metric_universe_input_contract",
    "metric_universe_issues",
    "project_metric_universe",
]
