"""Operator-facing knowledge build and inspection operations."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable, Mapping

import yaml

from agent_runtime.atomic_io import atomic_write_json, atomic_write_text, atomic_write_yaml

from .config import VALID_MODES, load_knowledge_config
from .models import KnowledgeTaskRequest, stable_digest, validate_namespace
from .runtime import prepare_task
from .sources import SourceCollector
from .storage import KnowledgeStore


MODE_ORDER = ("off", "shadow", "assist", "enforce")


def build_knowledge_base(
    agentlab_root: Path,
    *,
    projects: Iterable[str] = (),
    include_all_projects: bool = False,
    project_domains: Mapping[str, str] | None = None,
) -> dict:
    """Build system, project, and domain indexes without changing source authority."""
    root = Path(agentlab_root).resolve()
    config = load_knowledge_config(root)
    store = KnowledgeStore(root, config.runtime_path, config.keyword_backend)
    collector = SourceCollector(root, max_file_bytes=config.max_file_bytes)
    receipts_dir = store.root / "receipts"

    system_records = collector.collect_system(include_ineligible=True)
    store.sync_records("system.agentlab", system_records, scope="system:global_sources")

    requested = set(str(item) for item in projects)
    disallowed = sorted(project for project in requested if not config.allows_project(project))
    if disallowed:
        raise ValueError(
            "projects are excluded by knowledge indexing.project_allowlist: "
            + ", ".join(disallowed)
        )
    selected = set(requested)
    if include_all_projects:
        selected.update(
            project
            for project in collector.discover_projects()
            if config.allows_project(project)
        )
    retired_namespaces: tuple[str, ...] = ()
    purged_record_counts: dict[str, int] = {}
    if include_all_projects:
        keep_project_namespaces = {f"project.{project}" for project in selected}
        spaces = store.describe_spaces()
        empty_domain_namespaces: list[str] = []
        for item in spaces:
            namespace = item["namespace"]
            if not namespace.startswith("domain."):
                continue
            deleted, remaining = store.prune_project_records(namespace, selected)
            if deleted:
                purged_record_counts[namespace] = deleted
            if remaining == 0:
                empty_domain_namespaces.append(namespace)
        retired_namespaces = store.retire_spaces(
            [
                item["namespace"]
                for item in spaces
                if item["namespace"].startswith("project.")
                and item["namespace"] not in keep_project_namespaces
            ]
            + empty_domain_namespaces
        )
    domains = dict(project_domains or {})
    resolved_domains: dict[str, str] = {}
    namespaces = {"system.agentlab"}
    record_counts = {"system.agentlab": len(system_records)}

    for project in sorted(selected):
        project_namespace = validate_namespace(f"project.{project}")
        domain = str(domains.get(project) or collector.infer_project_domain(project))
        domain_namespace = validate_namespace(f"domain.{domain}")
        for previous_namespace, previous_scope in store.project_domain_memberships(project):
            if previous_namespace == domain_namespace:
                continue
            store.sync_records(
                previous_namespace,
                [],
                scope=previous_scope,
            )
        project_records = collector.collect_project(
            project,
            domain=domain,
            namespace=project_namespace,
            include_ineligible=True,
        )
        domain_records = collector.collect_project(
            project,
            domain=domain,
            namespace=domain_namespace,
            include_ineligible=True,
        )
        store.sync_records(
            project_namespace,
            project_records,
            scope=f"project:{project}:global_sources",
        )
        store.sync_records(
            domain_namespace,
            domain_records,
            scope=f"domain:{domain}:project:{project}",
        )
        namespaces.update((project_namespace, domain_namespace))
        record_counts[project_namespace] = len(project_records)
        record_counts[domain_namespace] = record_counts.get(domain_namespace, 0) + len(domain_records)
        resolved_domains[project] = domain

    ordered_namespaces = sorted(namespaces)
    snapshot = store.index_snapshot(ordered_namespaces)
    built_at = datetime.now(timezone.utc).isoformat()
    receipt = {
        "status": "BUILT",
        "receipt_id": stable_digest(
            snapshot,
            sorted(selected),
            resolved_domains,
            record_counts,
            retired_namespaces,
            purged_record_counts,
            prefix="kbuild_",
        ),
        "built_at": built_at,
        "projects": sorted(selected),
        "project_domains": resolved_domains,
        "namespaces": ordered_namespaces,
        "record_counts": record_counts,
        "index_snapshot": snapshot,
        "runtime_path": store.root.relative_to(root).as_posix(),
        "retired_namespaces": list(retired_namespaces),
        "purged_record_counts": purged_record_counts,
    }
    atomic_write_json(receipts_dir / "latest_build.json", receipt, ensure_ascii=False, indent=2)
    return receipt


def write_project_knowledge_snapshot(
    agentlab_root: Path,
    *,
    project: str,
    build_receipt: Mapping[str, object],
) -> dict:
    """Seal the exact project-only RAG view available to narrative Writer packets."""
    root = Path(agentlab_root).resolve()
    if project not in tuple(str(item) for item in build_receipt.get("projects") or ()):
        raise ValueError(f"build receipt does not include project: {project}")
    namespace = validate_namespace(f"project.{project}")
    config = load_knowledge_config(root)
    store = KnowledgeStore(root, config.runtime_path, config.keyword_backend)
    if not store.space_exists(namespace):
        raise ValueError(f"project knowledge namespace is missing: {namespace}")
    prefix = f"projects/{project}/"
    snapshot_path = f"{prefix}project_brain/knowledge_index_snapshot.yml"
    eligible_hashes = store.eligible_source_hashes(namespace)
    manifest_path = root / "projects" / project / "project.yml"
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError):
        manifest = {}
    features = manifest.get("features") if isinstance(manifest, dict) else {}
    truth_mode = str((features or {}).get("project_truth_mode") or "legacy")
    if truth_mode == "enforced":
        pointer_path = f"{prefix}project_truth.yml"
        snapshot_prefix = f"{prefix}.agentlab/truth/snapshots/"
        source_hashes = {
            path: source_hash
            for path, source_hash in eligible_hashes.items()
            if path == pointer_path or path.startswith(snapshot_prefix)
        }
        formal_fact_roots = ["canonical_truth"]
    else:
        formal_prefixes = tuple(
            f"{prefix}{item}/" for item in ("production", "project_brain")
        )
        source_hashes = {
            path: source_hash
            for path, source_hash in eligible_hashes.items()
            if path.startswith(formal_prefixes) and path != snapshot_path
        }
        formal_fact_roots = ["production", "project_brain"]
    result = {
        "schema_version": 1,
        "status": "sealed",
        "namespace": namespace,
        "index_snapshot": store.index_snapshot((namespace,)),
        "build_receipt_id": str(build_receipt.get("receipt_id") or ""),
        "formal_fact_roots": formal_fact_roots,
        "indexed_paths": sorted(source_hashes),
        "indexed_source_hashes": dict(sorted(source_hashes.items())),
        "forbidden_writer_roots": [
            "acceptance_runs",
            "agent_docs",
            "archive",
            "background_jobs",
            "candidates",
            "runs",
        ],
    }
    atomic_write_yaml(
        root / "projects" / project / "project_brain" / "knowledge_index_snapshot.yml",
        result,
    )
    return result


def knowledge_status(agentlab_root: Path) -> dict:
    """Describe configured mode and every local derived knowledge space."""
    root = Path(agentlab_root).resolve()
    config = load_knowledge_config(root)
    store = KnowledgeStore(root, config.runtime_path, config.keyword_backend)
    try:
        store.root.relative_to(root)
        storage_inside_agentlab = True
    except ValueError:
        storage_inside_agentlab = False
    spaces = store.describe_spaces()
    return {
        "status": "READY" if spaces else "EMPTY",
        "mode": config.mode,
        "auto_memory": config.auto_memory,
        "project_allowlist": list(config.project_allowlist),
        "runtime_path": store.root.relative_to(root).as_posix(),
        "storage_inside_agentlab": storage_inside_agentlab,
        "space_count": len(spaces),
        "record_count": sum(item["record_count"] for item in spaces),
        "eligible_record_count": sum(item["eligible_record_count"] for item in spaces),
        "spaces": spaces,
    }


def activate_knowledge_mode(
    agentlab_root: Path,
    mode: str,
    *,
    actor: str,
    reason: str,
) -> dict:
    """Advance one validated rollout stage, or roll back to a safer stage."""
    root = Path(agentlab_root).resolve()
    target = str(mode).strip().lower()
    if target not in VALID_MODES:
        raise ValueError(f"knowledge mode must be one of {sorted(VALID_MODES)}")
    if not actor.strip() or not reason.strip():
        raise ValueError("knowledge activation requires actor and reason")
    config = load_knowledge_config(root)
    current = config.mode
    current_rank = MODE_ORDER.index(current)
    target_rank = MODE_ORDER.index(target)
    status = knowledge_status(root)
    receipts_dir = root / config.runtime_path / "receipts"

    if target_rank > current_rank:
        if target_rank != current_rank + 1:
            raise ValueError(f"knowledge rollout must be sequential; activate {MODE_ORDER[current_rank + 1]} first")
        if current == "off":
            if status["eligible_record_count"] < 1:
                raise ValueError("build the knowledge base before activating shadow mode")
        else:
            validation_path = receipts_dir / "latest_validation.json"
            validation = _read_json(validation_path)
            if validation.get("status") != "PASS" or validation.get("mode") != current:
                raise ValueError(f"validate {current} mode successfully before activating {target}")

    changed_at = datetime.now(timezone.utc).isoformat()
    transition = f"{current}->{target}"
    receipt = {
        "status": "ACTIVATED",
        "receipt_id": stable_digest(transition, actor, reason, changed_at, prefix="kactivate_"),
        "changed_at": changed_at,
        "previous_mode": current,
        "mode": target,
        "transition": transition,
        "actor": actor.strip(),
        "reason": reason.strip(),
        "rollback": target_rank < current_rank,
    }
    _replace_config_mode(root / "config" / "knowledge_system.yml", target)
    atomic_write_json(
        receipts_dir / f"activation_{receipt['receipt_id']}.json",
        receipt,
        ensure_ascii=False,
        indent=2,
    )
    atomic_write_json(receipts_dir / "latest_activation.json", receipt, ensure_ascii=False, indent=2)
    return receipt


def validate_knowledge_stage(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    request_text: str,
    domain: str,
) -> dict:
    """Exercise the configured retrieval stage and persist its evidence gate."""
    root = Path(agentlab_root).resolve()
    config = load_knowledge_config(root)
    if config.mode == "off":
        raise ValueError("off mode cannot be validated as an active knowledge stage")
    prepared = prepare_task(
        KnowledgeTaskRequest(
            agentlab_root=root,
            project=project,
            task_id=task_id,
            request_text=request_text,
            domain=domain,
        )
    )
    validated_at = datetime.now(timezone.utc).isoformat()
    passed = prepared.status == "READY" and bool(prepared.evidence_bundle.items)
    receipt = {
        "status": "PASS" if passed else "FAIL",
        "receipt_id": stable_digest(
            config.mode,
            prepared.context_ref,
            prepared.evidence_bundle.trace.index_snapshot,
            validated_at,
            prefix="kvalidate_",
        ),
        "validated_at": validated_at,
        "mode": config.mode,
        "project": project,
        "task_id": task_id,
        "domain": domain,
        "context_status": prepared.status,
        "context_ref": prepared.context_ref,
        "index_snapshot": prepared.evidence_bundle.trace.index_snapshot,
        "evidence_count": len(prepared.evidence_bundle.items),
        "missing_channels": list(prepared.evidence_bundle.missing_channels),
        "warnings": list(prepared.warnings),
    }
    receipts_dir = root / config.runtime_path / "receipts"
    atomic_write_json(
        receipts_dir / f"validation_{receipt['receipt_id']}.json",
        receipt,
        ensure_ascii=False,
        indent=2,
    )
    atomic_write_json(receipts_dir / "latest_validation.json", receipt, ensure_ascii=False, indent=2)
    return receipt


def _replace_config_mode(path: Path, mode: str) -> None:
    if not path.is_file():
        raise ValueError(f"knowledge config does not exist: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    replaced = False
    for index, line in enumerate(lines):
        if line.startswith("mode:"):
            lines[index] = f"mode: {mode}"
            replaced = True
            break
    if not replaced:
        lines.insert(0, f"mode: {mode}")
    atomic_write_text(path, "\n".join(lines) + "\n")


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}
