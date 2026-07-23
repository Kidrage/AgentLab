"""Public schemas for project canonical truth.

The schemas deliberately describe semantic resources and facts instead of files.
Files, indexes, and generated views are projections of these records.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class ResourceChange:
    key: str
    content: Any
    media_type: str = "application/yaml"

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "content": deepcopy(self.content),
            "media_type": self.media_type,
        }


@dataclass(frozen=True)
class FactChange:
    key: str
    value: Any
    owner: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": deepcopy(self.value),
            "owner": self.owner,
        }


@dataclass(frozen=True)
class ChangeSet:
    project_id: str
    expected_snapshot_id: str
    actor_id: str
    idempotency_key: str
    reason: str = ""
    resources: tuple[ResourceChange, ...] = ()
    facts: tuple[FactChange, ...] = ()
    remove_resource_keys: tuple[str, ...] = ()
    remove_fact_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "resources", tuple(self.resources))
        object.__setattr__(self, "facts", tuple(self.facts))
        object.__setattr__(
            self, "remove_resource_keys", tuple(self.remove_resource_keys)
        )
        object.__setattr__(self, "remove_fact_keys", tuple(self.remove_fact_keys))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "project-truth-change-set/v1",
            "project_id": self.project_id,
            "expected_snapshot_id": self.expected_snapshot_id,
            "actor_id": self.actor_id,
            "idempotency_key": self.idempotency_key,
            "reason": self.reason,
            "resources": [item.to_dict() for item in self.resources],
            "facts": [item.to_dict() for item in self.facts],
            "remove_resource_keys": list(self.remove_resource_keys),
            "remove_fact_keys": list(self.remove_fact_keys),
        }


@dataclass(frozen=True)
class ResourceRevision:
    revision_id: str
    key: str
    content_sha256: str
    content: Any
    media_type: str
    previous_revision_id: str | None
    actor_id: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "key": self.key,
            "content_sha256": self.content_sha256,
            "content": deepcopy(self.content),
            "media_type": self.media_type,
            "previous_revision_id": self.previous_revision_id,
            "actor_id": self.actor_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ResourceRevision":
        return cls(
            revision_id=str(data["revision_id"]),
            key=str(data["key"]),
            content_sha256=str(data["content_sha256"]),
            content=deepcopy(data.get("content")),
            media_type=str(data["media_type"]),
            previous_revision_id=(
                str(data["previous_revision_id"])
                if data.get("previous_revision_id")
                else None
            ),
            actor_id=str(data["actor_id"]),
            created_at=str(data["created_at"]),
        )


@dataclass(frozen=True)
class FactRevision:
    revision_id: str
    key: str
    value_sha256: str
    value: Any
    owner: str
    previous_revision_id: str | None
    actor_id: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "key": self.key,
            "value_sha256": self.value_sha256,
            "value": deepcopy(self.value),
            "owner": self.owner,
            "previous_revision_id": self.previous_revision_id,
            "actor_id": self.actor_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FactRevision":
        return cls(
            revision_id=str(data["revision_id"]),
            key=str(data["key"]),
            value_sha256=str(data["value_sha256"]),
            value=deepcopy(data.get("value")),
            owner=str(data["owner"]),
            previous_revision_id=(
                str(data["previous_revision_id"])
                if data.get("previous_revision_id")
                else None
            ),
            actor_id=str(data["actor_id"]),
            created_at=str(data["created_at"]),
        )


@dataclass(frozen=True)
class CanonicalSnapshot:
    snapshot_id: str
    project_id: str
    generation: int
    parent_snapshot_id: str | None
    resources: Mapping[str, ResourceRevision] = field(default_factory=dict)
    facts: Mapping[str, FactRevision] = field(default_factory=dict)
    change_set_sha256: str | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "canonical-snapshot/v1",
            "snapshot_id": self.snapshot_id,
            "project_id": self.project_id,
            "generation": self.generation,
            "parent_snapshot_id": self.parent_snapshot_id,
            "resources": {
                key: value.to_dict() for key, value in sorted(self.resources.items())
            },
            "facts": {
                key: value.to_dict() for key, value in sorted(self.facts.items())
            },
            "change_set_sha256": self.change_set_sha256,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CanonicalSnapshot":
        return cls(
            snapshot_id=str(data["snapshot_id"]),
            project_id=str(data["project_id"]),
            generation=int(data["generation"]),
            parent_snapshot_id=(
                str(data["parent_snapshot_id"])
                if data.get("parent_snapshot_id")
                else None
            ),
            resources={
                str(key): ResourceRevision.from_dict(value)
                for key, value in (data.get("resources") or {}).items()
            },
            facts={
                str(key): FactRevision.from_dict(value)
                for key, value in (data.get("facts") or {}).items()
            },
            change_set_sha256=(
                str(data["change_set_sha256"])
                if data.get("change_set_sha256")
                else None
            ),
            created_at=str(data["created_at"]),
        )


@dataclass(frozen=True)
class ProjectTruthPointer:
    project_id: str
    current_snapshot_id: str
    generation: int
    updated_at: str
    last_receipt_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "project-truth-pointer/v1",
            "project_id": self.project_id,
            "current_snapshot_id": self.current_snapshot_id,
            "generation": self.generation,
            "updated_at": self.updated_at,
            "last_receipt_id": self.last_receipt_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProjectTruthPointer":
        return cls(
            project_id=str(data["project_id"]),
            current_snapshot_id=str(data["current_snapshot_id"]),
            generation=int(data["generation"]),
            updated_at=str(data["updated_at"]),
            last_receipt_id=(
                str(data["last_receipt_id"]) if data.get("last_receipt_id") else None
            ),
        )


@dataclass(frozen=True)
class CanonicalCommitReceipt:
    receipt_id: str
    project_id: str
    snapshot_id: str
    previous_snapshot_id: str
    generation: int
    actor_id: str
    idempotency_key: str
    change_set_sha256: str
    committed_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "canonical-commit-receipt/v1",
            "receipt_id": self.receipt_id,
            "project_id": self.project_id,
            "snapshot_id": self.snapshot_id,
            "previous_snapshot_id": self.previous_snapshot_id,
            "generation": self.generation,
            "actor_id": self.actor_id,
            "idempotency_key": self.idempotency_key,
            "change_set_sha256": self.change_set_sha256,
            "committed_at": self.committed_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CanonicalCommitReceipt":
        return cls(
            receipt_id=str(data["receipt_id"]),
            project_id=str(data["project_id"]),
            snapshot_id=str(data["snapshot_id"]),
            previous_snapshot_id=str(data["previous_snapshot_id"]),
            generation=int(data["generation"]),
            actor_id=str(data["actor_id"]),
            idempotency_key=str(data["idempotency_key"]),
            change_set_sha256=str(data["change_set_sha256"]),
            committed_at=str(data["committed_at"]),
        )
