"""Compile the project-only evidence contract for one narrative chapter."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Iterable
import hashlib
import json

import yaml


class ChapterKnowledgeContractError(RuntimeError):
    """Raised when a chapter lacks one required evidence group."""


REQUIRED_EVIDENCE_GROUPS = (
    "chapter_card",
    "character_state",
    "timeline_world_rules",
    "foreshadowing",
    "prior_continuity",
)
ALLOWED_CANONICAL_ROOTS = ("production", "project_brain")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_source(
    project_root: Path,
    relative: str,
    *,
    canonical_only: bool,
) -> tuple[str, Path]:
    pure = PurePosixPath(str(relative))
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ChapterKnowledgeContractError(f"unsafe chapter evidence path: {relative!r}")
    normalized = pure.as_posix()
    if canonical_only and (not pure.parts or pure.parts[0] not in ALLOWED_CANONICAL_ROOTS):
        raise ChapterKnowledgeContractError(
            f"canonical evidence is outside production/project_brain: {normalized}"
        )
    path = (project_root / Path(*pure.parts)).resolve()
    root = project_root.resolve()
    if root not in path.parents or not path.is_file():
        raise ChapterKnowledgeContractError(f"missing chapter evidence: {normalized}")
    return normalized, path


def _read_mapping(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ChapterKnowledgeContractError(f"cannot read {label}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ChapterKnowledgeContractError(f"{label} must contain a YAML mapping")
    return raw


def build_chapter_knowledge_contract(
    project_root: Path,
    *,
    project: str,
    chapter: int,
    previous_sources: Iterable[str] = (),
) -> dict[str, Any]:
    """Return a complete, hash-bound five-group chapter evidence contract."""
    root = Path(project_root).resolve()
    card_relative = f"production/chapter_cards/ch{chapter:03d}.yml"
    card_key, card_path = _validated_source(root, card_relative, canonical_only=True)
    card = _read_mapping(card_path, "chapter card")
    if int(card.get("chapter") or 0) != chapter:
        raise ChapterKnowledgeContractError("chapter card number does not match packet chapter")
    requirements = card.get("knowledge_requirements")
    if not isinstance(requirements, dict):
        raise ChapterKnowledgeContractError("chapter card has no knowledge_requirements mapping")

    evidence_groups: dict[str, list[str]] = {"chapter_card": [card_key]}
    source_paths: dict[str, Path] = {card_key: card_path}
    for group in ("character_state", "timeline_world_rules", "foreshadowing"):
        refs = requirements.get(group)
        if not isinstance(refs, list) or not refs:
            raise ChapterKnowledgeContractError(f"missing chapter evidence group: {group}")
        resolved: list[str] = []
        for ref in refs:
            key, path = _validated_source(root, str(ref), canonical_only=True)
            resolved.append(key)
            source_paths[key] = path
        evidence_groups[group] = resolved

    continuity = list(previous_sources)
    if not continuity and chapter == 1:
        continuity = ["project_brain/project_fact_snapshot.yml"]
    if not continuity:
        raise ChapterKnowledgeContractError("missing chapter evidence group: prior_continuity")
    resolved_continuity: list[str] = []
    for ref in continuity:
        key, path = _validated_source(root, str(ref), canonical_only=chapter == 1)
        resolved_continuity.append(key)
        source_paths[key] = path
    evidence_groups["prior_continuity"] = resolved_continuity

    index_relative = "project_brain/knowledge_index_snapshot.yml"
    index_key, index_path = _validated_source(root, index_relative, canonical_only=True)
    index = _read_mapping(index_path, "knowledge index snapshot")
    expected_namespace = f"project.{project}"
    if str(index.get("namespace") or "") != expected_namespace or not index.get("index_snapshot"):
        raise ChapterKnowledgeContractError("knowledge index snapshot does not match project")
    if index.get("formal_fact_roots") != list(ALLOWED_CANONICAL_ROOTS):
        raise ChapterKnowledgeContractError("knowledge index snapshot has unsafe fact roots")
    source_paths[index_key] = index_path
    source_hashes = {key: _hash(path) for key, path in sorted(source_paths.items())}
    indexed_paths = {
        str(item) for item in index.get("indexed_paths") or [] if isinstance(item, str)
    }
    indexed_hashes = index.get("indexed_source_hashes")
    if not isinstance(indexed_hashes, dict):
        raise ChapterKnowledgeContractError("knowledge index snapshot has no source hashes")
    retrieval_hits: list[str] = []
    for key, current_hash in source_hashes.items():
        if key == index_key or not key.startswith(("production/", "project_brain/")):
            continue
        indexed_key = f"projects/{project}/{key}"
        if indexed_key not in indexed_paths:
            raise ChapterKnowledgeContractError(
                f"canonical evidence is not present in project RAG: {key}"
            )
        if str(indexed_hashes.get(indexed_key) or "") != current_hash:
            raise ChapterKnowledgeContractError(
                f"project RAG source hash does not match canonical evidence: {key}"
            )
        retrieval_hits.append(key)
    version_payload = json.dumps(
        {"index_snapshot": index["index_snapshot"], "source_hashes": source_hashes},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "schema_version": 1,
        "status": "pass",
        "namespace": expected_namespace,
        "retrieval_mode": "assist",
        "allowed_canonical_roots": list(ALLOWED_CANONICAL_ROOTS),
        "forbidden_roots": [
            "acceptance_runs",
            "agent_docs",
            "archive",
            "background_jobs",
            "candidates",
            "runs",
        ],
        "index_snapshot_path": index_key,
        "index_snapshot": index["index_snapshot"],
        "evidence_version": hashlib.sha256(version_payload.encode("utf-8")).hexdigest(),
        "evidence_groups": evidence_groups,
        "source_hashes": source_hashes,
        "retrieval_evidence": {
            "hit_paths": sorted(retrieval_hits),
            "missing_paths": [],
            "source_distribution": {
                root: sum(1 for item in retrieval_hits if item.startswith(f"{root}/"))
                for root in ALLOWED_CANONICAL_ROOTS
            },
            "context_bytes": sum(path.stat().st_size for path in source_paths.values()),
        },
        "missing_groups": [],
    }
