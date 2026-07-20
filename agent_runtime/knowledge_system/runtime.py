"""Deep public interface for governed task retrieval and update proposals."""

from __future__ import annotations

from collections import defaultdict
import hashlib
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.policies import assert_path_allowed, ensure_safe_task_id

from .config import KnowledgeSystemConfig, load_knowledge_config
from .models import (
    AuthorityLevel,
    EvidenceBundle,
    EvidenceItem,
    KnowledgeRequirement,
    KnowledgeSyncReceipt,
    KnowledgeTaskRequest,
    KnowledgeUpdateProposal,
    Modality,
    PreparedKnowledgeContext,
    RetrievalTrace,
    TaskRetrievalView,
    coerce_task_request,
    stable_digest,
    validate_namespace,
)
from .sources import SourceCollector
from .storage import ELIGIBLE_AUTHORITIES, KnowledgeStore, SearchHit


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_CONTEXTS: dict[str, PreparedKnowledgeContext] = {}


class InsufficientEvidenceError(RuntimeError):
    """Raised by enforcing callers when required retrieval evidence is absent."""

    def __init__(self, prepared: PreparedKnowledgeContext) -> None:
        self.prepared = prepared
        super().__init__(
            "INSUFFICIENT_EVIDENCE: "
            + (", ".join(prepared.evidence_bundle.missing_channels) or "no eligible evidence")
        )


def prepare_task(request: KnowledgeTaskRequest | Mapping[str, Any]) -> PreparedKnowledgeContext:
    """Create task-scoped retrieval requirements, evidence, and an audit trace."""
    task = coerce_task_request(request)
    root = Path(task.agentlab_root).resolve()
    project = _safe_identifier(task.project, "project")
    task_id = ensure_safe_task_id(task.task_id)
    domain = _safe_identifier(task.domain or _infer_domain(task.request_text), "domain")
    config = load_knowledge_config(root)
    namespaces = (
        "system.agentlab",
        validate_namespace(f"domain.{domain}"),
        validate_namespace(f"project.{project}"),
    )
    modalities = tuple(item.value for item in task.modalities) or _modalities_for(domain)
    required_channels = task.required_channels or config.required_channels
    requirement_id = stable_digest(
        project,
        task_id,
        task.request_text,
        domain,
        modalities,
        namespaces,
        required_channels,
        prefix="req_",
    )
    requirement = KnowledgeRequirement(
        requirement_id=requirement_id,
        project=project,
        task_id=task_id,
        request_text=task.request_text,
        domain=domain,
        modalities=modalities,
        namespaces=namespaces,
        required_channels=tuple(required_channels),
        max_results=config.top_k,
    )
    view_id = stable_digest(requirement_id, task.file_hints, prefix="view_")
    view = TaskRetrievalView(
        view_id=view_id,
        task_id=task_id,
        query=task.request_text,
        namespaces=namespaces,
        channels=tuple(required_channels),
        filters={
            "authority": list(ELIGIBLE_AUTHORITIES),
            "lifecycle": ["active"],
            "file_hints": list(task.file_hints),
        },
        max_results=config.top_k,
    )
    if config.mode == "off":
        return _disabled_context(config, requirement, view)

    store = KnowledgeStore(root, config.runtime_path, config.keyword_backend)
    for namespace in namespaces:
        store.ensure_space(namespace)
    collector = SourceCollector(root, max_file_bytes=config.max_file_bytes)
    refresh_system = config.refresh_on_prepare or (
        config.bootstrap_missing_spaces and store.record_count("system.agentlab") == 0
    )
    project_namespace = f"project.{project}"
    domain_namespace = f"domain.{domain}"
    refresh_project = config.refresh_on_prepare or (
        config.bootstrap_missing_spaces and store.record_count(project_namespace) == 0
    )
    domain_scope = f"domain:{domain}:project:{project}"
    bootstrap_domain = (
        config.bootstrap_missing_spaces
        and store.active_scope_record_count(domain_namespace, domain_scope) == 0
    )
    if config.index_system_sources and refresh_system:
        store.sync_records(
            "system.agentlab",
            collector.collect_system(),
            scope="system:global_sources",
        )
    if config.index_project_sources and refresh_project:
        store.sync_records(
            project_namespace,
            collector.collect_project(project, domain=domain),
            scope=f"project:{project}:global_sources",
        )
    if config.index_project_sources and bootstrap_domain:
        store.sync_records(
            domain_namespace,
            collector.collect_project(project, domain=domain, namespace=domain_namespace),
            scope=domain_scope,
        )

    channel_hits: dict[str, list[SearchHit]] = {}
    steps: list[dict[str, Any]] = [
        {
            "stage": "metadata_filter",
            "eligible_authority": list(ELIGIBLE_AUTHORITIES),
            "eligible_lifecycle": ["active"],
        }
    ]
    warnings: list[str] = []
    degraded = False
    for channel in required_channels:
        if channel == "keyword":
            hits = store.search(
                namespaces,
                task.request_text,
                max_results=config.top_k,
                modalities=modalities,
                path_hints=task.file_hints,
            )
            channel_hits[channel] = hits
            backends = sorted({hit.backend for hit in hits})
            degraded = degraded or "degraded_bm25" in backends
            steps.append(
                {"stage": "keyword", "backend": backends or ["sqlite_fts5"], "result_count": len(hits)}
            )
        else:
            channel_hits[channel] = []
            warnings.append(f"{channel} retrieval adapter is not configured")
            steps.append({"stage": channel, "backend": "unavailable", "result_count": 0})

    fused = _reciprocal_rank_fusion(channel_hits, limit=config.top_k)
    snapshot = store.index_snapshot(namespaces)
    missing_channels = tuple(channel for channel in required_channels if not channel_hits.get(channel))
    evidence_items = tuple(
        _evidence_item(hit, channel, rank, score)
        for rank, (hit, channel, score) in enumerate(fused, start=1)
    )
    steps.append(
        {
            "stage": "deterministic_rrf",
            "k": 60,
            "result_count": len(evidence_items),
            "record_ids": [item.record_id for item in evidence_items],
        }
    )
    status = "READY" if evidence_items and not missing_channels else "INSUFFICIENT_EVIDENCE"
    trace_id = stable_digest(view_id, snapshot, steps, prefix="trace_")
    trace = RetrievalTrace(
        trace_id=trace_id,
        index_snapshot=snapshot,
        channels=tuple(required_channels),
        steps=tuple(steps),
        degraded=degraded,
        warnings=tuple(warnings),
    )
    bundle_id = stable_digest(
        view_id,
        snapshot,
        status,
        [item.evidence_id for item in evidence_items],
        missing_channels,
        prefix="bundle_",
    )
    bundle = EvidenceBundle(
        bundle_id=bundle_id,
        status=status,
        items=evidence_items,
        missing_channels=missing_channels,
        trace=trace,
    )
    context_ref = stable_digest(requirement_id, view_id, bundle_id, prefix="kctx_")
    prepared = PreparedKnowledgeContext(
        context_ref=context_ref,
        status=status,
        mode=config.mode,
        requirement=requirement,
        retrieval_view=view,
        evidence_bundle=bundle,
        warnings=tuple(warnings),
    )
    _CONTEXTS[context_ref] = prepared
    _write_task_knowledge(root, project, task_id, prepared)
    return prepared


def evaluate_outcome(
    outcome: Mapping[str, Any],
    context_ref: str | PreparedKnowledgeContext,
) -> KnowledgeUpdateProposal:
    """Validate claim evidence and return a proposal; never mutate authority."""
    prepared_data = _resolve_prepared_context(outcome, context_ref)
    if prepared_data is None:
        raise KeyError(f"unknown knowledge context_ref: {context_ref}")
    resolved_context_ref = str(prepared_data["context_ref"])
    items = ((prepared_data.get("evidence_bundle") or {}).get("items") or [])
    known = {str(item["evidence_id"]): item for item in items}
    claims = tuple(dict(item) for item in outcome.get("claims") or ())
    errors: list[str] = []
    warnings: list[str] = []
    normalized_claims = []
    for index, claim in enumerate(claims):
        refs = claim.get("evidence_refs") or []
        evidence_ids = [
            str(item.get("evidence_id")) if isinstance(item, dict) else str(item)
            for item in refs
        ]
        missing = sorted(item for item in evidence_ids if item not in known)
        if not evidence_ids:
            errors.append(f"claims[{index}]: evidence_refs are required")
        if missing:
            errors.append(f"claims[{index}]: unknown evidence refs: {', '.join(missing)}")
        ineligible = [
            item
            for item in evidence_ids
            if item in known and str(known[item].get("authority")) not in ELIGIBLE_AUTHORITIES
        ]
        if ineligible:
            errors.append(f"claims[{index}]: ineligible evidence authority: {', '.join(ineligible)}")
        changed_sources = [
            item
            for item in evidence_ids
            if item in known and not _evidence_hash_is_current(outcome, known[item])
        ]
        if changed_sources:
            errors.append(f"claims[{index}]: source hash changed: {', '.join(changed_sources)}")
        normalized = dict(claim)
        normalized["evidence_refs"] = evidence_ids
        normalized_claims.append(normalized)

    proposed_records = []
    for index, item in enumerate(outcome.get("knowledge_updates") or ()):
        record = dict(item)
        requested_authority = str(record.get("authority") or AuthorityLevel.CANDIDATE.value)
        if requested_authority != AuthorityLevel.CANDIDATE.value:
            warnings.append(
                f"knowledge_updates[{index}]: authority '{requested_authority}' reduced to candidate pending governance"
            )
        record["authority"] = AuthorityLevel.CANDIDATE.value
        record["lifecycle"] = "active"
        proposed_records.append(record)

    status = "INSUFFICIENT_EVIDENCE" if errors else "PROPOSE_ONLY"
    proposal_id = stable_digest(
        resolved_context_ref,
        normalized_claims,
        proposed_records,
        status,
        prefix="kup_",
    )
    return KnowledgeUpdateProposal(
        proposal_id=proposal_id,
        status=status,
        context_ref=resolved_context_ref,
        claims=tuple(normalized_claims),
        proposed_records=tuple(proposed_records),
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def sync_committed(commit_receipt: Mapping[str, Any]) -> KnowledgeSyncReceipt:
    """Incrementally refresh derived indexes after existing governance commits truth."""
    raw = dict(commit_receipt)
    root = Path(raw["agentlab_root"]).resolve()
    project = _safe_identifier(str(raw["project"]), "project")
    committed_status = str(raw.get("status") or raw.get("verdict") or "").lower()
    collector = SourceCollector(root)
    domain = _safe_identifier(
        str(raw.get("domain") or collector.infer_project_domain(project)),
        "domain",
    )
    namespaces = (
        validate_namespace(f"project.{project}"),
        validate_namespace(f"domain.{domain}"),
    )
    receipt_id = stable_digest(raw, prefix="ksync_")
    if committed_status not in {"committed", "promoted", "accepted", "pass"}:
        return KnowledgeSyncReceipt(
            receipt_id=receipt_id,
            status="REJECTED",
            project=project,
            namespaces=namespaces,
            index_snapshot=None,
            warnings=("commit receipt does not prove accepted or promoted state",),
        )
    paths = tuple(str(item) for item in raw.get("committed_paths") or raw.get("promoted_paths") or ())
    invalid_paths = tuple(path for path in paths if not _is_governed_truth_path(root, project, path))
    if invalid_paths:
        return KnowledgeSyncReceipt(
            receipt_id=receipt_id,
            status="REJECTED",
            project=project,
            namespaces=namespaces,
            index_snapshot=None,
            warnings=(
                "commit receipt includes paths outside production, Project Brain, or the artifact index: "
                + ", ".join(invalid_paths),
            ),
        )
    missing_paths = tuple(
        path for path in paths if not assert_path_allowed(path, root).is_file()
    )
    if missing_paths:
        return KnowledgeSyncReceipt(
            receipt_id=receipt_id,
            status="REJECTED",
            project=project,
            namespaces=namespaces,
            index_snapshot=None,
            warnings=(
                "commit receipt includes governed paths that are missing or not files: "
                + ", ".join(missing_paths),
            ),
        )
    store: KnowledgeStore | None = None
    try:
        config = load_knowledge_config(root)
        store = KnowledgeStore(root, config.runtime_path, config.keyword_backend)
        collector = SourceCollector(root, max_file_bytes=config.max_file_bytes)
        for namespace in namespaces:
            store.ensure_space(namespace)
        records_by_namespace: dict[str, list] = {}
        if paths:
            canonical_paths = tuple(
                path for path in paths if _governed_truth_authority(root, project, path) is AuthorityLevel.CANONICAL
            )
            accepted_paths = tuple(path for path in paths if path not in canonical_paths)
            for namespace in namespaces:
                records = [
                    *collector.collect_paths(
                        canonical_paths,
                        namespace=namespace,
                        project_id=project,
                        authority=AuthorityLevel.CANONICAL,
                        object_kind="committed_project_fact",
                    ),
                    *collector.collect_paths(
                        accepted_paths,
                        namespace=namespace,
                        project_id=project,
                        authority=AuthorityLevel.ACCEPTED,
                        object_kind="committed_artifact",
                    ),
                ]
                records_by_namespace[namespace] = records
                store.sync_records(
                    namespace,
                    records,
                    scope=_source_scope(namespace, project=project, domain=domain),
                    tombstone_missing=False,
                )
        else:
            for namespace in namespaces:
                records = collector.collect_project(
                    project,
                    domain=domain,
                    namespace=namespace,
                )
                records_by_namespace[namespace] = records
                store.sync_records(
                    namespace,
                    records,
                    scope=_source_scope(namespace, project=project, domain=domain),
                )
        snapshot = store.index_snapshot(namespaces)
        indexed_paths = {
            record.source.path
            for records in records_by_namespace.values()
            for record in records
        }
        return KnowledgeSyncReceipt(
            receipt_id=receipt_id,
            status="SYNCED",
            project=project,
            namespaces=namespaces,
            index_snapshot=snapshot,
            indexed_paths=tuple(sorted(indexed_paths)),
        )
    except Exception as exc:
        snapshot = None
        if store is not None:
            try:
                for namespace in namespaces:
                    store.mark_stale(namespace)
                snapshot = store.index_snapshot(namespaces)
            except Exception:
                snapshot = None
        return KnowledgeSyncReceipt(
            receipt_id=receipt_id,
            status="INDEX_STALE",
            project=project,
            namespaces=namespaces,
            index_snapshot=snapshot,
            stale_namespaces=namespaces,
            warnings=(f"derived index refresh failed; committed truth was not rolled back: {exc}",),
        )


def _is_governed_truth_path(root: Path, project: str, raw_path: str) -> bool:
    return _governed_truth_authority(root, project, raw_path) is not None


def _governed_truth_authority(
    root: Path,
    project: str,
    raw_path: str,
) -> AuthorityLevel | None:
    try:
        path = assert_path_allowed(raw_path, root)
    except ValueError:
        return None
    project_root = assert_path_allowed(root / "projects" / project, root)
    production_root = project_root / "production"
    release_objects_root = project_root / "release_objects"
    brain_root = project_root / "project_brain"
    artifact_index = project_root / "project_artifact_index.yml"
    if path == artifact_index.resolve() or path.is_relative_to(brain_root.resolve()):
        return AuthorityLevel.CANONICAL
    if path.is_relative_to(production_root.resolve()) or path.is_relative_to(
        release_objects_root.resolve()
    ):
        return AuthorityLevel.ACCEPTED
    return None


def _source_scope(namespace: str, *, project: str, domain: str) -> str:
    if namespace == f"domain.{domain}":
        return f"domain:{domain}:project:{project}"
    return f"project:{project}:global_sources"


def _disabled_context(
    config: KnowledgeSystemConfig,
    requirement: KnowledgeRequirement,
    view: TaskRetrievalView,
) -> PreparedKnowledgeContext:
    trace = RetrievalTrace(
        trace_id=stable_digest(view.view_id, "off", prefix="trace_"),
        index_snapshot="disabled",
        channels=view.channels,
        steps=({"stage": "knowledge_system", "status": "off"},),
    )
    bundle = EvidenceBundle(
        bundle_id=stable_digest(view.view_id, "off", prefix="bundle_"),
        status="DISABLED",
        items=(),
        missing_channels=(),
        trace=trace,
    )
    return PreparedKnowledgeContext(
        context_ref=stable_digest(requirement.requirement_id, "off", prefix="kctx_"),
        status="DISABLED",
        mode=config.mode,
        requirement=requirement,
        retrieval_view=view,
        evidence_bundle=bundle,
    )


def _reciprocal_rank_fusion(
    channel_hits: Mapping[str, Sequence[SearchHit]],
    *,
    limit: int,
) -> list[tuple[SearchHit, str, float]]:
    scores: dict[str, float] = defaultdict(float)
    selected: dict[str, tuple[SearchHit, str]] = {}
    for channel in sorted(channel_hits):
        seen_in_channel: set[str] = set()
        for rank, hit in enumerate(channel_hits[channel], start=1):
            identity = f"{hit.source.path}:{hit.source.content_hash}"
            if identity in seen_in_channel:
                current = selected.get(identity)
                if current is not None and _namespace_priority(hit.namespace) < _namespace_priority(
                    current[0].namespace
                ):
                    selected[identity] = (hit, channel)
                continue
            seen_in_channel.add(identity)
            scores[identity] += 1.0 / (60 + rank)
            current = selected.get(identity)
            if current is None or _namespace_priority(hit.namespace) < _namespace_priority(
                current[0].namespace
            ):
                selected[identity] = (hit, channel)
    ordered = sorted(
        selected,
        key=lambda identity: (
            -scores[identity],
            _namespace_priority(selected[identity][0].namespace),
            selected[identity][0].namespace,
            selected[identity][0].source.path,
            identity,
        ),
    )
    return [(*selected[identity], scores[identity]) for identity in ordered[:limit]]


def _namespace_priority(namespace: str) -> int:
    if namespace.startswith("project."):
        return 0
    if namespace.startswith("domain."):
        return 1
    return 2


def _evidence_item(hit: SearchHit, channel: str, rank: int, score: float) -> EvidenceItem:
    locator = f"{hit.source.path}#L{hit.line_start}-L{hit.line_end}"
    evidence_id = stable_digest(hit.record_id, locator, hit.source.content_hash, channel, prefix="ev_")
    return EvidenceItem(
        evidence_id=evidence_id,
        record_id=hit.record_id,
        namespace=hit.namespace,
        source=hit.source,
        locator=locator,
        excerpt=hit.excerpt,
        authority=hit.authority,
        lifecycle=hit.lifecycle,
        modality=hit.modality,
        object_kind=hit.object_kind,
        channel=channel,
        rank=rank,
        score=score,
        metadata=hit.metadata,
    )


def _write_task_knowledge(
    root: Path,
    project: str,
    task_id: str,
    prepared: PreparedKnowledgeContext,
) -> None:
    run_dir = assert_path_allowed(root / "projects" / project / "runs" / task_id, root)
    knowledge_dir = run_dir / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(knowledge_dir / "knowledge_requirement.yml", prepared.requirement.as_dict())
    atomic_write_yaml(knowledge_dir / "retrieval_view.yml", prepared.retrieval_view.as_dict())
    atomic_write_yaml(knowledge_dir / "evidence_bundle.yml", prepared.evidence_bundle.as_dict())
    atomic_write_yaml(knowledge_dir / "retrieval_trace.yml", prepared.evidence_bundle.trace.as_dict())
    atomic_write_yaml(knowledge_dir / "prepared_context.yml", prepared.as_dict())


def _resolve_prepared_context(
    outcome: Mapping[str, Any],
    context_ref: str | PreparedKnowledgeContext,
) -> dict[str, Any] | None:
    if isinstance(context_ref, PreparedKnowledgeContext):
        return context_ref.as_dict()
    if all(outcome.get(key) for key in ("agentlab_root", "project", "task_id")):
        root = Path(str(outcome["agentlab_root"])).resolve()
        project = _safe_identifier(str(outcome["project"]), "project")
        task_id = ensure_safe_task_id(str(outcome["task_id"]))
        path = assert_path_allowed(
            root / "projects" / project / "runs" / task_id / "knowledge" / "prepared_context.yml",
            root,
        )
        if path.is_file():
            import yaml

            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict) and data.get("context_ref") == context_ref:
                return data
    prepared = _CONTEXTS.get(context_ref)
    return prepared.as_dict() if prepared is not None else None


def _evidence_hash_is_current(outcome: Mapping[str, Any], evidence: Mapping[str, Any]) -> bool:
    if not outcome.get("agentlab_root"):
        return True
    root = Path(str(outcome["agentlab_root"])).resolve()
    source = evidence.get("source") or {}
    if source.get("kind") == "external":
        return False
    try:
        path = assert_path_allowed(str(source.get("path") or ""), root)
        current_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, ValueError):
        return False
    return current_hash == source.get("content_hash")


def _safe_identifier(value: str, label: str) -> str:
    if not _SAFE_IDENTIFIER.fullmatch(value):
        raise ValueError(f"unsafe {label} identifier: {value}")
    return value


def _infer_domain(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("novel", "chapter", "character", "narrative", "小说", "章节")):
        return "longform_narrative"
    if any(token in lowered for token in ("research", "source", "citation", "web", "研究", "引用")):
        return "research"
    if any(token in lowered for token in ("image", "video", "audio", "music", "图片", "视频", "音频")):
        return "media_production"
    if any(token in lowered for token in ("code", "repo", "test", "bug", "refactor", "代码", "仓库")):
        return "code_engineering"
    return "general_production"


def _modalities_for(domain: str) -> tuple[str, ...]:
    if domain == "code_engineering":
        return (Modality.CODE.value, Modality.STRUCTURED.value, Modality.TEXT.value)
    if domain in {"longform_narrative", "research"}:
        return (Modality.TEXT.value, Modality.STRUCTURED.value)
    if domain == "media_production":
        return (
            Modality.IMAGE.value,
            Modality.AUDIO.value,
            Modality.VIDEO.value,
            Modality.STRUCTURED.value,
        )
    return (Modality.TEXT.value, Modality.STRUCTURED.value)
