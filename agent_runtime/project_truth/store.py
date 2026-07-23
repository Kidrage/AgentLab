"""Transactional, content-addressed canonical truth for one project."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

import yaml

from agent_runtime.atomic_io import atomic_write_json, atomic_write_yaml

from .models import (
    CanonicalCommitReceipt,
    CanonicalSnapshot,
    ChangeSet,
    FactRevision,
    ProjectTruthPointer,
    ResourceRevision,
)


class ProjectTruthError(RuntimeError):
    """Base class for canonical truth failures."""


class ProjectTruthConflict(ProjectTruthError):
    """A compare-and-swap or idempotency conflict."""


class ProjectTruthIntegrityError(ProjectTruthError):
    """Stored canonical truth is missing, malformed, or hash-invalid."""


class ProjectTruthValidationError(ProjectTruthError):
    """A proposed change set is ambiguous or invalid."""


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProjectTruthValidationError(
            "canonical truth values must be JSON-compatible"
        ) from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _with_hash_id(data: Mapping[str, Any], id_field: str) -> dict[str, Any]:
    document = dict(data)
    document.pop(id_field, None)
    document[id_field] = _sha256(document)
    return document


class ProjectTruthStore:
    """Own the single canonical pointer and its immutable snapshot history."""

    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()
        self.pointer_path = self.project_root / "project_truth.yml"
        self.truth_root = self.project_root / ".agentlab" / "truth"
        self.objects_root = self.truth_root / "objects" / "sha256"
        self.snapshots_root = self.truth_root / "snapshots"
        self.receipts_root = self.truth_root / "receipts"
        self.events_path = self.truth_root / "events.jsonl"
        self.lock_path = self.truth_root / ".commit.lock"

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.truth_root.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def initialize(self, project_id: str) -> ProjectTruthPointer:
        """Create the initial empty snapshot, or return the existing pointer."""
        self._validate_identifier(project_id, "project_id")
        self.project_root.mkdir(parents=True, exist_ok=True)
        with self._lock():
            if self.pointer_path.exists():
                pointer = self._load_pointer()
                if pointer.project_id != project_id:
                    raise ProjectTruthConflict(
                        "project truth already belongs to a different project"
                    )
                return pointer

            created_at = _now()
            snapshot_data = {
                "schema_version": "canonical-snapshot/v1",
                "project_id": project_id,
                "generation": 0,
                "parent_snapshot_id": None,
                "resources": {},
                "facts": {},
                "change_set_sha256": None,
                "created_at": created_at,
            }
            snapshot_data = _with_hash_id(snapshot_data, "snapshot_id")
            snapshot = CanonicalSnapshot.from_dict(snapshot_data)
            self._write_immutable_yaml(
                self.snapshots_root / f"{snapshot.snapshot_id}.yml",
                snapshot.to_dict(),
            )
            pointer = ProjectTruthPointer(
                project_id=project_id,
                current_snapshot_id=snapshot.snapshot_id,
                generation=0,
                updated_at=created_at,
            )
            atomic_write_yaml(self.pointer_path, pointer.to_dict(), sort_keys=False)
            return pointer

    def current(self) -> CanonicalSnapshot:
        """Read the one authoritative current snapshot."""
        return self._load_snapshot(self._load_pointer().current_snapshot_id)

    def commit(self, change_set: ChangeSet) -> CanonicalCommitReceipt:
        """Atomically compare-and-swap one validated change set into authority."""
        self._validate_change_set(change_set)
        change_set_sha256 = _sha256(change_set.to_dict())
        receipt_path = self._receipt_path(
            change_set.project_id, change_set.idempotency_key
        )

        with self._lock():
            if receipt_path.exists():
                receipt = self._load_receipt(
                    receipt_path,
                    expected_project_id=change_set.project_id,
                    expected_idempotency_key=change_set.idempotency_key,
                )
                if receipt.change_set_sha256 != change_set_sha256:
                    raise ProjectTruthConflict(
                        "idempotency key already belongs to a different change set"
                    )
                pointer = self._load_pointer()
                if self._snapshot_in_chain(
                    pointer.current_snapshot_id, receipt.snapshot_id
                ):
                    return receipt
                if pointer.current_snapshot_id != receipt.previous_snapshot_id:
                    raise ProjectTruthConflict(
                        "idempotent commit receipt is not on the canonical chain"
                    )
                recovered = self._load_snapshot(receipt.snapshot_id)
                if recovered.generation != receipt.generation:
                    raise ProjectTruthIntegrityError(
                        "idempotent commit receipt generation mismatch"
                    )
                self._append_event(
                    {
                        "schema_version": "project-truth-event/v1",
                        "event_type": "CANONICAL_CHANGE_PREPARED",
                        "project_id": change_set.project_id,
                        "snapshot_id": receipt.snapshot_id,
                        "receipt_id": receipt.receipt_id,
                        "committed_at": receipt.committed_at,
                    }
                )
                atomic_write_yaml(
                    self.pointer_path,
                    ProjectTruthPointer(
                        project_id=receipt.project_id,
                        current_snapshot_id=receipt.snapshot_id,
                        generation=receipt.generation,
                        updated_at=receipt.committed_at,
                        last_receipt_id=receipt.receipt_id,
                    ).to_dict(),
                    sort_keys=False,
                )
                return receipt

            pointer = self._load_pointer()
            if pointer.project_id != change_set.project_id:
                raise ProjectTruthConflict("change set project does not match truth")
            if pointer.current_snapshot_id != change_set.expected_snapshot_id:
                raise ProjectTruthConflict(
                    "stale canonical snapshot: refresh before committing"
                )
            current = self._load_snapshot(pointer.current_snapshot_id)
            committed_at = _now()
            resources = dict(current.resources)
            facts = dict(current.facts)

            for change in change_set.resources:
                content_sha256 = self._write_content_object(change.content)
                previous = resources.get(change.key)
                revision_data = {
                    "key": change.key,
                    "content_sha256": content_sha256,
                    "content": change.content,
                    "media_type": change.media_type,
                    "previous_revision_id": (
                        previous.revision_id if previous is not None else None
                    ),
                    "actor_id": change_set.actor_id,
                    "created_at": committed_at,
                }
                revision_data = _with_hash_id(revision_data, "revision_id")
                resources[change.key] = ResourceRevision.from_dict(revision_data)

            for change in change_set.facts:
                value_sha256 = self._write_content_object(change.value)
                previous = facts.get(change.key)
                revision_data = {
                    "key": change.key,
                    "value_sha256": value_sha256,
                    "value": change.value,
                    "owner": change.owner,
                    "previous_revision_id": (
                        previous.revision_id if previous is not None else None
                    ),
                    "actor_id": change_set.actor_id,
                    "created_at": committed_at,
                }
                revision_data = _with_hash_id(revision_data, "revision_id")
                facts[change.key] = FactRevision.from_dict(revision_data)

            generation = pointer.generation + 1
            snapshot_data = {
                "schema_version": "canonical-snapshot/v1",
                "project_id": change_set.project_id,
                "generation": generation,
                "parent_snapshot_id": current.snapshot_id,
                "resources": {
                    key: value.to_dict() for key, value in sorted(resources.items())
                },
                "facts": {
                    key: value.to_dict() for key, value in sorted(facts.items())
                },
                "change_set_sha256": change_set_sha256,
                "created_at": committed_at,
            }
            snapshot_data = _with_hash_id(snapshot_data, "snapshot_id")
            snapshot = CanonicalSnapshot.from_dict(snapshot_data)

            receipt_data = {
                "schema_version": "canonical-commit-receipt/v1",
                "project_id": change_set.project_id,
                "snapshot_id": snapshot.snapshot_id,
                "previous_snapshot_id": current.snapshot_id,
                "generation": generation,
                "actor_id": change_set.actor_id,
                "idempotency_key": change_set.idempotency_key,
                "change_set_sha256": change_set_sha256,
                "committed_at": committed_at,
            }
            receipt_data = _with_hash_id(receipt_data, "receipt_id")
            receipt = CanonicalCommitReceipt.from_dict(receipt_data)

            self._write_immutable_yaml(
                self.snapshots_root / f"{snapshot.snapshot_id}.yml",
                snapshot.to_dict(),
            )
            self._write_immutable_yaml(receipt_path, receipt.to_dict())
            self._append_event(
                {
                    "schema_version": "project-truth-event/v1",
                    "event_type": "CANONICAL_CHANGE_PREPARED",
                    "project_id": change_set.project_id,
                    "snapshot_id": snapshot.snapshot_id,
                    "receipt_id": receipt.receipt_id,
                    "committed_at": committed_at,
                }
            )
            next_pointer = ProjectTruthPointer(
                project_id=change_set.project_id,
                current_snapshot_id=snapshot.snapshot_id,
                generation=generation,
                updated_at=committed_at,
                last_receipt_id=receipt.receipt_id,
            )
            atomic_write_yaml(
                self.pointer_path, next_pointer.to_dict(), sort_keys=False
            )
            return receipt

    def fact_history(self, key: str) -> list[FactRevision]:
        """Return newest-first immutable revisions for one semantic fact key."""
        self._validate_identifier(key, "fact key")
        revisions: list[FactRevision] = []
        seen: set[str] = set()
        snapshot = self.current()
        while True:
            revision = snapshot.facts.get(key)
            if revision is not None and revision.revision_id not in seen:
                revisions.append(revision)
                seen.add(revision.revision_id)
            if snapshot.parent_snapshot_id is None:
                return revisions
            snapshot = self._load_snapshot(snapshot.parent_snapshot_id)

    def resource_history(self, key: str) -> list[ResourceRevision]:
        """Return newest-first immutable revisions for one semantic resource key."""
        self._validate_identifier(key, "resource key")
        revisions: list[ResourceRevision] = []
        seen: set[str] = set()
        snapshot = self.current()
        while True:
            revision = snapshot.resources.get(key)
            if revision is not None and revision.revision_id not in seen:
                revisions.append(revision)
                seen.add(revision.revision_id)
            if snapshot.parent_snapshot_id is None:
                return revisions
            snapshot = self._load_snapshot(snapshot.parent_snapshot_id)

    def audit(self) -> dict[str, Any]:
        """Verify the current chain and every referenced content hash."""
        pointer = self._load_pointer()
        snapshot = self._load_snapshot(pointer.current_snapshot_id)
        checked_snapshots = 0
        checked_objects: set[str] = set()
        expected_generation = pointer.generation
        while True:
            if snapshot.generation != expected_generation:
                raise ProjectTruthIntegrityError("snapshot generation chain is broken")
            for revision in snapshot.resources.values():
                self._verify_content_object(revision.content_sha256, revision.content)
                checked_objects.add(revision.content_sha256)
            for revision in snapshot.facts.values():
                self._verify_content_object(revision.value_sha256, revision.value)
                checked_objects.add(revision.value_sha256)
            checked_snapshots += 1
            if snapshot.parent_snapshot_id is None:
                break
            expected_generation -= 1
            snapshot = self._load_snapshot(snapshot.parent_snapshot_id)
        return {
            "status": "pass",
            "project_id": pointer.project_id,
            "current_snapshot_id": pointer.current_snapshot_id,
            "snapshots_checked": checked_snapshots,
            "objects_checked": len(checked_objects),
        }

    def _validate_change_set(self, change_set: ChangeSet) -> None:
        if not isinstance(change_set, ChangeSet):
            raise ProjectTruthValidationError("change set must use the ChangeSet schema")
        for value, label in (
            (change_set.project_id, "project_id"),
            (change_set.expected_snapshot_id, "expected_snapshot_id"),
            (change_set.actor_id, "actor_id"),
            (change_set.idempotency_key, "idempotency_key"),
        ):
            self._validate_identifier(value, label)
        if not change_set.resources and not change_set.facts:
            raise ProjectTruthValidationError("change set must contain at least one change")
        resource_keys = [item.key for item in change_set.resources]
        fact_keys = [item.key for item in change_set.facts]
        self._reject_duplicates(resource_keys, "resource")
        self._reject_duplicates(fact_keys, "fact")
        for item in change_set.resources:
            self._validate_identifier(item.key, "resource key")
            self._validate_identifier(item.media_type, "media_type")
            _canonical_json(item.content)
        for item in change_set.facts:
            self._validate_identifier(item.key, "fact key")
            self._validate_identifier(item.owner, "fact owner")
            _canonical_json(item.value)

    @staticmethod
    def _validate_identifier(value: str, label: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ProjectTruthValidationError(f"{label} must be a non-empty string")
        if any(character in value for character in ("\0", "\n", "\r")):
            raise ProjectTruthValidationError(f"{label} contains forbidden characters")

    @staticmethod
    def _reject_duplicates(keys: list[str], label: str) -> None:
        if len(keys) != len(set(keys)):
            raise ProjectTruthValidationError(f"duplicate {label} key in change set")

    def _load_pointer(self) -> ProjectTruthPointer:
        if not self.pointer_path.exists():
            raise ProjectTruthIntegrityError("project truth is not initialized")
        data = self._read_yaml(self.pointer_path)
        if data.get("schema_version") != "project-truth-pointer/v1":
            raise ProjectTruthIntegrityError("project truth pointer schema mismatch")
        return ProjectTruthPointer.from_dict(data)

    def _load_snapshot(self, snapshot_id: str) -> CanonicalSnapshot:
        if not _SHA256.fullmatch(snapshot_id):
            raise ProjectTruthIntegrityError("canonical snapshot id is invalid")
        path = self.snapshots_root / f"{snapshot_id}.yml"
        data = self._read_yaml(path)
        if data.get("schema_version") != "canonical-snapshot/v1":
            raise ProjectTruthIntegrityError("canonical snapshot schema mismatch")
        actual_id = str(data.get("snapshot_id") or "")
        if actual_id != snapshot_id or _with_hash_id(data, "snapshot_id")[
            "snapshot_id"
        ] != snapshot_id:
            raise ProjectTruthIntegrityError("canonical snapshot hash mismatch")
        return CanonicalSnapshot.from_dict(data)

    def _snapshot_in_chain(self, head_id: str, expected_id: str) -> bool:
        snapshot = self._load_snapshot(head_id)
        while True:
            if snapshot.snapshot_id == expected_id:
                return True
            if snapshot.parent_snapshot_id is None:
                return False
            snapshot = self._load_snapshot(snapshot.parent_snapshot_id)

    def _load_receipt(
        self,
        path: Path,
        *,
        expected_project_id: str,
        expected_idempotency_key: str,
    ) -> CanonicalCommitReceipt:
        data = self._read_yaml(path)
        if data.get("schema_version") != "canonical-commit-receipt/v1":
            raise ProjectTruthIntegrityError("canonical receipt schema mismatch")
        actual_id = str(data.get("receipt_id") or "")
        if not _SHA256.fullmatch(actual_id) or _with_hash_id(
            data, "receipt_id"
        )["receipt_id"] != actual_id:
            raise ProjectTruthIntegrityError("canonical receipt hash mismatch")
        receipt = CanonicalCommitReceipt.from_dict(data)
        if (
            receipt.project_id != expected_project_id
            or receipt.idempotency_key != expected_idempotency_key
        ):
            raise ProjectTruthIntegrityError("canonical receipt binding mismatch")
        return receipt

    def _write_content_object(self, content: Any) -> str:
        digest = _sha256(content)
        path = self.objects_root / digest[:2] / f"{digest}.json"
        self._write_immutable_json(
            path,
            {
                "schema_version": "project-truth-object/v1",
                "sha256": digest,
                "content": content,
            },
        )
        return digest

    def _verify_content_object(self, digest: str, expected: Any) -> None:
        path = self.objects_root / digest[:2] / f"{digest}.json"
        if not path.exists():
            raise ProjectTruthIntegrityError(f"missing content object {digest}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProjectTruthIntegrityError(
                f"invalid content object {digest}"
            ) from exc
        if (
            data.get("schema_version") != "project-truth-object/v1"
            or data.get("sha256") != digest
            or _sha256(data.get("content")) != digest
            or data.get("content") != expected
        ):
            raise ProjectTruthIntegrityError(f"content object hash mismatch {digest}")

    def _receipt_path(self, project_id: str, idempotency_key: str) -> Path:
        key = hashlib.sha256(
            f"{project_id}\0{idempotency_key}".encode("utf-8")
        ).hexdigest()
        return self.receipts_root / f"{key}.yml"

    def _write_immutable_yaml(self, path: Path, data: Mapping[str, Any]) -> None:
        if path.exists():
            if self._read_yaml(path) != dict(data):
                raise ProjectTruthIntegrityError(
                    f"immutable truth record collision at {path.name}"
                )
            return
        atomic_write_yaml(path, dict(data), sort_keys=False)

    def _write_immutable_json(self, path: Path, data: Mapping[str, Any]) -> None:
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ProjectTruthIntegrityError(
                    f"invalid immutable truth object at {path.name}"
                ) from exc
            if existing != dict(data):
                raise ProjectTruthIntegrityError(
                    f"immutable truth object collision at {path.name}"
                )
            return
        atomic_write_json(path, dict(data), sort_keys=True)

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ProjectTruthIntegrityError(f"cannot read truth record {path}") from exc
        if not isinstance(data, dict):
            raise ProjectTruthIntegrityError(f"truth record is not a mapping: {path}")
        return data

    def _append_event(self, event: Mapping[str, Any]) -> None:
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        line = _canonical_json(event) + b"\n"
        with self.events_path.open("ab") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
