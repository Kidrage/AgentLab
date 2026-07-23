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
ARTIFACT_DISPOSITION_TRANSITIONS: dict[str, set[str]] = {
    "eligible": {"rejected_pre_v3", "superseded", "archived"},
    "rejected_pre_v3": {"archived"},
    "superseded": {"archived"},
    "archived": set(),
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

    def classify_task_input(
        self,
        task_id: str,
        *,
        input_profile: dict[str, Any],
        producer_attempt_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Accept a complete profile returned by a successful Brain intake Attempt."""

        task_id = _validated_id(task_id, field="task_id")
        producer_attempt_id = _validated_id(
            producer_attempt_id, field="producer_attempt_id"
        )
        if not isinstance(input_profile, dict):
            raise ValueError("input_profile must be a mapping")
        classification = TaskInputClassifier(self.agentlab_root).classify(input_profile)
        if not classification.get("admission_ready"):
            raise InvalidTransition("Brain input classification is still incomplete")

        def validate(projection: dict[str, Any]) -> None:
            current = projection["task"].get("input_classification") or {}
            if current.get("admission_ready"):
                raise InvalidTransition("Task input classification is already admitted")
            attempt = projection["attempts"].get(producer_attempt_id)
            if attempt is None or attempt.get("status") != "succeeded":
                raise InvalidTransition(
                    "input classification requires a successful producer Attempt"
                )
            contract = attempt.get("execution_contract") or {}
            if contract.get("role") != "Supervisor" or contract.get(
                "purpose"
            ) != "input_classification":
                raise InvalidTransition(
                    "input classification must come from a Supervisor intake Attempt"
                )
            output = self._load_validated_attempt_output(
                task_id=task_id, attempt=attempt
            )
            if output.get("input_profile") != input_profile:
                raise InvalidTransition(
                    "input classification does not match the Supervisor Attempt output"
                )

        self._append_event(
            task_id=task_id,
            event_type="TASK_INPUT_CLASSIFIED",
            entity_type="task",
            entity_id=task_id,
            idempotency_key=idempotency_key,
            payload={
                "input_profile": dict(input_profile),
                "input_classification": classification,
                "producer_attempt_id": producer_attempt_id,
            },
            validate_projection=validate,
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
                    classification = projection["task"].get(
                        "input_classification"
                    ) or {}
                    if (
                        projection["task"].get("legacy_source") is None
                        and classification.get("enforcement") == "strict"
                    ):
                        for attempt_id, attempt in projection["attempts"].items():
                            if attempt.get("status") != "succeeded":
                                continue
                            try:
                                self._validate_attempt_execution_receipt(
                                    task_id=task_dir.name,
                                    attempt=attempt,
                                    outcome=attempt.get("outcome") or {},
                                )
                            except (TaskRuntimeError, ValueError, OSError) as exc:
                                artifact_failures.append(
                                    f"{attempt_id}: invalid Attempt receipt: {exc}"
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
                gate_evidence = classification.get("gate_evidence") or {}
                uncovered_gates = sorted(
                    gate
                    for gate in classification.get("validation_gates") or []
                    if gate_evidence.get(gate) not in available_records
                )
                if uncovered_gates:
                    raise InvalidTransition(
                        "task completion has validation gates without evidence: "
                        + ", ".join(uncovered_gates)
                    )
                successful_delegated_attempts = sum(
                    attempt["status"] == "succeeded"
                    and str(
                        (attempt.get("execution_contract") or {}).get("role") or ""
                    )
                    != "Supervisor"
                    for attempt in projection["attempts"].values()
                )
                minimum_attempts = int(
                    classification.get("minimum_successful_delegated_attempts") or 0
                )
                if successful_delegated_attempts < minimum_attempts:
                    raise InvalidTransition(
                        "task completion requires successful delegated Attempts: "
                        f"{successful_delegated_attempts}/{minimum_attempts}"
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
        assigned_agent_id: str | None = None,
        agent_manifest_revision: int | None = None,
        canonical_snapshot_id: str | None = None,
        effective_contract_hash: str | None = None,
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
        agent_binding = self._validate_project_agent_binding(
            assigned_agent_id=assigned_agent_id,
            agent_manifest_revision=agent_manifest_revision,
            canonical_snapshot_id=canonical_snapshot_id,
            contract_hash=effective_contract_hash,
        )

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
                **agent_binding,
            },
            validate_projection=validate,
        )
        return self.rebuild_task(task_id)

    def _validate_project_agent_binding(
        self,
        *,
        assigned_agent_id: str | None,
        agent_manifest_revision: int | None,
        canonical_snapshot_id: str | None,
        contract_hash: str | None,
    ) -> dict[str, Any]:
        project_root = self.agentlab_root / "projects" / self.project
        manifest_path = project_root / "project.yml"
        project_manifest: dict[str, Any] = {}
        if manifest_path.is_file():
            loaded = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                project_manifest = loaded
        features = project_manifest.get("features") or {}
        workspace = project_manifest.get("workspace") or {}
        enabled = features.get("enable_project_agents") is True
        supplied = (
            assigned_agent_id,
            agent_manifest_revision,
            canonical_snapshot_id,
            contract_hash,
        )
        if not enabled:
            if any(value is not None for value in supplied):
                raise ValueError(
                    "project Agent binding supplied while project agents are disabled"
                )
            return {}
        if features.get("project_truth_mode") != "enforced":
            raise ValueError("project agents require enforced project truth")
        if workspace.get("isolation") != "required":
            raise ValueError("project agents require isolated project workspace")
        if any(value is None for value in supplied):
            raise ValueError(
                "project Agent WorkItem requires agent, manifest, snapshot, "
                "and contract bindings"
            )

        from agent_runtime.project_agents import (
            AgentContract,
            ProjectAgentRegistry,
            effective_contract_hash as hash_contract,
        )
        from agent_runtime.project_truth import ProjectTruthStore

        agent_id = _validated_id(str(assigned_agent_id), field="assigned_agent_id")
        snapshot_id = str(canonical_snapshot_id)
        if not _SHA256.fullmatch(snapshot_id):
            raise ValueError("canonical_snapshot_id must be a SHA-256 hex digest")
        if not isinstance(agent_manifest_revision, int) or isinstance(
            agent_manifest_revision, bool
        ) or agent_manifest_revision < 1:
            raise ValueError("agent_manifest_revision must be positive")
        if not _SHA256.fullmatch(str(contract_hash)):
            raise ValueError("effective_contract_hash must be a SHA-256 hex digest")

        truth = ProjectTruthStore(project_root)
        current = truth.current()
        if current.snapshot_id != snapshot_id:
            raise ValueError("canonical snapshot binding is stale")
        registered = ProjectAgentRegistry(truth).get(agent_id)
        AgentContract(registered).assert_active()
        if registered.manifest_revision != agent_manifest_revision:
            raise ValueError("agent manifest revision binding is stale")
        if hash_contract(registered) != contract_hash:
            raise ValueError("effective Agent contract hash mismatch")
        return {
            "assigned_agent_id": agent_id,
            "agent_manifest_revision": agent_manifest_revision,
            "canonical_snapshot_id": snapshot_id,
            "effective_contract_hash": contract_hash,
        }

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
                role = str(execution_contract.get("role") or "")
                brain_intake = (
                    role == "Supervisor"
                    and execution_contract.get("purpose") == "input_classification"
                )
                if not classification.get("admission_ready") and not brain_intake:
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
                if not role:
                    raise InvalidTransition("execution contract must declare its AgentLab role")
                delegated = role != "Supervisor"
                delegation_mode = str(classification.get("delegation_mode") or "")
                if delegation_mode == "brain_only" and delegated:
                    raise InvalidTransition("this tier permits Brain-direct execution only")
                if delegation_mode == "single_worker_identity" and delegated:
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
                            "this tier permits one delegated worker identity"
                        )
                pre_worker_records = set(
                    classification.get("pre_worker_records") or []
                )
                if pre_worker_records and delegated:
                    record_types = {
                        record["record_type"]
                        for record in projection["trace_records"].values()
                    }
                    if not pre_worker_records.issubset(record_types):
                        raise InvalidTransition(
                            "Worker execution requires Brain scope and execution plan records"
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
        producer_role: str,
        path: Path,
        idempotency_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Pin one immutable execution, quality, change, or memory receipt."""

        task_id = _validated_id(task_id, field="task_id")
        record_id = _validated_id(record_id, field="record_id")
        record_type = _validated_id(record_type, field="record_type")
        producer = _validated_id(producer, field="producer")
        producer_role = _validated_id(producer_role, field="producer_role")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be a mapping")
        resolved_path = Path(path).resolve(strict=True)
        records_root = (self._task_dir(task_id) / "records").resolve(strict=False)
        staging_root = records_root / "staging"
        immutable_root = records_root / "immutable"
        if not resolved_path.is_relative_to(staging_root):
            raise ValueError("trace record source must be inside records/staging")
        content = resolved_path.read_bytes()
        try:
            record_data = yaml.safe_load(content.decode("utf-8")) or {}
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ValueError("trace record must be valid UTF-8 YAML") from exc
        if not isinstance(record_data, dict):
            raise ValueError("trace record payload must be a mapping")
        record_contract = TaskInputClassifier(self.agentlab_root).trace_record_contract(
            record_type
        )
        destination = immutable_root / record_id / f"payload{resolved_path.suffix or '.bin'}"
        payload = {
            "record_type": record_type,
            "producer": producer,
            "producer_role": producer_role,
            "source_path": resolved_path.relative_to(self._task_dir(task_id)).as_posix(),
            "path": destination.relative_to(self._task_dir(task_id)).as_posix(),
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "metadata": metadata or {},
            "record_contract": record_contract,
            "record_data": record_data,
        }

        def validate(projection: dict[str, Any]) -> None:
            if record_id in projection["trace_records"]:
                raise EntityAlreadyExists(f"trace record {record_id!r} already exists")
            self._validate_trace_record(
                record_type=record_type,
                producer=producer,
                producer_role=producer_role,
                data=record_data,
                contract=record_contract,
                projection=projection,
            )
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

        return self._transition_attempt(
            task_id,
            attempt_id=attempt_id,
            status=status,
            idempotency_key=idempotency_key,
            outcome=outcome,
            executed_success=False,
        )

    def _transition_executed_attempt(
        self,
        task_id: str,
        *,
        attempt_id: str,
        status: str,
        idempotency_key: str,
        outcome: dict[str, Any],
    ) -> dict[str, Any]:
        """Complete the private RoleAttemptExecutor success path."""

        if str(status or "").strip().lower() != "succeeded":
            raise ValueError("executed Attempt transition only accepts succeeded")
        return self._transition_attempt(
            task_id,
            attempt_id=attempt_id,
            status=status,
            idempotency_key=idempotency_key,
            outcome=outcome,
            executed_success=True,
        )

    def _transition_attempt(
        self,
        task_id: str,
        *,
        attempt_id: str,
        status: str,
        idempotency_key: str,
        outcome: dict[str, Any] | None,
        executed_success: bool,
    ) -> dict[str, Any]:

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
            classification = projection["task"].get("input_classification") or {}
            if (
                status == "succeeded"
                and projection["task"].get("legacy_source") is None
                and classification.get("enforcement") == "strict"
            ):
                if not executed_success:
                    raise InvalidTransition(
                        "strict Attempt success is owned by RoleAttemptExecutor"
                    )
                self._validate_attempt_execution_receipt(
                    task_id=task_id,
                    attempt=attempt,
                    outcome=payload["outcome"],
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

    def verify_attempt_execution_receipt(
        self, task_id: str, attempt_id: str
    ) -> dict[str, Any]:
        """Revalidate one succeeded Attempt's pinned execution evidence."""

        task_id = _validated_id(task_id, field="task_id")
        attempt_id = _validated_id(attempt_id, field="attempt_id")
        projection = self.load_task(task_id)
        attempt = projection["attempts"].get(attempt_id)
        if attempt is None or attempt.get("status") != "succeeded":
            raise InvalidTransition("Attempt is not successful")
        self._validate_attempt_execution_receipt(
            task_id=task_id,
            attempt=attempt,
            outcome=attempt.get("outcome") or {},
        )
        return {
            "task_id": task_id,
            "attempt_id": attempt_id,
            "ok": True,
            "receipt_sha256": (attempt.get("outcome") or {}).get("receipt_sha256"),
            "output_sha256": (attempt.get("outcome") or {}).get("output_sha256"),
        }

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
            if projection["artifacts"][version_id].get("selection_eligible") is not True:
                raise InvalidTransition(
                    f"artifact version {version_id!r} is not selection eligible"
                )
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

    def change_artifact_disposition(
        self,
        task_id: str,
        *,
        version_id: str,
        disposition: str,
        reason_code: str,
        feedback_digest: str,
        feedback_path: Path | None = None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Append an auditable disposition without rewriting artifact history."""

        task_id = _validated_id(task_id, field="task_id")
        version_id = _validated_id(version_id, field="version_id")
        disposition = _validated_id(disposition, field="disposition")
        reason_code = _validated_id(reason_code, field="reason_code")
        feedback_digest = str(feedback_digest or "").strip()
        if not _SHA256.fullmatch(feedback_digest):
            raise ValueError("feedback_digest must be lowercase 64-hex")
        feedback_ref: str | None = None
        if feedback_path is not None:
            resolved_feedback = Path(feedback_path).resolve(strict=True)
            task_root = self._task_dir(task_id).resolve(strict=False)
            if not resolved_feedback.is_relative_to(task_root):
                raise ValueError("feedback path must be inside the task directory")
            if hashlib.sha256(resolved_feedback.read_bytes()).hexdigest() != feedback_digest:
                raise ValueError("feedback path SHA256 does not match feedback_digest")
            feedback_ref = resolved_feedback.relative_to(task_root).as_posix()

        def validate(projection: dict[str, Any]) -> None:
            artifact = projection["artifacts"].get(version_id)
            if artifact is None:
                raise EntityNotFound(f"artifact version {version_id!r} does not exist")
            current_disposition = str(artifact.get("disposition") or "eligible")
            if current_disposition != from_disposition:
                raise InvalidTransition("artifact disposition changed concurrently")
            if disposition not in ARTIFACT_DISPOSITION_TRANSITIONS.get(
                current_disposition, set()
            ):
                raise InvalidTransition(
                    "invalid artifact disposition transition: "
                    f"{current_disposition!r} -> {disposition!r}"
                )
            if task_status_transition is not None:
                if (
                    projection["task"]["status"]
                    != task_status_transition["from_status"]
                    or projection["selected_artifact_version"] != version_id
                ):
                    raise InvalidTransition(
                        "completed selected artifact changed before audit disposition"
                    )

        projection = self.load_task(task_id)
        artifact = projection["artifacts"].get(version_id)
        if artifact is None:
            raise EntityNotFound(f"artifact version {version_id!r} does not exist")
        from_disposition = str(artifact.get("disposition") or "eligible")
        task_status_transition = (
            {"from_status": "completed", "status": "ready"}
            if projection["task"]["status"] == "completed"
            and projection["selected_artifact_version"] == version_id
            else None
        )
        if from_disposition == disposition:
            history = artifact.get("disposition_history") or []
            last_change = history[-1] if history else {}
            if (
                last_change.get("reason_code") == reason_code
                and last_change.get("feedback_digest") == feedback_digest
                and last_change.get("feedback_ref") == feedback_ref
            ):
                return projection
            raise InvalidTransition(
                f"artifact version {version_id!r} already has disposition "
                f"{disposition!r} under a different audit decision"
            )
        self._append_event(
            task_id=task_id,
            event_type="ARTIFACT_VERSION_DISPOSITION_CHANGED",
            entity_type="artifact_version",
            entity_id=version_id,
            idempotency_key=idempotency_key,
            payload={
                "version_id": version_id,
                "from_disposition": from_disposition,
                "disposition": disposition,
                "reason_code": reason_code,
                "feedback_digest": feedback_digest,
                "feedback_ref": feedback_ref,
                "task_status_transition": task_status_transition,
            },
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

    def _validate_trace_record(
        self,
        *,
        record_type: str,
        producer: str,
        producer_role: str,
        data: dict[str, Any],
        contract: dict[str, Any],
        projection: dict[str, Any],
    ) -> None:
        if data.get("schema_version") != contract.get("schema_version"):
            raise InvalidTransition(
                f"{record_type} schema_version does not match its policy contract"
            )
        allowed_roles = set(contract.get("producer_roles") or [])
        if producer_role not in allowed_roles:
            raise InvalidTransition(
                f"{record_type} cannot be produced by role {producer_role!r}"
            )
        type_checks = {
            "string": lambda value: isinstance(value, str),
            "integer": lambda value: isinstance(value, int)
            and not isinstance(value, bool),
            "boolean": lambda value: isinstance(value, bool),
            "list": lambda value: isinstance(value, list),
            "mapping": lambda value: isinstance(value, dict),
            "sha256": lambda value: isinstance(value, str)
            and bool(_SHA256.fullmatch(value)),
        }
        for field, rules in (contract.get("fields") or {}).items():
            rules = rules or {}
            value = data.get(field)
            expected_type = str(rules.get("type") or "")
            checker = type_checks.get(expected_type)
            if checker is None or not checker(value):
                raise InvalidTransition(
                    f"{record_type}.{field} must satisfy type {expected_type!r}"
                )
            if "equals" in rules and value != rules["equals"]:
                raise InvalidTransition(
                    f"{record_type}.{field} does not match its required value"
                )
            if "minimum" in rules and value < rules["minimum"]:
                raise InvalidTransition(
                    f"{record_type}.{field} is below its minimum"
                )
            if "minimum_items" in rules and len(value) < rules["minimum_items"]:
                raise InvalidTransition(
                    f"{record_type}.{field} has too few items"
                )
        for relation in contract.get("relations") or []:
            left = data.get(relation.get("left"))
            right = data.get(relation.get("right"))
            if relation.get("operator") == "gte_field" and not left >= right:
                raise InvalidTransition(
                    f"{record_type} field relation is not satisfied"
                )
        attempt_id_field = str(contract.get("attempt_id_field") or "")
        if attempt_id_field:
            for attempt_id in data.get(attempt_id_field) or []:
                attempt = projection["attempts"].get(str(attempt_id))
                if attempt is None or attempt.get("status") != "succeeded":
                    raise InvalidTransition(
                        f"{record_type} references a non-successful Attempt"
                    )
                role = str(
                    (attempt.get("execution_contract") or {}).get("role") or ""
                )
                if role == "Supervisor":
                    raise InvalidTransition(
                        f"{record_type} may only link delegated Attempts"
                    )
                receipt_hashes_field = str(
                    contract.get("attempt_receipt_hashes_field") or ""
                )
                if receipt_hashes_field and (
                    (data.get(receipt_hashes_field) or {}).get(str(attempt_id))
                    != (attempt.get("outcome") or {}).get("receipt_sha256")
                ):
                    raise InvalidTransition(
                        f"{record_type} Attempt receipt hash does not match the ledger"
                    )
        producer_attempt_field = str(
            contract.get("producer_attempt_id_field") or ""
        )
        if producer_attempt_field:
            producer_attempt_id = str(data.get(producer_attempt_field) or "")
            attempt = projection["attempts"].get(producer_attempt_id)
            if attempt is None or attempt.get("status") != "succeeded":
                raise InvalidTransition(
                    f"{record_type} producer Attempt is not successful"
                )
            attempt_contract = attempt.get("execution_contract") or {}
            if (
                attempt_contract.get("role") != producer_role
                or attempt.get("worker") != producer
            ):
                raise InvalidTransition(
                    f"{record_type} producer Attempt identity does not match"
                )
            source_hash_field = str(
                contract.get("source_output_sha256_field") or ""
            )
            source_hash = str(data.get(source_hash_field) or "")
            if source_hash != (attempt.get("outcome") or {}).get("output_sha256"):
                raise InvalidTransition(
                    f"{record_type} source output hash does not match producer Attempt"
                )
            output = self._load_validated_attempt_output(
                task_id=projection["task"]["task_id"], attempt=attempt
            )
            source_output_key = str(contract.get("source_output_key") or "")
            source_record = output.get(source_output_key)
            provenance_fields = {producer_attempt_field, source_hash_field}
            recorded_decision = {
                key: value for key, value in data.items() if key not in provenance_fields
            }
            if source_record != recorded_decision:
                raise InvalidTransition(
                    f"{record_type} does not match the producer Attempt output"
                )
        for link in contract.get("attempt_receipt_hash_links") or []:
            attempt = projection["attempts"].get(
                str(data.get(link.get("attempt_id_field")) or "")
            )
            allowed_link_roles = set(link.get("allowed_roles") or [])
            attempt_role = str(
                ((attempt or {}).get("execution_contract") or {}).get("role") or ""
            )
            if (
                attempt is None
                or attempt.get("status") != "succeeded"
                or (allowed_link_roles and attempt_role not in allowed_link_roles)
                or data.get(link.get("hash_field"))
                != (attempt.get("outcome") or {}).get("receipt_sha256")
            ):
                raise InvalidTransition(
                    f"{record_type} linked Attempt receipt hash does not match"
                )
        for link in contract.get("record_data_hash_links") or []:
            matching = [
                record
                for record in projection["trace_records"].values()
                if record.get("record_type") == link.get("record_type")
            ]
            if not matching:
                raise InvalidTransition(
                    f"{record_type} linked trace record does not exist"
                )
            linked_data = matching[-1].get("record_data") or {}
            expected_hash = hashlib.sha256(
                _canonical_json(linked_data.get(link.get("data_field"))).encode("utf-8")
            ).hexdigest()
            if data.get(link.get("hash_field")) != expected_hash:
                raise InvalidTransition(
                    f"{record_type} linked trace data hash does not match"
                )
        path_list_field = str(contract.get("path_list_field") or "")
        path_hashes_field = str(contract.get("path_hashes_field") or "")
        if path_list_field and path_hashes_field:
            paths = data.get(path_list_field) or []
            hashes = data.get(path_hashes_field) or {}
            if set(paths) != set(hashes):
                raise InvalidTransition(
                    f"{record_type} path list and content hashes do not match"
                )
            project_root = (
                self.agentlab_root / "projects" / self.project
            ).resolve(strict=False)
            for relative_path in paths:
                if not isinstance(relative_path, str) or not relative_path.strip():
                    raise InvalidTransition(
                        f"{record_type} referenced path or hash is invalid"
                    )
                candidate = self.agentlab_root / relative_path
                try:
                    resolved = candidate.resolve(strict=True)
                    actual_hash = hashlib.sha256(resolved.read_bytes()).hexdigest()
                except (OSError, RuntimeError) as exc:
                    raise InvalidTransition(
                        f"{record_type} referenced path or hash is invalid"
                    ) from exc
                if (
                    candidate.is_symlink()
                    or not resolved.is_file()
                    or not resolved.is_relative_to(project_root)
                    or actual_hash != hashes.get(relative_path)
                ):
                    raise InvalidTransition(
                        f"{record_type} referenced path or hash is invalid"
                    )

    def _validate_attempt_execution_receipt(
        self,
        *,
        task_id: str,
        attempt: dict[str, Any],
        outcome: dict[str, Any],
    ) -> None:
        attempt_id = str(attempt["attempt_id"])
        receipt_value = str(outcome.get("receipt_path") or "")
        receipt_hash = str(outcome.get("receipt_sha256") or "")
        if not receipt_value or not _SHA256.fullmatch(receipt_hash):
            raise InvalidTransition(
                "successful Attempt requires a hashed role-executor receipt"
            )
        task_root = self._task_dir(task_id).resolve(strict=False)
        attempt_root = (task_root / "attempt_logs" / attempt_id).resolve(strict=False)
        try:
            receipt_candidate = task_root / receipt_value
            receipt_path = receipt_candidate.resolve(strict=True)
            receipt_bytes = receipt_path.read_bytes()
            receipt = yaml.safe_load(receipt_bytes.decode("utf-8")) or {}
        except (OSError, RuntimeError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise InvalidTransition(
                "Attempt execution receipt path or content is invalid"
            ) from exc
        if (
            receipt_candidate.is_symlink()
            or not receipt_path.is_relative_to(attempt_root)
            or hashlib.sha256(receipt_bytes).hexdigest() != receipt_hash
        ):
            raise InvalidTransition("Attempt execution receipt path or hash is invalid")
        contract = attempt.get("execution_contract") or {}
        expected = {
            "schema_version": "task-runtime-role-attempt-receipt/v1",
            "project": self.project,
            "task_id": task_id,
            "work_item_id": attempt.get("work_item_id"),
            "attempt_id": attempt_id,
            "role": contract.get("role"),
            "worker": attempt.get("worker"),
            "provider": attempt.get("provider"),
            "status": "pass",
        }
        if outcome.get("execution_origin") != "role_attempt_executor" or not isinstance(
            receipt, dict
        ) or any(
            receipt.get(field) != value for field, value in expected.items()
        ):
            raise InvalidTransition("Attempt execution receipt identity is invalid")
        output_candidate = task_root / str(receipt.get("output_path") or "")
        try:
            output_path = output_candidate.resolve(strict=True)
            output_bytes = output_path.read_bytes()
        except (OSError, RuntimeError) as exc:
            raise InvalidTransition("Attempt output path or hash is invalid") from exc
        output_hash = str(receipt.get("output_sha256") or "")
        if (
            output_candidate.is_symlink()
            or not output_path.is_relative_to(attempt_root)
            or not _SHA256.fullmatch(output_hash)
            or hashlib.sha256(output_bytes).hexdigest() != output_hash
            or outcome.get("output_sha256") != output_hash
        ):
            raise InvalidTransition("Attempt output path or hash is invalid")
        model_execution = receipt.get("model_execution") or {}
        if not isinstance(model_execution, dict):
            raise InvalidTransition("Attempt model execution binding is missing")
        expected_model_execution = {
            "cli_agent": attempt.get("worker"),
            "model_key": contract.get("model_key"),
            "model_id": contract.get("model_id"),
            "runtime_provider": contract.get("runtime_provider"),
            "executor_provider": "agentlab-cli-executor",
        }
        if any(
            model_execution.get(field) != value
            for field, value in expected_model_execution.items()
        ):
            raise InvalidTransition("Attempt model execution route does not match")
        model_receipt_candidate = task_root / str(model_execution.get("path") or "")
        try:
            model_receipt_path = model_receipt_candidate.resolve(strict=True)
            model_receipt_bytes = model_receipt_path.read_bytes()
            model_receipt = yaml.safe_load(model_receipt_bytes.decode("utf-8")) or {}
        except (OSError, RuntimeError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise InvalidTransition("Attempt model execution receipt is invalid") from exc
        if (
            model_receipt_candidate.is_symlink()
            or not model_receipt_path.is_relative_to(attempt_root)
            or hashlib.sha256(model_receipt_bytes).hexdigest()
            != model_execution.get("sha256")
            or not isinstance(model_receipt, dict)
        ):
            raise InvalidTransition("Attempt model execution receipt hash is invalid")
        selected_provider = model_receipt.get(
            "selected_provider", model_receipt.get("provider")
        )
        selected_model = model_receipt.get(
            "selected_model_id", model_receipt.get("model")
        )
        profile_binding = model_receipt.get(
            "profile_binding_verified", model_receipt.get("profile_state_verified")
        )
        if (
            model_receipt.get("status") != "pass"
            or model_receipt.get("worker") != attempt.get("worker")
            or model_receipt.get("invocation_contract")
            != contract.get("invocation_contract")
            or model_receipt.get("role", contract.get("role"))
            != contract.get("role")
            or selected_provider != contract.get("runtime_provider")
            or selected_model != contract.get("model_id")
            or profile_binding is not True
            or model_receipt.get("command_binding_verified") is not True
            or model_receipt.get("fallback_detected") is True
            or model_receipt.get("provider_process_started") is not True
            or model_receipt.get("exit_code") != 0
            or model_receipt.get("issues") not in (None, [])
            or model_receipt.get("provider_model_binding_verified") is False
        ):
            raise InvalidTransition("Attempt model execution receipt did not pass")

    def _load_validated_attempt_output(
        self, *, task_id: str, attempt: dict[str, Any]
    ) -> dict[str, Any]:
        outcome = attempt.get("outcome") or {}
        self._validate_attempt_execution_receipt(
            task_id=task_id, attempt=attempt, outcome=outcome
        )
        task_root = self._task_dir(task_id).resolve(strict=False)
        try:
            receipt_path = (
                task_root / str(outcome.get("receipt_path") or "")
            ).resolve(strict=True)
            receipt = yaml.safe_load(receipt_path.read_text(encoding="utf-8")) or {}
            output_path = (
                task_root / str(receipt.get("output_path") or "")
            ).resolve(strict=True)
            output = self._parse_attempt_output_mapping(
                output_path.read_text(encoding="utf-8")
            )
        except (OSError, RuntimeError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise InvalidTransition("Attempt output is not readable YAML") from exc
        return output

    @staticmethod
    def _parse_attempt_output_mapping(content: str) -> dict[str, Any]:
        candidates = [content]
        marker = "\n## Output\n\n"
        if marker in content:
            candidates.append(content.split(marker, 1)[1].split("\n\n## stderr", 1)[0])
        for candidate in candidates:
            stripped = candidate.strip()
            if stripped.startswith("```") and stripped.endswith("```"):
                first_newline = stripped.find("\n")
                if first_newline >= 0:
                    stripped = stripped[first_newline + 1 : -3].strip()
            try:
                parsed = yaml.safe_load(stripped) or {}
            except yaml.YAMLError:
                continue
            if isinstance(parsed, dict):
                return parsed
        raise InvalidTransition("Attempt output must contain a YAML mapping")

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
            if event["event_type"] == "TASK_INPUT_CLASSIFIED":
                if task is None:
                    raise LedgerIntegrityError(
                        "input classification precedes TASK_CREATED"
                    )
                attempt_id = _validated_id(
                    event["payload"].get("producer_attempt_id"),
                    field="producer_attempt_id",
                )
                attempt = attempts.get(attempt_id)
                if attempt is None or attempt.get("status") != "succeeded":
                    raise LedgerIntegrityError(
                        "input classification producer is not succeeded"
                    )
                contract = attempt.get("execution_contract") or {}
                if contract.get("role") != "Supervisor" or contract.get(
                    "purpose"
                ) != "input_classification":
                    raise LedgerIntegrityError(
                        "input classification producer is not a Supervisor intake"
                    )
                task["input_classification"] = event["payload"][
                    "input_classification"
                ]
                task["input_classification_attempt_id"] = attempt_id
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
                    "status": (
                        "ready"
                        if not dependencies
                        or all(
                            work_items[dependency]["status"] == "accepted"
                            for dependency in dependencies
                        )
                        else "pending"
                    ),
                    "active_attempt_id": None,
                    "created_at": event["recorded_at"],
                    "updated_at": event["recorded_at"],
                }
                for binding_field in (
                    "assigned_agent_id",
                    "agent_manifest_revision",
                    "canonical_snapshot_id",
                    "effective_contract_hash",
                ):
                    if event["payload"].get(binding_field) is not None:
                        work_items[work_item_id][binding_field] = event["payload"][
                            binding_field
                        ]
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
                    "disposition": "eligible",
                    "selection_eligible": True,
                    "disposition_history": [],
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
                    "producer_role": event["payload"]["producer_role"],
                    "source_path": event["payload"].get("source_path"),
                    "path": event["payload"]["path"],
                    "size_bytes": event["payload"]["size_bytes"],
                    "sha256": event["payload"]["sha256"],
                    "metadata": event["payload"].get("metadata") or {},
                    "record_contract": event["payload"].get("record_contract") or {},
                    "record_data": event["payload"].get("record_data") or {},
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
                if artifacts[version_id].get("selection_eligible") is not True:
                    raise LedgerIntegrityError(
                        "selected artifact version is not selection eligible"
                    )
                if not any(
                    binding["version_id"] == version_id
                    for binding in evidence_bindings.values()
                ):
                    raise LedgerIntegrityError("selected artifact version has no evidence")
                selected_artifact_version = version_id
                continue
            if event["event_type"] == "ARTIFACT_VERSION_DISPOSITION_CHANGED":
                version_id = _validated_id(
                    event["payload"].get("version_id"), field="version_id"
                )
                artifact = artifacts.get(version_id)
                if artifact is None:
                    raise LedgerIntegrityError(
                        "artifact disposition references missing artifact version"
                    )
                from_disposition = str(
                    event["payload"].get("from_disposition") or ""
                )
                disposition = str(event["payload"].get("disposition") or "")
                if (
                    artifact.get("disposition") != from_disposition
                    or disposition
                    not in ARTIFACT_DISPOSITION_TRANSITIONS.get(
                        from_disposition, set()
                    )
                ):
                    raise LedgerIntegrityError(
                        "invalid artifact disposition transition in ledger"
                    )
                artifact["disposition"] = disposition
                artifact["selection_eligible"] = disposition == "eligible"
                artifact["disposition_history"].append(
                    {
                        "from_disposition": from_disposition,
                        "disposition": disposition,
                        "reason_code": event["payload"].get("reason_code"),
                        "feedback_digest": event["payload"].get("feedback_digest"),
                        "feedback_ref": event["payload"].get("feedback_ref"),
                        "event_id": event["event_id"],
                        "recorded_at": event["recorded_at"],
                    }
                )
                if selected_artifact_version == version_id:
                    selected_artifact_version = None
                task_transition = event["payload"].get("task_status_transition")
                if task_transition is not None:
                    if task is None or not isinstance(task_transition, dict):
                        raise LedgerIntegrityError(
                            "artifact disposition has invalid task transition"
                        )
                    from_status = str(task_transition.get("from_status") or "")
                    to_status = str(task_transition.get("status") or "")
                    if (
                        task["status"] != from_status
                        or to_status not in TASK_TRANSITIONS.get(from_status, set())
                    ):
                        raise LedgerIntegrityError(
                            "artifact disposition has invalid task lifecycle transition"
                        )
                    task["status"] = to_status
                    task["updated_at"] = event["recorded_at"]
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
