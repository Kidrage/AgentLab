"""Event-ledger authority and rebuildable projections for Task Runtime v2."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Callable, Iterator
import uuid
import yaml

from agent_runtime.atomic_io import atomic_write_yaml
from .input_tiers import TaskInputClassifier


EVENT_SCHEMA = "task-runtime-event/v2"
PROJECTION_SCHEMA = "task-runtime-projection/v2"
PROJECT_INDEX_SCHEMA = "task-runtime-project-index/v2"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class TaskRuntimeError(RuntimeError):
    """Base error raised by the Task Runtime v2 interface."""


class LedgerIntegrityError(TaskRuntimeError):
    """The append-only ledger cannot be trusted or projected."""


class IdempotencyConflict(TaskRuntimeError):
    """An idempotency key was reused for a different command."""


class InvalidTransition(TaskRuntimeError):
    """A lifecycle transition violates the declared state machine."""


class EntityNotFound(TaskRuntimeError):
    """A referenced Task Runtime entity does not exist."""


class EntityAlreadyExists(TaskRuntimeError):
    """A command attempted to create an existing entity."""


class ActiveAttemptExists(TaskRuntimeError):
    """A WorkItem already owns a non-terminal Attempt lease."""


class DuplicateBusinessGoal(TaskRuntimeError):
    """A caller attempted to split one business goal across Task identities."""


TASK_TRANSITIONS: dict[str, set[str]] = {
    "created": {"ready", "paused", "cancelled"},
    "ready": {"running", "blocked", "paused", "cancelled"},
    "running": {"waiting", "completed", "blocked", "paused", "failed", "cancelled"},
    "waiting": {"running", "blocked", "paused", "cancelled"},
    "blocked": {"ready", "running", "cancelled"},
    "paused": {"ready", "running", "cancelled"},
    "completed": {"ready"},
    "cancelled": set(),
    "failed": {"ready"},
}

ATTEMPT_TRANSITIONS: dict[str, set[str]] = {
    "scheduled": {"running", "cancelled"},
    "running": {"succeeded", "failed", "cancelled"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
}
ACTIVE_ATTEMPT_STATUSES = {"scheduled", "running"}
WORK_ITEM_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"cancelled"},
    "ready": {"running", "blocked", "cancelled"},
    "running": {"waiting_review", "accepted", "failed", "blocked", "cancelled"},
    "waiting_review": {"running", "accepted", "failed", "blocked", "cancelled"},
    "blocked": {"ready", "running", "cancelled"},
    "accepted": set(),
    "failed": set(),
    "cancelled": set(),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _event_hash(event_without_hash: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(event_without_hash).encode("utf-8")).hexdigest()


def _goal_fingerprint(user_goal: str) -> str:
    normalized = " ".join(user_goal.casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _validated_id(value: str, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not _SAFE_ID.fullmatch(normalized):
        raise ValueError(f"{field} must match {_SAFE_ID.pattern}")
    return normalized


class TaskRuntime:
    """Deep module for commands, ledger integrity, and deterministic projections."""

    def __init__(self, agentlab_root: Path, *, project: str) -> None:
        self.agentlab_root = Path(agentlab_root).resolve(strict=False)
        self.project = _validated_id(project, field="project")
        self.tasks_root = self.agentlab_root / "projects" / self.project / "runtime" / "tasks"

    def create_task(
        self,
        *,
        task_id: str,
        title: str,
        user_goal: str,
        idempotency_key: str,
        input_profile: dict[str, Any] | None = None,
        legacy_source: dict[str, Any] | None = None,
        allow_duplicate_goal: bool = False,
        independent_boundary_reason: str | None = None,
    ) -> dict[str, Any]:
        """Create one stable business task and return its current projection."""

        task_id = _validated_id(task_id, field="task_id")
        title = str(title or "").strip()
        user_goal = str(user_goal or "").strip()
        if not title or not user_goal:
            raise ValueError("title and user_goal are required")
        if legacy_source is not None and not isinstance(legacy_source, dict):
            raise ValueError("legacy_source must be a mapping")
        if input_profile is not None and not isinstance(input_profile, dict):
            raise ValueError("input_profile must be a mapping")
        boundary_reason = str(independent_boundary_reason or "").strip()
        if allow_duplicate_goal and not boundary_reason:
            raise ValueError(
                "independent_boundary_reason is required when allowing a duplicate goal"
            )
        declared_input_profile = dict(input_profile or {})
        input_classification = TaskInputClassifier(self.agentlab_root).classify(
            input_profile
        )
        payload: dict[str, Any] = {
            "title": title,
            "user_goal": user_goal,
            "goal_fingerprint": _goal_fingerprint(user_goal),
            "default_job": {"job_id": "job-main", "kind": "inline"},
            "input_profile": declared_input_profile,
            "input_classification": input_classification,
        }
        if legacy_source is not None:
            payload["legacy_source"] = legacy_source
        if allow_duplicate_goal:
            payload["duplicate_goal_override"] = {
                "independent_boundary_reason": boundary_reason
            }
        with self._admission_lock():
            if not allow_duplicate_goal:
                self._assert_unique_business_goal(
                    task_id=task_id, goal_fingerprint=payload["goal_fingerprint"]
                )
            self._append_event(
                task_id=task_id,
                event_type="TASK_CREATED",
                entity_type="task",
                entity_id=task_id,
                idempotency_key=idempotency_key,
                payload=payload,
            )
        return self.rebuild_task(task_id)

    def rebuild_task(self, task_id: str) -> dict[str, Any]:
        """Validate the ledger and deterministically replace all task projections."""

        task_id = _validated_id(task_id, field="task_id")
        with self._ledger_lock(task_id):
            events = self._load_events(task_id)
            projection = self._project(events, task_id=task_id)
            projection_dir = self._task_dir(task_id) / "projections"
            projection_dir.mkdir(parents=True, exist_ok=True)
            self._write_task_projections(projection_dir, projection)
        return projection

    def rebuild_project(self) -> dict[str, Any]:
        """Rebuild every Task projection and the project index from authoritative ledgers."""

        tasks: list[dict[str, Any]] = []
        selected_records: list[dict[str, Any]] = []
        if self.tasks_root.exists():
            for task_dir in sorted(path for path in self.tasks_root.iterdir() if path.is_dir()):
                projection = self.rebuild_task(task_dir.name)
                tasks.append(
                    {
                        "task_id": task_dir.name,
                        "title": projection["task"]["title"],
                        "status": projection["task"]["status"],
                        "job_count": len(projection["jobs"]),
                        "work_item_count": len(projection["work_items"]),
                        "attempt_count": len(projection["attempts"]),
                        "selected_artifact_version": projection[
                            "selected_artifact_version"
                        ],
                        "last_event_sequence": projection["last_event_sequence"],
                        "last_event_hash": projection["last_event_hash"],
                    }
                )
                selected_version = projection["selected_artifact_version"]
                if selected_version:
                    artifact = projection["artifacts"][selected_version]
                    attempt = projection["attempts"][artifact["producer_attempt_id"]]
                    selected_records.append(
                        {
                            "task_id": task_dir.name,
                            "artifact_id": artifact["artifact_id"],
                            "version_id": selected_version,
                            "sha256": artifact["sha256"],
                            "media_type": artifact["media_type"],
                            "producer": {
                                "attempt_id": attempt["attempt_id"],
                                "worker": attempt["worker"],
                                "provider": attempt["provider"],
                                "execution_contract_hash": attempt[
                                    "execution_contract_hash"
                                ],
                            },
                            "evidence": [
                                {
                                    "binding_id": binding["binding_id"],
                                    "input_manifest_hash": binding[
                                        "input_manifest_hash"
                                    ],
                                    "index_snapshot_id": binding[
                                        "index_snapshot_id"
                                    ],
                                    "source_hashes": binding["source_hashes"],
                                    "audit": binding["audit"],
                                    "execution_receipt": binding["execution_receipt"],
                                }
                                for binding in projection["evidence_bindings"].values()
                                if binding["version_id"] == selected_version
                            ],
                        }
                    )
        index = {
            "schema_version": PROJECT_INDEX_SCHEMA,
            "project": self.project,
            "task_count": len(tasks),
            "tasks": tasks,
        }
        runtime_root = self.tasks_root.parent
        runtime_root.mkdir(parents=True, exist_ok=True)
        atomic_write_yaml(runtime_root / "task_index.yml", index)
        knowledge_root = runtime_root / "knowledge"
        knowledge_root.mkdir(parents=True, exist_ok=True)
        atomic_write_yaml(
            knowledge_root / "selected_artifacts.yml",
            {
                "schema_version": "task-runtime-selected-artifacts/v2",
                "project": self.project,
                "selected_artifacts": selected_records,
            },
        )
        return index

    def list_tasks(self, *, include_legacy: bool = True) -> list[dict[str, Any]]:
        """Dual-read task catalog; v2 wins and all writes still target v2 only."""

        entries: dict[str, dict[str, Any]] = {}
        if self.tasks_root.exists():
            for task_dir in sorted(path for path in self.tasks_root.iterdir() if path.is_dir()):
                with self._ledger_lock(task_dir.name):
                    events = self._load_events(task_dir.name)
                    projection = self._project(events, task_id=task_dir.name)
                entries[task_dir.name] = {
                    "task_id": task_dir.name,
                    "status": projection["task"]["status"],
                    "title": projection["task"]["title"],
                    "storage": "v2",
                }
        if include_legacy:
            runs_root = self.agentlab_root / "projects" / self.project / "runs"
            if runs_root.is_dir():
                for run_dir in sorted(
                    path
                    for path in runs_root.iterdir()
                    if path.is_dir() and not path.is_symlink()
                ):
                    state_path = run_dir / "state.yml"
                    if not state_path.is_file() or state_path.is_symlink():
                        continue
                    state = yaml.safe_load(state_path.read_text(encoding="utf-8")) or {}
                    if not isinstance(state, dict):
                        raise LedgerIntegrityError(
                            f"legacy state is not a mapping: {state_path}"
                        )
                    task_id = _validated_id(
                        str(state.get("task_id") or run_dir.name), field="task_id"
                    )
                    entries.setdefault(
                        task_id,
                        {
                            "task_id": task_id,
                            "status": str(state.get("status") or "unknown"),
                            "title": task_id,
                            "storage": "legacy-read-only",
                        },
                    )
        return [entries[task_id] for task_id in sorted(entries)]

    def doctor_project(self) -> dict[str, Any]:
        """Read-only integrity diagnosis for every v2 ledger in a project."""

        reports: dict[str, dict[str, Any]] = {}
        if self.tasks_root.exists():
            for task_dir in sorted(path for path in self.tasks_root.iterdir() if path.is_dir()):
                try:
                    with self._ledger_lock(task_dir.name):
                        events = self._load_events(task_dir.name)
                        projection = self._project(events, task_id=task_dir.name)
                    artifact_failures: list[str] = []
                    for version_id, artifact in projection["artifacts"].items():
                        path = task_dir / artifact["path"]
                        if path.is_symlink():
                            artifact_failures.append(
                                f"{version_id}: artifact path is a symlink"
                            )
                        elif not path.is_file():
                            artifact_failures.append(f"{version_id}: artifact file missing")
                        elif hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
                            artifact_failures.append(f"{version_id}: artifact SHA256 mismatch")
                    for record_id, record in projection["trace_records"].items():
                        path = task_dir / record["path"]
                        if path.is_symlink():
                            artifact_failures.append(
                                f"{record_id}: trace record path is a symlink"
                            )
                        elif not path.is_file():
                            artifact_failures.append(f"{record_id}: trace record file missing")
                        elif hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
                            artifact_failures.append(
                                f"{record_id}: trace record SHA256 mismatch"
                            )
                    reports[task_dir.name] = {
                        "ok": not artifact_failures,
                        "event_count": len(events),
                        "last_event_hash": projection["last_event_hash"],
                        "failures": artifact_failures,
                    }
                except (TaskRuntimeError, ValueError, OSError) as exc:
                    reports[task_dir.name] = {"ok": False, "failures": [str(exc)]}
        return {
            "project": self.project,
            "ok": all(report["ok"] for report in reports.values()),
            "task_count": len(reports),
            "tasks": reports,
        }

    def transition_task(
        self,
        task_id: str,
        *,
        status: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Append one validated Task lifecycle transition."""

        task_id = _validated_id(task_id, field="task_id")
        status = str(status or "").strip().lower()
        if status not in TASK_TRANSITIONS:
            raise ValueError(f"unknown task status: {status}")

        def validate(projection: dict[str, Any]) -> None:
            if status != "completed":
                return
            unfinished = sorted(
                work_item_id
                for work_item_id, work_item in projection["work_items"].items()
                if work_item["status"] not in {"accepted", "cancelled"}
            )
            if unfinished:
                raise InvalidTransition(
                    "task completion requires accepted/cancelled work items: "
                    + ", ".join(unfinished)
                )
            if projection["artifacts"] and not projection["selected_artifact_version"]:
                raise InvalidTransition(
                    "task completion requires one evidenced selected artifact version"
                )
            classification = projection["task"].get("input_classification") or {}
            if projection["task"].get("legacy_source") is None:
                if not classification.get("admission_ready"):
                    raise InvalidTransition(
                        "task completion requires a complete input classification"
                    )
                available_records = {
                    record["record_type"]
                    for record in projection["trace_records"].values()
                }
                if projection["evidence_bindings"]:
                    available_records.add("evidence_binding")
                required_records = set(classification.get("required_records") or [])
                required_records.discard("input_classification")
                missing_records = sorted(required_records - available_records)
                if missing_records:
                    raise InvalidTransition(
                        "task completion has missing required trace records: "
                        + ", ".join(missing_records)
                    )
        self._append_event(
            task_id=task_id,
            event_type="TASK_STATUS_CHANGED",
            entity_type="task",
            entity_id=task_id,
            idempotency_key=idempotency_key,
            payload={"status": status},
            expected_task_statuses={
                current for current, allowed in TASK_TRANSITIONS.items() if status in allowed
            },
            validate_projection=validate,
        )
        return self.rebuild_task(task_id)

    def create_work_item(
        self,
        task_id: str,
        *,
        job_id: str,
        work_item_id: str,
        kind: str,
        title: str,
        idempotency_key: str,
        depends_on: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a schedulable unit inside an existing Job and Task."""

        task_id = _validated_id(task_id, field="task_id")
        job_id = _validated_id(job_id, field="job_id")
        work_item_id = _validated_id(work_item_id, field="work_item_id")
        kind = _validated_id(kind, field="kind")
        title = str(title or "").strip()
        if not title:
            raise ValueError("work item title is required")
        dependencies = [
            _validated_id(item, field="depends_on") for item in (depends_on or [])
        ]

        def validate(projection: dict[str, Any]) -> None:
            if projection["task"]["status"] in {"completed", "failed", "cancelled"}:
                raise InvalidTransition("reopen the Task before adding a WorkItem")
            if job_id not in projection["jobs"]:
                raise EntityNotFound(f"job {job_id!r} does not exist")
            if work_item_id in projection["work_items"]:
                raise EntityAlreadyExists(f"work item {work_item_id!r} already exists")
            missing = [item for item in dependencies if item not in projection["work_items"]]
            if missing:
                raise EntityNotFound(f"work item dependencies do not exist: {', '.join(missing)}")

        self._append_event(
            task_id=task_id,
            event_type="WORK_ITEM_CREATED",
            entity_type="work_item",
            entity_id=work_item_id,
            idempotency_key=idempotency_key,
            payload={
                "job_id": job_id,
                "kind": kind,
                "title": title,
                "depends_on": dependencies,
            },
            validate_projection=validate,
        )
        return self.rebuild_task(task_id)

    def create_job(
        self,
        task_id: str,
        *,
        job_id: str,
        kind: str,
        strategy: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Create an alternative execution strategy under one business Task."""

        task_id = _validated_id(task_id, field="task_id")
        job_id = _validated_id(job_id, field="job_id")
        kind = _validated_id(kind, field="kind")
        strategy = str(strategy or "").strip()
        if not strategy:
            raise ValueError("job strategy is required")

        def validate(projection: dict[str, Any]) -> None:
            if projection["task"]["status"] in {"completed", "failed", "cancelled"}:
                raise InvalidTransition("reopen the Task before adding a Job")
            if job_id in projection["jobs"]:
                raise EntityAlreadyExists(f"job {job_id!r} already exists")

        self._append_event(
            task_id=task_id,
            event_type="JOB_CREATED",
            entity_type="job",
            entity_id=job_id,
            idempotency_key=idempotency_key,
            payload={"kind": kind, "strategy": strategy},
            validate_projection=validate,
        )
        return self.rebuild_task(task_id)

    def transition_work_item(
        self,
        task_id: str,
        *,
        work_item_id: str,
        status: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Advance one schedulable unit and deterministically unlock dependants."""

        task_id = _validated_id(task_id, field="task_id")
        work_item_id = _validated_id(work_item_id, field="work_item_id")
        status = str(status or "").strip().lower()
        if status not in WORK_ITEM_TRANSITIONS:
            raise ValueError(f"unknown work item status: {status}")
        payload: dict[str, Any] = {"status": status}

        def validate(projection: dict[str, Any]) -> None:
            work_item = projection["work_items"].get(work_item_id)
            if work_item is None:
                raise EntityNotFound(f"work item {work_item_id!r} does not exist")
            current = work_item["status"]
            if status not in WORK_ITEM_TRANSITIONS[current]:
                raise InvalidTransition(
                    f"work item cannot transition from {current!r} to {status!r}"
                )
            if status in {"accepted", "failed", "cancelled"} and work_item.get(
                "active_attempt_id"
            ):
                raise InvalidTransition("terminal work item transition requires no active attempt")
            payload["from_status"] = current

        self._append_event(
            task_id=task_id,
            event_type="WORK_ITEM_STATUS_CHANGED",
            entity_type="work_item",
            entity_id=work_item_id,
            idempotency_key=idempotency_key,
            payload=payload,
            validate_projection=validate,
            idempotency_ignored_payload_keys={"from_status"},
        )
        return self.rebuild_task(task_id)

    def schedule_attempt(
        self,
        task_id: str,
        *,
        work_item_id: str,
        attempt_id: str,
        worker: str,
        provider: str,
        execution_contract: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Lease one WorkItem to one immutable execution Attempt."""

        task_id = _validated_id(task_id, field="task_id")
        work_item_id = _validated_id(work_item_id, field="work_item_id")
        attempt_id = _validated_id(attempt_id, field="attempt_id")
        worker = _validated_id(worker, field="worker")
        provider = _validated_id(provider, field="provider")
        if not isinstance(execution_contract, dict) or not execution_contract:
            raise ValueError("execution_contract must be a non-empty mapping")

        payload: dict[str, Any] = {
            "work_item_id": work_item_id,
            "worker": worker,
            "provider": provider,
            "execution_contract": execution_contract,
            "execution_contract_hash": hashlib.sha256(
                _canonical_json(execution_contract).encode("utf-8")
            ).hexdigest(),
        }

        def validate(projection: dict[str, Any]) -> None:
            work_item = projection["work_items"].get(work_item_id)
            if work_item is None:
                raise EntityNotFound(f"work item {work_item_id!r} does not exist")
            if attempt_id in projection["attempts"]:
                raise EntityAlreadyExists(f"attempt {attempt_id!r} already exists")
            if projection["task"]["status"] in {
                "completed",
                "failed",
                "cancelled",
                "paused",
            }:
                raise InvalidTransition("Task is not accepting execution Attempts")
            if work_item["status"] not in {
                "ready",
                "running",
                "waiting_review",
                "blocked",
            }:
                raise InvalidTransition(
                    f"work item status {work_item['status']!r} cannot schedule an Attempt"
                )
            classification = projection["task"].get("input_classification") or {}
            if projection["task"].get("legacy_source") is None:
                if not classification.get("admission_ready"):
                    raise InvalidTransition(
                        "execution requires a complete Brain input classification"
                    )
                if execution_contract.get("input_tier") != classification.get("tier"):
                    raise InvalidTransition(
                        "execution contract input_tier does not match Task classification"
                    )
                if execution_contract.get("route") != classification.get("route"):
                    raise InvalidTransition(
                        "execution contract route does not match Task classification"
                    )
                role = str(execution_contract.get("role") or "")
                if not role:
                    raise InvalidTransition("execution contract must declare its AgentLab role")
                delegated = role != "Supervisor"
                tier = str(classification.get("tier") or "")
                if tier == "L0" and delegated:
                    raise InvalidTransition("L0 permits Brain-direct execution only")
                if tier in {"L1", "L2"} and delegated:
                    delegated_workers = {
                        (attempt["worker"], attempt["provider"])
                        for attempt in projection["attempts"].values()
                        if str(
                            (attempt.get("execution_contract") or {}).get("role") or ""
                        )
                        != "Supervisor"
                    }
                    if delegated_workers and (worker, provider) not in delegated_workers:
                        raise InvalidTransition(
                            f"{tier} permits one delegated worker identity"
                        )
                if tier == "L3" and delegated:
                    record_types = {
                        record["record_type"]
                        for record in projection["trace_records"].values()
                    }
                    if not {"brain_scope_decision", "execution_plan"}.issubset(
                        record_types
                    ):
                        raise InvalidTransition(
                            "L3 Worker execution requires Brain scope and execution plan records"
                        )
            active = work_item.get("active_attempt_id")
            if active:
                raise ActiveAttemptExists(
                    f"work item {work_item_id!r} already has active attempt {active!r}"
                )
            payload["ordinal"] = 1 + sum(
                attempt["work_item_id"] == work_item_id
                for attempt in projection["attempts"].values()
            )

        self._append_event(
            task_id=task_id,
            event_type="ATTEMPT_SCHEDULED",
            entity_type="attempt",
            entity_id=attempt_id,
            idempotency_key=idempotency_key,
            payload=payload,
            validate_projection=validate,
            idempotency_ignored_payload_keys={"ordinal"},
        )
        return self.rebuild_task(task_id)

    def record_trace(
        self,
        task_id: str,
        *,
        record_id: str,
        record_type: str,
        producer: str,
        path: Path,
        idempotency_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Pin one immutable execution, quality, change, or memory receipt."""

        task_id = _validated_id(task_id, field="task_id")
        record_id = _validated_id(record_id, field="record_id")
        record_type = _validated_id(record_type, field="record_type")
        producer = _validated_id(producer, field="producer")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be a mapping")
        resolved_path = Path(path).resolve(strict=True)
        records_root = (self._task_dir(task_id) / "records").resolve(strict=False)
        staging_root = records_root / "staging"
        immutable_root = records_root / "immutable"
        if not resolved_path.is_relative_to(staging_root):
            raise ValueError("trace record source must be inside records/staging")
        content = resolved_path.read_bytes()
        destination = immutable_root / record_id / f"payload{resolved_path.suffix or '.bin'}"
        payload = {
            "record_type": record_type,
            "producer": producer,
            "source_path": resolved_path.relative_to(self._task_dir(task_id)).as_posix(),
            "path": destination.relative_to(self._task_dir(task_id)).as_posix(),
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "metadata": metadata or {},
        }

        def validate(projection: dict[str, Any]) -> None:
            if record_id in projection["trace_records"]:
                raise EntityAlreadyExists(f"trace record {record_id!r} already exists")
            current = resolved_path.read_bytes()
            if hashlib.sha256(current).hexdigest() != payload["sha256"]:
                raise TaskRuntimeError("trace record source changed while recording")
            self._materialize_immutable(destination, current, payload["sha256"])

        self._append_event(
            task_id=task_id,
            event_type="TRACE_RECORDED",
            entity_type="trace_record",
            entity_id=record_id,
            idempotency_key=idempotency_key,
            payload=payload,
            validate_projection=validate,
        )
        return self.rebuild_task(task_id)

    def transition_attempt(
        self,
        task_id: str,
        *,
        attempt_id: str,
        status: str,
        idempotency_key: str,
        outcome: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Advance one Attempt without changing the Task identity."""

        task_id = _validated_id(task_id, field="task_id")
        attempt_id = _validated_id(attempt_id, field="attempt_id")
        status = str(status or "").strip().lower()
        if status not in ATTEMPT_TRANSITIONS:
            raise ValueError(f"unknown attempt status: {status}")
        if outcome is not None and not isinstance(outcome, dict):
            raise ValueError("outcome must be a mapping")
        payload: dict[str, Any] = {"status": status, "outcome": outcome or {}}

        def validate(projection: dict[str, Any]) -> None:
            attempt = projection["attempts"].get(attempt_id)
            if attempt is None:
                raise EntityNotFound(f"attempt {attempt_id!r} does not exist")
            current = attempt["status"]
            if status not in ATTEMPT_TRANSITIONS[current]:
                raise InvalidTransition(
                    f"attempt cannot transition from {current!r} to {status!r}"
                )
            payload["from_status"] = current

        self._append_event(
            task_id=task_id,
            event_type="ATTEMPT_STATUS_CHANGED",
            entity_type="attempt",
            entity_id=attempt_id,
            idempotency_key=idempotency_key,
            payload=payload,
            validate_projection=validate,
            idempotency_ignored_payload_keys={"from_status"},
        )
        return self.rebuild_task(task_id)

    def record_artifact_version(
        self,
        task_id: str,
        *,
        artifact_id: str,
        version_id: str,
        attempt_id: str,
        path: Path,
        media_type: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Record an immutable content-addressed output from a successful Attempt."""

        task_id = _validated_id(task_id, field="task_id")
        artifact_id = _validated_id(artifact_id, field="artifact_id")
        version_id = _validated_id(version_id, field="version_id")
        attempt_id = _validated_id(attempt_id, field="attempt_id")
        media_type = str(media_type or "").strip()
        if not media_type:
            raise ValueError("media_type is required")
        resolved_path = Path(path).resolve(strict=True)
        artifacts_root = (self._task_dir(task_id) / "artifacts").resolve(strict=False)
        if not resolved_path.is_relative_to(artifacts_root):
            raise ValueError("artifact path must be inside the task artifacts directory")
        versions_root = artifacts_root / "versions"
        if resolved_path.is_relative_to(versions_root):
            raise ValueError("artifact source must be outside the immutable versions directory")
        content = resolved_path.read_bytes()
        destination = versions_root / version_id / f"payload{resolved_path.suffix or '.bin'}"
        payload = {
            "artifact_id": artifact_id,
            "attempt_id": attempt_id,
            "source_path": resolved_path.relative_to(self._task_dir(task_id)).as_posix(),
            "path": destination.relative_to(self._task_dir(task_id)).as_posix(),
            "media_type": media_type,
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }

        def validate(projection: dict[str, Any]) -> None:
            attempt = projection["attempts"].get(attempt_id)
            if attempt is None:
                raise EntityNotFound(f"attempt {attempt_id!r} does not exist")
            if attempt["status"] != "succeeded":
                raise InvalidTransition("artifacts require a succeeded producer attempt")
            if version_id in projection["artifacts"]:
                raise EntityAlreadyExists(f"artifact version {version_id!r} already exists")
            current = resolved_path.read_bytes()
            if hashlib.sha256(current).hexdigest() != payload["sha256"]:
                raise TaskRuntimeError("artifact source changed while recording its version")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if destination.is_symlink():
                    raise LedgerIntegrityError("immutable artifact destination is a symlink")
                if hashlib.sha256(destination.read_bytes()).hexdigest() != payload["sha256"]:
                    raise EntityAlreadyExists(
                        f"immutable artifact destination already differs: {destination}"
                    )
                return
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
            )
            temp = Path(temp_name)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(current)
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    os.link(temp, destination)
                except FileExistsError:
                    if (
                        destination.is_symlink()
                        or hashlib.sha256(destination.read_bytes()).hexdigest()
                        != payload["sha256"]
                    ):
                        raise EntityAlreadyExists(
                            f"immutable artifact destination raced: {destination}"
                        )
            finally:
                if temp.exists():
                    temp.unlink()

        self._append_event(
            task_id=task_id,
            event_type="ARTIFACT_VERSION_RECORDED",
            entity_type="artifact_version",
            entity_id=version_id,
            idempotency_key=idempotency_key,
            payload=payload,
            validate_projection=validate,
        )
        return self.rebuild_task(task_id)

    def bind_evidence(
        self,
        task_id: str,
        *,
        binding_id: str,
        version_id: str,
        input_manifest_hash: str,
        index_snapshot_id: str,
        source_hashes: dict[str, str],
        idempotency_key: str,
        audit: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Bind a selected RAG/input snapshot to one immutable ArtifactVersion."""

        task_id = _validated_id(task_id, field="task_id")
        binding_id = _validated_id(binding_id, field="binding_id")
        version_id = _validated_id(version_id, field="version_id")
        index_snapshot_id = _validated_id(index_snapshot_id, field="index_snapshot_id")
        if not _SHA256.fullmatch(str(input_manifest_hash or "")):
            raise ValueError("input_manifest_hash must be a lowercase SHA256")
        if not source_hashes:
            raise ValueError("source_hashes must not be empty")
        if audit is not None and not isinstance(audit, dict):
            raise ValueError("audit must be a mapping")
        normalized_sources: dict[str, str] = {}
        for source_id, digest in source_hashes.items():
            source_id = _validated_id(source_id, field="source_id")
            if not _SHA256.fullmatch(str(digest or "")):
                raise ValueError(f"source hash for {source_id!r} must be a lowercase SHA256")
            normalized_sources[source_id] = digest

        def validate(projection: dict[str, Any]) -> None:
            if version_id not in projection["artifacts"]:
                raise EntityNotFound(f"artifact version {version_id!r} does not exist")
            if binding_id in projection["evidence_bindings"]:
                raise EntityAlreadyExists(f"evidence binding {binding_id!r} already exists")

        self._append_event(
            task_id=task_id,
            event_type="EVIDENCE_BOUND",
            entity_type="evidence_binding",
            entity_id=binding_id,
            idempotency_key=idempotency_key,
            payload={
                "version_id": version_id,
                "input_manifest_hash": input_manifest_hash,
                "index_snapshot_id": index_snapshot_id,
                "source_hashes": normalized_sources,
                "audit": audit or {},
            },
            validate_projection=validate,
        )
        return self.rebuild_task(task_id)

    def select_artifact_version(
        self,
        task_id: str,
        *,
        version_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Select exactly one evidenced ArtifactVersion as the Task result."""

        task_id = _validated_id(task_id, field="task_id")
        version_id = _validated_id(version_id, field="version_id")

        def validate(projection: dict[str, Any]) -> None:
            if version_id not in projection["artifacts"]:
                raise EntityNotFound(f"artifact version {version_id!r} does not exist")
            if not any(
                binding["version_id"] == version_id
                for binding in projection["evidence_bindings"].values()
            ):
                raise EntityNotFound(
                    f"artifact version {version_id!r} has no evidence binding"
                )
            artifact = projection["artifacts"][version_id]
            path = self._task_dir(task_id) / artifact["path"]
            if path.is_symlink() or not path.is_file():
                raise LedgerIntegrityError(
                    f"artifact version {version_id!r} file is missing or unsafe"
                )
            if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
                raise LedgerIntegrityError(
                    f"artifact version {version_id!r} SHA256 mismatch"
                )

        self._append_event(
            task_id=task_id,
            event_type="ARTIFACT_VERSION_SELECTED",
            entity_type="artifact_version",
            entity_id=version_id,
            idempotency_key=idempotency_key,
            payload={"version_id": version_id},
            validate_projection=validate,
        )
        return self.rebuild_task(task_id)

    def verify_evidence(self, task_id: str) -> dict[str, Any]:
        """Verify ledger integrity, artifact bytes, and evidence references."""

        task_id = _validated_id(task_id, field="task_id")
        projection = self.rebuild_task(task_id)
        failures: list[str] = []
        for version_id, artifact in projection["artifacts"].items():
            path = self._task_dir(task_id) / artifact["path"]
            if path.is_symlink():
                failures.append(f"{version_id}: artifact path is a symlink")
                continue
            elif not path.is_file():
                failures.append(f"{version_id}: artifact file missing")
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != artifact["sha256"]:
                failures.append(f"{version_id}: artifact SHA256 mismatch")
        for binding_id, binding in projection["evidence_bindings"].items():
            if binding["version_id"] not in projection["artifacts"]:
                failures.append(f"{binding_id}: artifact version missing")
        return {
            "task_id": task_id,
            "ok": not failures,
            "failures": failures,
            "last_event_hash": projection["last_event_hash"],
        }

    def load_task(self, task_id: str) -> dict[str, Any]:
        """Return a projection rebuilt from authority, never trusting stale snapshots."""

        return self.rebuild_task(task_id)

    def _task_dir(self, task_id: str) -> Path:
        return self.tasks_root / _validated_id(task_id, field="task_id")

    @contextmanager
    def _admission_lock(self) -> Iterator[None]:
        runtime_root = self.tasks_root.parent
        runtime_root.mkdir(parents=True, exist_ok=True)
        with (runtime_root / ".admission.lock").open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _assert_unique_business_goal(
        self, *, task_id: str, goal_fingerprint: str
    ) -> None:
        if not self.tasks_root.exists():
            return
        for task_dir in sorted(path for path in self.tasks_root.iterdir() if path.is_dir()):
            if task_dir.name == task_id:
                continue
            with self._ledger_lock(task_dir.name):
                events = self._load_events(task_dir.name)
                projection = self._project(events, task_id=task_dir.name)
            if projection["task"]["goal_fingerprint"] == goal_fingerprint:
                raise DuplicateBusinessGoal(
                    f"business goal already belongs to task {task_dir.name!r}; "
                    "add a Job, WorkItem, or Attempt there, or use an explicit "
                    "independent-boundary override"
                )

    def _write_task_projections(
        self, projection_dir: Path, projection: dict[str, Any]
    ) -> None:
        """Write disposable views; callers can always recreate them from events.jsonl."""

        atomic_write_yaml(projection_dir / "task.yml", projection)
        atomic_write_yaml(projection_dir / "jobs.yml", projection["jobs"])
        atomic_write_yaml(projection_dir / "work_items.yml", projection["work_items"])
        atomic_write_yaml(projection_dir / "attempts.yml", projection["attempts"])
        atomic_write_yaml(projection_dir / "artifact_index.yml", projection["artifacts"])
        atomic_write_yaml(projection_dir / "evidence.yml", projection["evidence_bindings"])
        atomic_write_yaml(projection_dir / "trace_records.yml", projection["trace_records"])
        counts: dict[str, int] = {}
        for work_item in projection["work_items"].values():
            status = work_item["status"]
            counts[status] = counts.get(status, 0) + 1
        atomic_write_yaml(
            projection_dir / "progress.yml",
            {
                "task_id": projection["task"]["task_id"],
                "task_status": projection["task"]["status"],
                "work_item_counts": counts,
                "attempt_count": len(projection["attempts"]),
                "last_event_sequence": projection["last_event_sequence"],
            },
        )
        atomic_write_yaml(
            projection_dir / "handoff.yml",
            {
                "task_id": projection["task"]["task_id"],
                "user_goal": projection["task"]["user_goal"],
                "status": projection["task"]["status"],
                "selected_artifact_version": projection["selected_artifact_version"],
                "input_tier": (
                    projection["task"].get("input_classification") or {}
                ).get("tier"),
                "last_event_hash": projection["last_event_hash"],
            },
        )

    @staticmethod
    def _materialize_immutable(
        destination: Path, content: bytes, expected_sha256: str
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.is_symlink():
                raise LedgerIntegrityError("immutable destination is a symlink")
            if hashlib.sha256(destination.read_bytes()).hexdigest() != expected_sha256:
                raise EntityAlreadyExists(
                    f"immutable destination already differs: {destination}"
                )
            return
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        temp = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp, destination)
            except FileExistsError:
                if (
                    destination.is_symlink()
                    or hashlib.sha256(destination.read_bytes()).hexdigest()
                    != expected_sha256
                ):
                    raise EntityAlreadyExists(
                        f"immutable destination raced: {destination}"
                    )
        finally:
            if temp.exists():
                temp.unlink()

    @contextmanager
    def _ledger_lock(self, task_id: str) -> Iterator[None]:
        lock_root = self.tasks_root.parent / ".locks"
        lock_root.mkdir(parents=True, exist_ok=True)
        lock_path = lock_root / f"{_validated_id(task_id, field='task_id')}.lock"
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _append_event(
        self,
        *,
        task_id: str,
        event_type: str,
        entity_type: str,
        entity_id: str,
        idempotency_key: str,
        payload: dict[str, Any],
        expected_task_statuses: set[str] | None = None,
        validate_projection: Callable[[dict[str, Any]], None] | None = None,
        idempotency_ignored_payload_keys: set[str] | None = None,
    ) -> dict[str, Any]:
        idempotency_key = _validated_id(idempotency_key, field="idempotency_key")
        with self._ledger_lock(task_id):
            events = self._load_events(task_id)
            if not events and event_type != "TASK_CREATED":
                raise EntityNotFound(f"task {task_id!r} does not exist")
            command_identity = {
                "event_type": event_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "payload": payload,
            }
            for existing in events:
                if existing.get("idempotency_key") != idempotency_key:
                    continue
                existing_identity = {
                    key: existing.get(key) for key in command_identity
                }
                ignored_keys = set(idempotency_ignored_payload_keys or set())
                if expected_task_statuses is not None:
                    ignored_keys.add("from_status")
                if ignored_keys:
                    existing_payload = dict(existing_identity.get("payload") or {})
                    requested_payload = dict(command_identity.get("payload") or {})
                    for key in ignored_keys:
                        existing_payload.pop(key, None)
                        requested_payload.pop(key, None)
                    existing_identity["payload"] = existing_payload
                    command_identity["payload"] = requested_payload
                if existing_identity != command_identity:
                    raise IdempotencyConflict(
                        f"idempotency key {idempotency_key!r} already belongs to another command"
                    )
                return existing

            if event_type == "TASK_CREATED" and events:
                raise EntityAlreadyExists(f"task {task_id!r} already exists")

            if expected_task_statuses is not None:
                current_projection = self._project(events, task_id=task_id)
                current_status = current_projection["task"]["status"]
                if current_status not in expected_task_statuses:
                    raise InvalidTransition(
                        f"task cannot transition from {current_status!r} "
                        f"to {payload.get('status')!r}"
                    )
                payload = {**payload, "from_status": current_status}
                command_identity["payload"] = payload
            if validate_projection is not None:
                validate_projection(self._project(events, task_id=task_id))

            event: dict[str, Any] = {
                "schema_version": EVENT_SCHEMA,
                "event_id": f"evt-{uuid.uuid4().hex}",
                "sequence": len(events) + 1,
                "task_id": task_id,
                "project": self.project,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "event_type": event_type,
                "recorded_at": _utc_now(),
                "idempotency_key": idempotency_key,
                "previous_event_hash": events[-1]["event_hash"] if events else None,
                "payload": payload,
            }
            event["event_hash"] = _event_hash(event)
            ledger_path = self._task_dir(task_id) / "events.jsonl"
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with ledger_path.open("a", encoding="utf-8") as handle:
                handle.write(_canonical_json(event) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return event

    def _load_events(self, task_id: str) -> list[dict[str, Any]]:
        ledger_path = self._task_dir(task_id) / "events.jsonl"
        if not ledger_path.exists():
            return []
        events: list[dict[str, Any]] = []
        previous_hash: str | None = None
        for sequence, line in enumerate(ledger_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise LedgerIntegrityError(
                    f"invalid JSON at ledger line {sequence}: {exc.msg}"
                ) from exc
            if not isinstance(event, dict):
                raise LedgerIntegrityError(f"ledger line {sequence} is not an object")
            supplied_hash = event.get("event_hash")
            unhashed = {key: value for key, value in event.items() if key != "event_hash"}
            checks = {
                "schema_version": event.get("schema_version") == EVENT_SCHEMA,
                "sequence": event.get("sequence") == sequence,
                "task_id": event.get("task_id") == task_id,
                "project": event.get("project") == self.project,
                "previous_event_hash": event.get("previous_event_hash") == previous_hash,
                "event_hash": supplied_hash == _event_hash(unhashed),
            }
            failed = [name for name, passed in checks.items() if not passed]
            if failed:
                raise LedgerIntegrityError(
                    f"ledger integrity failure at line {sequence}: {', '.join(failed)}"
                )
            events.append(event)
            previous_hash = str(supplied_hash)
        return events

    def _project(self, events: list[dict[str, Any]], *, task_id: str) -> dict[str, Any]:
        task: dict[str, Any] | None = None
        jobs: dict[str, dict[str, Any]] = {}
        work_items: dict[str, dict[str, Any]] = {}
        attempts: dict[str, dict[str, Any]] = {}
        artifacts: dict[str, dict[str, Any]] = {}
        evidence_bindings: dict[str, dict[str, Any]] = {}
        trace_records: dict[str, dict[str, Any]] = {}
        selected_artifact_version: str | None = None
        for event in events:
            if event["event_type"] == "TASK_CREATED":
                if task is not None:
                    raise LedgerIntegrityError("task ledger contains multiple TASK_CREATED events")
                task = {
                    "task_id": task_id,
                    "project": self.project,
                    "title": event["payload"]["title"],
                    "user_goal": event["payload"]["user_goal"],
                    "goal_fingerprint": event["payload"].get("goal_fingerprint")
                    or _goal_fingerprint(event["payload"]["user_goal"]),
                    "status": "created",
                    "created_at": event["recorded_at"],
                    "updated_at": event["recorded_at"],
                }
                if event["payload"].get("input_classification") is not None:
                    task["input_classification"] = event["payload"][
                        "input_classification"
                    ]
                if event["payload"].get("legacy_source") is not None:
                    task["legacy_source"] = event["payload"]["legacy_source"]
                if event["payload"].get("duplicate_goal_override") is not None:
                    task["duplicate_goal_override"] = event["payload"][
                        "duplicate_goal_override"
                    ]
                default_job = event["payload"].get("default_job") or {}
                job_id = _validated_id(default_job.get("job_id"), field="job_id")
                jobs[job_id] = {
                    "job_id": job_id,
                    "kind": str(default_job.get("kind") or "inline"),
                    "status": "queued",
                    "created_at": event["recorded_at"],
                    "updated_at": event["recorded_at"],
                }
                continue
            if event["event_type"] == "TASK_STATUS_CHANGED":
                if task is None:
                    raise LedgerIntegrityError("task transition precedes TASK_CREATED")
                from_status = str(event["payload"].get("from_status") or "")
                to_status = str(event["payload"].get("status") or "")
                if (
                    task["status"] != from_status
                    or to_status not in TASK_TRANSITIONS.get(from_status, set())
                ):
                    raise LedgerIntegrityError(
                        f"invalid task transition in ledger: {from_status!r} -> {to_status!r}"
                    )
                task["status"] = to_status
                task["updated_at"] = event["recorded_at"]
                continue
            if event["event_type"] == "WORK_ITEM_CREATED":
                if task is None:
                    raise LedgerIntegrityError("work item precedes TASK_CREATED")
                work_item_id = _validated_id(event["entity_id"], field="work_item_id")
                job_id = _validated_id(event["payload"].get("job_id"), field="job_id")
                if job_id not in jobs:
                    raise LedgerIntegrityError(f"work item references missing job: {job_id}")
                if work_item_id in work_items:
                    raise LedgerIntegrityError(f"duplicate work item: {work_item_id}")
                dependencies = list(event["payload"].get("depends_on") or [])
                if any(item not in work_items for item in dependencies):
                    raise LedgerIntegrityError("work item references missing dependency")
                work_items[work_item_id] = {
                    "work_item_id": work_item_id,
                    "job_id": job_id,
                    "kind": event["payload"]["kind"],
                    "title": event["payload"]["title"],
                    "depends_on": dependencies,
                    "status": "pending" if dependencies else "ready",
                    "active_attempt_id": None,
                    "created_at": event["recorded_at"],
                    "updated_at": event["recorded_at"],
                }
                continue
            if event["event_type"] == "JOB_CREATED":
                if task is None:
                    raise LedgerIntegrityError("job precedes TASK_CREATED")
                job_id = _validated_id(event["entity_id"], field="job_id")
                if job_id in jobs:
                    raise LedgerIntegrityError(f"duplicate job: {job_id}")
                jobs[job_id] = {
                    "job_id": job_id,
                    "kind": event["payload"]["kind"],
                    "strategy": event["payload"]["strategy"],
                    "status": "queued",
                    "created_at": event["recorded_at"],
                    "updated_at": event["recorded_at"],
                }
                continue
            if event["event_type"] == "WORK_ITEM_STATUS_CHANGED":
                work_item_id = _validated_id(event["entity_id"], field="work_item_id")
                work_item = work_items.get(work_item_id)
                if work_item is None:
                    raise LedgerIntegrityError(
                        f"work item transition references missing item: {work_item_id}"
                    )
                from_status = str(event["payload"].get("from_status") or "")
                to_status = str(event["payload"].get("status") or "")
                if (
                    work_item["status"] != from_status
                    or to_status not in WORK_ITEM_TRANSITIONS.get(from_status, set())
                ):
                    raise LedgerIntegrityError(
                        f"invalid work item transition in ledger: {from_status!r} -> {to_status!r}"
                    )
                work_item["status"] = to_status
                work_item["updated_at"] = event["recorded_at"]
                for dependent in work_items.values():
                    if dependent["status"] != "pending":
                        continue
                    if all(
                        work_items[dependency]["status"] == "accepted"
                        for dependency in dependent["depends_on"]
                    ):
                        dependent["status"] = "ready"
                        dependent["updated_at"] = event["recorded_at"]
                continue
            if event["event_type"] == "ATTEMPT_SCHEDULED":
                if task is None:
                    raise LedgerIntegrityError("attempt precedes TASK_CREATED")
                attempt_id = _validated_id(event["entity_id"], field="attempt_id")
                work_item_id = _validated_id(
                    event["payload"].get("work_item_id"), field="work_item_id"
                )
                if attempt_id in attempts:
                    raise LedgerIntegrityError(f"duplicate attempt: {attempt_id}")
                work_item = work_items.get(work_item_id)
                if work_item is None:
                    raise LedgerIntegrityError(
                        f"attempt references missing work item: {work_item_id}"
                    )
                if work_item.get("active_attempt_id"):
                    raise LedgerIntegrityError(
                        f"work item {work_item_id} has overlapping active attempts"
                    )
                attempts[attempt_id] = {
                    "attempt_id": attempt_id,
                    "work_item_id": work_item_id,
                    "ordinal": int(event["payload"]["ordinal"]),
                    "worker": event["payload"]["worker"],
                    "provider": event["payload"]["provider"],
                    "execution_contract": event["payload"]["execution_contract"],
                    "execution_contract_hash": event["payload"]["execution_contract_hash"],
                    "status": "scheduled",
                    "outcome": {},
                    "created_at": event["recorded_at"],
                    "updated_at": event["recorded_at"],
                }
                work_item["active_attempt_id"] = attempt_id
                work_item["updated_at"] = event["recorded_at"]
                continue
            if event["event_type"] == "ATTEMPT_STATUS_CHANGED":
                attempt_id = _validated_id(event["entity_id"], field="attempt_id")
                attempt = attempts.get(attempt_id)
                if attempt is None:
                    raise LedgerIntegrityError(
                        f"attempt transition references missing attempt: {attempt_id}"
                    )
                from_status = str(event["payload"].get("from_status") or "")
                to_status = str(event["payload"].get("status") or "")
                if (
                    attempt["status"] != from_status
                    or to_status not in ATTEMPT_TRANSITIONS.get(from_status, set())
                ):
                    raise LedgerIntegrityError(
                        f"invalid attempt transition in ledger: {from_status!r} -> {to_status!r}"
                    )
                attempt["status"] = to_status
                attempt["outcome"] = event["payload"].get("outcome") or {}
                attempt["updated_at"] = event["recorded_at"]
                work_item = work_items[attempt["work_item_id"]]
                if to_status not in ACTIVE_ATTEMPT_STATUSES:
                    work_item["active_attempt_id"] = None
                work_item["updated_at"] = event["recorded_at"]
                continue
            if event["event_type"] == "ARTIFACT_VERSION_RECORDED":
                version_id = _validated_id(event["entity_id"], field="version_id")
                attempt_id = _validated_id(
                    event["payload"].get("attempt_id"), field="attempt_id"
                )
                if version_id in artifacts:
                    raise LedgerIntegrityError(f"duplicate artifact version: {version_id}")
                if attempt_id not in attempts or attempts[attempt_id]["status"] != "succeeded":
                    raise LedgerIntegrityError("artifact producer attempt is not succeeded")
                artifacts[version_id] = {
                    "artifact_id": event["payload"]["artifact_id"],
                    "version_id": version_id,
                    "producer_attempt_id": attempt_id,
                    "source_path": event["payload"].get("source_path"),
                    "path": event["payload"]["path"],
                    "media_type": event["payload"]["media_type"],
                    "size_bytes": event["payload"]["size_bytes"],
                    "sha256": event["payload"]["sha256"],
                    "created_at": event["recorded_at"],
                }
                continue
            if event["event_type"] == "TRACE_RECORDED":
                record_id = _validated_id(event["entity_id"], field="record_id")
                if record_id in trace_records:
                    raise LedgerIntegrityError(f"duplicate trace record: {record_id}")
                trace_records[record_id] = {
                    "record_id": record_id,
                    "record_type": event["payload"]["record_type"],
                    "producer": event["payload"]["producer"],
                    "source_path": event["payload"].get("source_path"),
                    "path": event["payload"]["path"],
                    "size_bytes": event["payload"]["size_bytes"],
                    "sha256": event["payload"]["sha256"],
                    "metadata": event["payload"].get("metadata") or {},
                    "created_at": event["recorded_at"],
                }
                continue
            if event["event_type"] == "EVIDENCE_BOUND":
                binding_id = _validated_id(event["entity_id"], field="binding_id")
                version_id = _validated_id(
                    event["payload"].get("version_id"), field="version_id"
                )
                if binding_id in evidence_bindings:
                    raise LedgerIntegrityError(f"duplicate evidence binding: {binding_id}")
                if version_id not in artifacts:
                    raise LedgerIntegrityError("evidence references missing artifact version")
                evidence_bindings[binding_id] = {
                    "binding_id": binding_id,
                    "version_id": version_id,
                    "input_manifest_hash": event["payload"]["input_manifest_hash"],
                    "index_snapshot_id": event["payload"]["index_snapshot_id"],
                    "source_hashes": event["payload"]["source_hashes"],
                    "audit": event["payload"].get("audit") or {},
                    "execution_receipt": {
                        "attempt_id": artifacts[version_id]["producer_attempt_id"],
                        "worker": attempts[
                            artifacts[version_id]["producer_attempt_id"]
                        ]["worker"],
                        "provider": attempts[
                            artifacts[version_id]["producer_attempt_id"]
                        ]["provider"],
                        "execution_contract_hash": attempts[
                            artifacts[version_id]["producer_attempt_id"]
                        ]["execution_contract_hash"],
                        "outcome": attempts[
                            artifacts[version_id]["producer_attempt_id"]
                        ]["outcome"],
                    },
                    "created_at": event["recorded_at"],
                }
                continue
            if event["event_type"] == "ARTIFACT_VERSION_SELECTED":
                version_id = _validated_id(
                    event["payload"].get("version_id"), field="version_id"
                )
                if version_id not in artifacts:
                    raise LedgerIntegrityError("selected artifact version does not exist")
                if not any(
                    binding["version_id"] == version_id
                    for binding in evidence_bindings.values()
                ):
                    raise LedgerIntegrityError("selected artifact version has no evidence")
                selected_artifact_version = version_id
                continue
            raise LedgerIntegrityError(f"unsupported event type: {event['event_type']}")
        if task is None:
            raise LedgerIntegrityError(f"task {task_id!r} has no TASK_CREATED event")
        return {
            "schema_version": PROJECTION_SCHEMA,
            "task": task,
            "jobs": jobs,
            "work_items": work_items,
            "attempts": attempts,
            "artifacts": artifacts,
            "evidence_bindings": evidence_bindings,
            "trace_records": trace_records,
            "selected_artifact_version": selected_artifact_version,
            "last_event_sequence": events[-1]["sequence"],
            "last_event_hash": events[-1]["event_hash"],
        }
