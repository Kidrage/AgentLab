"""Compile the project-only evidence contract for one narrative chapter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

import yaml

from agent_runtime.narrative.fact_authority import (
    assert_fact_authority_evidence,
    assert_fact_authority_projection,
    load_fact_authority,
    verify_registered_fact_authority,
)
from agent_runtime.narrative.state_store import (
    NarrativeStateError,
    NarrativeStateStore,
)


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


def _active_fact_authority_declarations(
    project_root: Path,
) -> list[dict[str, Any]]:
    declarations: list[dict[str, Any]] = []
    locations = (
        ("project_brain/project_state_contract.yml", "active_fact_authority"),
        ("production/canonical/index.yml", "field_authority"),
    )
    for relative, field in locations:
        path = project_root / relative
        if not path.is_file():
            continue
        document = _read_mapping(path, relative)
        declaration = document.get(field)
        if declaration is None:
            continue
        if not isinstance(declaration, dict):
            raise ChapterKnowledgeContractError(
                f"{relative} {field} must be a mapping"
            )
        declarations.append(dict(declaration))
    return declarations


def _records_from_evidence(
    document: Mapping[str, Any],
    *,
    target: str,
) -> dict[str, Any]:
    direct = document.get(target)
    if isinstance(direct, Mapping):
        return dict(direct)
    records = document.get("records")
    if isinstance(records, list):
        return {
            str(record["id"]): dict(record)
            for record in records
            if isinstance(record, Mapping) and str(record.get("id") or "").strip()
        }
    entity_id = str(document.get("id") or "").strip()
    return {entity_id: dict(document)} if entity_id else {}


def _assert_contract_evidence_projection(
    source_paths: Mapping[str, Path],
    evidence_groups: Mapping[str, list[str]],
    authority: Mapping[str, Any],
) -> None:
    target_groups = {
        "characters": "character_state",
        "foreshadowing": "foreshadowing",
        "world_axes": "timeline_world_rules",
    }
    state: dict[str, dict[str, Any]] = {}
    for target in {fact["target"] for fact in authority["facts"]}:
        group = target_groups.get(target)
        if group is None:
            raise ChapterKnowledgeContractError(
                f"fact authority target has no chapter evidence group: {target}"
            )
        combined: dict[str, Any] = {}
        for relative in evidence_groups[group]:
            document = _read_mapping(source_paths[relative], relative)
            combined.update(_records_from_evidence(document, target=target))
        state[target] = combined
    try:
        assert_fact_authority_projection(state, authority)
    except ValueError as exc:
        raise ChapterKnowledgeContractError(str(exc)) from exc


def _assert_event_ledger_authority_binding(
    project_root: Path,
    *,
    project: str,
    authority: Mapping[str, Any],
    source_sha256: str,
) -> None:
    active = _event_ledger_active_authority(project_root, project=project)
    if active is None:
        raise ChapterKnowledgeContractError(
            "fact authority event ledger has no unique active authority"
        )
    authority_id, metadata = active
    if (
        authority_id != authority["authority_id"]
        or metadata.get("revision") != authority["revision"]
        or metadata.get("source_sha256") != source_sha256
        or metadata.get("source_path") != "production/fact_authority.yml"
    ):
        raise ChapterKnowledgeContractError(
            "fact authority event ledger binding mismatch"
        )


def _event_ledger_active_authority(
    project_root: Path,
    *,
    project: str,
) -> tuple[str, Mapping[str, Any]] | None:
    if not (project_root / "project_brain/narrative_state_events.jsonl").is_file():
        return None
    try:
        snapshot = NarrativeStateStore(
            project_root / "project_brain",
            project=project,
        ).read()
    except (OSError, ValueError, NarrativeStateError) as exc:
        raise ChapterKnowledgeContractError(
            f"cannot verify fact authority event ledger: {exc}"
        ) from exc
    active = snapshot.get("fact_authorities")
    if not active:
        return None
    if not isinstance(active, Mapping) or len(active) != 1:
        raise ChapterKnowledgeContractError(
            "fact authority event ledger has no unique active authority"
        )
    authority_id, metadata = next(iter(active.items()))
    if not isinstance(metadata, Mapping):
        raise ChapterKnowledgeContractError(
            "fact authority event ledger active metadata is invalid"
        )
    return str(authority_id), metadata


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

    fact_authority_declarations = _active_fact_authority_declarations(root)
    active_authority: dict[str, Any] | None = None
    active_authority_sha256: str | None = None
    active_authority_key: str | None = None
    declared_paths = {
        str(item.get("path") or "") for item in fact_authority_declarations
    }
    if len(declared_paths) > 1:
        raise ChapterKnowledgeContractError(
            "active fact authority declarations disagree on path"
        )
    fact_authority_relative = (
        next(iter(declared_paths))
        if declared_paths
        else "production/fact_authority.yml"
    )
    authority_pure = PurePosixPath(fact_authority_relative)
    if (
        authority_pure.is_absolute()
        or not authority_pure.parts
        or any(part in {"", ".", ".."} for part in authority_pure.parts)
    ):
        raise ChapterKnowledgeContractError(
            "active fact authority declaration path is unsafe"
        )
    fact_authority_path = root / Path(*authority_pure.parts)
    artifact_index_selects_authority = False
    artifact_index_path = root / "project_artifact_index.yml"
    if artifact_index_path.is_file():
        artifact_index = _read_mapping(
            artifact_index_path,
            "project artifact index",
        )
        current = artifact_index.get("current")
        artifact_index_selects_authority = isinstance(
            current,
            Mapping,
        ) and "production/fact_authority.yml" in current.values()
    ledger_active_authority = _event_ledger_active_authority(
        root,
        project=project,
    )
    authority_required = bool(
        fact_authority_declarations
        or artifact_index_selects_authority
        or ledger_active_authority
        or (root / "project_brain/narrative_governance_v3.yml").is_file()
    )
    if authority_required and not fact_authority_path.is_file():
        message = (
            "missing declared active fact authority"
            if fact_authority_declarations
            else "missing active fact authority"
        )
        raise ChapterKnowledgeContractError(message)
    if fact_authority_path.is_file():
        try:
            authority, authority_sha256 = load_fact_authority(
                fact_authority_path,
                project=project,
            )
            verify_registered_fact_authority(
                root,
                authority,
                authority_sha256,
            )
            for declaration in fact_authority_declarations:
                if (
                    declaration.get("path") != fact_authority_relative
                    or declaration.get("authority_id") != authority["authority_id"]
                    or declaration.get("revision") != authority["revision"]
                    or declaration.get("sha256") != authority_sha256
                ):
                    raise ValueError(
                        "active fact authority declaration binding mismatch"
                    )
            _assert_event_ledger_authority_binding(
                root,
                project=project,
                authority=authority,
                source_sha256=authority_sha256,
            )
            assert_fact_authority_evidence(
                root,
                authority,
                source_sha256=authority_sha256,
            )
        except ValueError as exc:
            raise ChapterKnowledgeContractError(
                f"invalid active fact authority: {exc}"
            ) from exc
        _assert_contract_evidence_projection(
            source_paths,
            evidence_groups,
            authority,
        )
        authority_key, authority_path = _validated_source(
            root,
            fact_authority_relative,
            canonical_only=True,
        )
        if authority_key not in evidence_groups["character_state"]:
            evidence_groups["character_state"].append(authority_key)
        source_paths[authority_key] = authority_path
        active_authority = authority
        active_authority_sha256 = authority_sha256
        active_authority_key = authority_key

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
    if (
        active_authority is not None
        and active_authority_sha256 is not None
        and active_authority_key is not None
    ):
        if source_hashes.get(active_authority_key) != active_authority_sha256:
            raise ChapterKnowledgeContractError(
                "active fact authority changed during context compilation"
            )
        try:
            verify_registered_fact_authority(
                root,
                active_authority,
                active_authority_sha256,
            )
        except ValueError as exc:
            raise ChapterKnowledgeContractError(
                f"active fact authority changed during context compilation: {exc}"
            ) from exc
        _assert_event_ledger_authority_binding(
            root,
            project=project,
            authority=active_authority,
            source_sha256=active_authority_sha256,
        )
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
