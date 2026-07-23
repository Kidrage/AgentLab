"""Compatibility import for the former JSONL local-search index."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from agent_runtime.local_search.storage import load_index
from agent_runtime.policies import assert_path_allowed

from .config import load_knowledge_config
from .models import (
    AuthorityLevel,
    KnowledgeLifecycle,
    KnowledgeRecord,
    SourceRef,
)
from .sources import _modality_for
from .storage import KnowledgeStore


def import_legacy_jsonl(
    agentlab_root: Path,
    index_path: Path,
    *,
    namespace: str,
    project_id: str | None = None,
    source_root: Path | None = None,
    authority: AuthorityLevel = AuthorityLevel.AUDIT,
) -> dict[str, Any]:
    """Import legacy Documents, downgrading unverifiable entries to stale audit data."""
    if authority in {AuthorityLevel.CANONICAL, AuthorityLevel.ACCEPTED}:
        raise ValueError("legacy import cannot assign eligible authority without promotion")
    root = Path(agentlab_root).resolve()
    index_path = assert_path_allowed(index_path, root)
    source_root = assert_path_allowed(source_root or root, root)
    records = []
    stale_count = 0
    audit_count = 0
    skipped_count = 0
    for document in load_index(index_path):
        try:
            actual_path = assert_path_allowed(source_root / document.path, root)
            source_path = actual_path.relative_to(root).as_posix()
            actual_hash = None
            if actual_path.is_file():
                actual_hash = hashlib.sha256(actual_path.read_bytes()).hexdigest()
            mismatch = actual_hash != document.content_hash
            record_authority = AuthorityLevel.AUDIT if mismatch else authority
            lifecycle = KnowledgeLifecycle.STALE if mismatch else KnowledgeLifecycle.ACTIVE
            if mismatch:
                stale_count += 1
            if record_authority is AuthorityLevel.AUDIT:
                audit_count += 1
            records.append(
                KnowledgeRecord.create(
                    namespace=namespace,
                    project_id=project_id,
                    source=SourceRef(source_path, document.content_hash, "legacy_jsonl"),
                    content=document.text,
                    authority=record_authority,
                    lifecycle=lifecycle,
                    modality=_modality_for(actual_path),
                    object_kind="legacy_document",
                    metadata={
                        "legacy_source_category": document.source_category,
                        "legacy_index": index_path.relative_to(root).as_posix(),
                        "source_hash_verified": not mismatch,
                        "actual_content_hash": actual_hash,
                    },
                )
            )
        except (OSError, ValueError):
            skipped_count += 1
    config = load_knowledge_config(root)
    store = KnowledgeStore(root, config.runtime_path, config.keyword_backend)
    store.sync_records(
        namespace,
        records,
        scope=f"legacy_jsonl:{index_path.relative_to(root).as_posix()}",
    )
    return {
        "status": "IMPORTED",
        "namespace": namespace,
        "record_count": len(records),
        "active_count": len(records) - stale_count,
        "stale_count": stale_count,
        "audit_count": audit_count,
        "skipped_count": skipped_count,
        "index_snapshot": store.index_snapshot((namespace,)),
    }
