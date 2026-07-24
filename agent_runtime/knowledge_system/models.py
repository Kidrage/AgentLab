"""Public contracts for AgentLab's governed knowledge system."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


NAMESPACE_RE = re.compile(
    r"^(system|domain|project)\.[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
    r"|^agent\.[A-Za-z0-9][A-Za-z0-9_.-]{0,63}"
    r"\.[A-Za-z0-9][A-Za-z0-9_-]{1,63}$"
)


class AuthorityLevel(str, Enum):
    CANONICAL = "canonical"
    ACCEPTED = "accepted"
    CANDIDATE = "candidate"
    AUDIT = "audit"
    EXTERNAL = "external"


class KnowledgeLifecycle(str, Enum):
    ACTIVE = "active"
    STALE = "stale"
    DEPRECATED = "deprecated"
    TOMBSTONED = "tombstoned"


class Modality(str, Enum):
    TEXT = "text"
    CODE = "code"
    STRUCTURED = "structured"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"


def stable_digest(*parts: Any, prefix: str = "") -> str:
    body = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return f"{prefix}{digest}"


def validate_namespace(namespace: str) -> str:
    if not NAMESPACE_RE.fullmatch(str(namespace or "")):
        raise ValueError(f"invalid knowledge namespace: {namespace}")
    return namespace


@dataclass(frozen=True)
class SourceRef:
    path: str
    content_hash: str
    kind: str = "local_file"

    def __post_init__(self) -> None:
        raw_path = self.path.replace("\\", "/")
        if Path(raw_path).is_absolute() or ".." in Path(raw_path).parts:
            raise ValueError(f"unsafe knowledge source path: {self.path}")
        path = raw_path[2:] if raw_path.startswith("./") else raw_path
        if not path:
            raise ValueError(f"unsafe knowledge source path: {self.path}")
        if not re.fullmatch(r"[0-9a-f]{64}", self.content_hash):
            raise ValueError("source content_hash must be a SHA-256 hex digest")
        object.__setattr__(self, "path", path)

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "content_hash": self.content_hash, "kind": self.kind}


@dataclass(frozen=True)
class KnowledgeRecord:
    record_id: str
    namespace: str
    project_id: str | None
    source: SourceRef
    content: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    authority: AuthorityLevel = AuthorityLevel.CANDIDATE
    lifecycle: KnowledgeLifecycle = KnowledgeLifecycle.ACTIVE
    modality: Modality = Modality.TEXT
    object_kind: str = "document"
    version: int = 1
    relations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_namespace(self.namespace)
        if self.version < 1:
            raise ValueError("knowledge record version must be positive")

    @classmethod
    def create(
        cls,
        *,
        namespace: str,
        project_id: str | None,
        source: SourceRef,
        content: str,
        authority: AuthorityLevel,
        modality: Modality,
        object_kind: str,
        metadata: Mapping[str, Any] | None = None,
        lifecycle: KnowledgeLifecycle = KnowledgeLifecycle.ACTIVE,
        version: int = 1,
        relations: tuple[str, ...] = (),
    ) -> "KnowledgeRecord":
        record_id = stable_digest(namespace, source.path, source.content_hash, prefix="kr_")
        return cls(
            record_id=record_id,
            namespace=namespace,
            project_id=project_id,
            source=source,
            content=content,
            metadata=dict(metadata or {}),
            authority=authority,
            lifecycle=lifecycle,
            modality=modality,
            object_kind=object_kind,
            version=version,
            relations=relations,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "namespace": self.namespace,
            "project_id": self.project_id,
            "source": self.source.as_dict(),
            "content": self.content,
            "metadata": dict(self.metadata),
            "authority": self.authority.value,
            "lifecycle": self.lifecycle.value,
            "modality": self.modality.value,
            "object_kind": self.object_kind,
            "version": self.version,
            "relations": list(self.relations),
        }


@dataclass(frozen=True)
class KnowledgeTaskRequest:
    agentlab_root: Path
    project: str
    task_id: str
    request_text: str
    domain: str | None = None
    modalities: tuple[Modality, ...] = ()
    required_channels: tuple[str, ...] = ()
    file_hints: tuple[str, ...] = ()


@dataclass(frozen=True)
class KnowledgeRequirement:
    requirement_id: str
    project: str
    task_id: str
    request_text: str
    domain: str
    modalities: tuple[str, ...]
    namespaces: tuple[str, ...]
    required_channels: tuple[str, ...]
    max_results: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "project": self.project,
            "task_id": self.task_id,
            "request_text": self.request_text,
            "domain": self.domain,
            "modalities": list(self.modalities),
            "namespaces": list(self.namespaces),
            "required_channels": list(self.required_channels),
            "max_results": self.max_results,
        }


@dataclass(frozen=True)
class TaskRetrievalView:
    view_id: str
    task_id: str
    query: str
    namespaces: tuple[str, ...]
    channels: tuple[str, ...]
    filters: Mapping[str, Any]
    max_results: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "view_id": self.view_id,
            "task_id": self.task_id,
            "query": self.query,
            "namespaces": list(self.namespaces),
            "channels": list(self.channels),
            "filters": dict(self.filters),
            "max_results": self.max_results,
        }


@dataclass(frozen=True)
class RetrievalTrace:
    trace_id: str
    index_snapshot: str
    channels: tuple[str, ...]
    steps: tuple[Mapping[str, Any], ...]
    degraded: bool = False
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "index_snapshot": self.index_snapshot,
            "channels": list(self.channels),
            "steps": [dict(step) for step in self.steps],
            "degraded": self.degraded,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    record_id: str
    namespace: str
    source: SourceRef
    locator: str
    excerpt: str
    authority: str
    lifecycle: str
    modality: str
    object_kind: str
    channel: str
    rank: int
    score: float
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "record_id": self.record_id,
            "namespace": self.namespace,
            "source": self.source.as_dict(),
            "locator": self.locator,
            "excerpt": self.excerpt,
            "authority": self.authority,
            "lifecycle": self.lifecycle,
            "modality": self.modality,
            "object_kind": self.object_kind,
            "channel": self.channel,
            "rank": self.rank,
            "score": round(self.score, 8),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EvidenceBundle:
    bundle_id: str
    status: str
    items: tuple[EvidenceItem, ...]
    missing_channels: tuple[str, ...]
    trace: RetrievalTrace

    def as_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "status": self.status,
            "items": [item.as_dict() for item in self.items],
            "missing_channels": list(self.missing_channels),
            "trace": self.trace.as_dict(),
        }


@dataclass(frozen=True)
class PreparedKnowledgeContext:
    context_ref: str
    status: str
    mode: str
    requirement: KnowledgeRequirement
    retrieval_view: TaskRetrievalView
    evidence_bundle: EvidenceBundle
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "context_ref": self.context_ref,
            "status": self.status,
            "mode": self.mode,
            "requirement": self.requirement.as_dict(),
            "retrieval_view": self.retrieval_view.as_dict(),
            "evidence_bundle": self.evidence_bundle.as_dict(),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class KnowledgeUpdateProposal:
    proposal_id: str
    status: str
    context_ref: str
    claims: tuple[Mapping[str, Any], ...]
    proposed_records: tuple[Mapping[str, Any], ...]
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "status": self.status,
            "context_ref": self.context_ref,
            "claims": [dict(item) for item in self.claims],
            "proposed_records": [dict(item) for item in self.proposed_records],
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class KnowledgeSyncReceipt:
    receipt_id: str
    status: str
    project: str
    namespaces: tuple[str, ...]
    index_snapshot: str | None
    indexed_paths: tuple[str, ...] = ()
    stale_namespaces: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "status": self.status,
            "project": self.project,
            "namespaces": list(self.namespaces),
            "index_snapshot": self.index_snapshot,
            "indexed_paths": list(self.indexed_paths),
            "stale_namespaces": list(self.stale_namespaces),
            "warnings": list(self.warnings),
        }


def coerce_task_request(value: KnowledgeTaskRequest | Mapping[str, Any]) -> KnowledgeTaskRequest:
    if isinstance(value, KnowledgeTaskRequest):
        return value
    raw = dict(value)
    return KnowledgeTaskRequest(
        agentlab_root=Path(raw["agentlab_root"]),
        project=str(raw["project"]),
        task_id=str(raw["task_id"]),
        request_text=str(raw.get("request_text") or ""),
        domain=str(raw["domain"]) if raw.get("domain") else None,
        modalities=tuple(Modality(item) for item in raw.get("modalities") or ()),
        required_channels=tuple(str(item) for item in raw.get("required_channels") or ()),
        file_hints=tuple(str(item) for item in raw.get("file_hints") or ()),
    )
