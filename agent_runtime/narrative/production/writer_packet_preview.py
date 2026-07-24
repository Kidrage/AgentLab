"""Provider-free Writer packet preview backed by a compiled context bundle."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from agent_runtime.cli_executor import _task_packet_payload

from agent_runtime.narrative.production.context_compiler import (
    ContextCompiler,
    ContextRequest,
)


@dataclass
class WriterPacketPreview:
    chapter_id: int
    status: str
    payload: dict[str, Any] | None = None
    payload_json: str = ""
    payload_bytes: int = 0
    token_estimate: int = 0
    loaded_file_count: int = 0
    loaded_context_bytes: int = 0
    duplicate_context_ratio: float = 0.0
    context_bundle_id: str = ""
    context_manifest_path: str = ""
    context_manifest_sha256: str = ""
    issues: list[str] = field(default_factory=list)
    candidate_only: bool = True
    production_modified: bool = False


def build_writer_packet_preview(
    request: ContextRequest,
    *,
    project: str,
    task_id: str,
) -> WriterPacketPreview:
    """Render a schema-v2 sealed Writer payload without running a provider."""
    source_root = Path(request.source_root or Path.cwd()).resolve()
    output_dir = Path(request.output_dir or (source_root / "bundles")).resolve()
    project_ref = Path(project)
    if project_ref.name != project or project_ref.is_absolute():
        return WriterPacketPreview(
            chapter_id=request.chapter_id,
            status="blocked",
            issues=["preview_project_name_is_invalid"],
        )
    if _is_any_project_production_path(output_dir):
        return WriterPacketPreview(
            chapter_id=request.chapter_id,
            status="blocked",
            issues=["preview_output_dir_is_production"],
        )
    project_root = (
        source_root
        if source_root.name == project and source_root.parent.name == "projects"
        else source_root / "projects" / project
    ).resolve()
    production_root = (project_root / "production").resolve()
    if output_dir == production_root or production_root in output_dir.parents:
        return WriterPacketPreview(
            chapter_id=request.chapter_id,
            status="blocked",
            issues=["preview_output_dir_is_production"],
        )

    compiled = ContextCompiler.compile(request)
    if compiled.status != "pass":
        return WriterPacketPreview(
            chapter_id=request.chapter_id,
            status="blocked",
            issues=list(compiled.issues),
        )

    records = list(compiled.shared_files)
    records.extend(compiled.role_specific_files.get("Writer") or [])
    writer_context_bytes = sum(int(record.get("bytes") or 0) for record in records)
    writer_duplicate_ratio = _writer_duplicate_ratio(request, source_root, records)
    sections: list[str] = []
    issues: list[str] = []
    for record in records:
        rendered = _render_record(source_root, record, issues)
        if rendered is not None:
            sections.append(rendered)
    if issues:
        return WriterPacketPreview(
            chapter_id=request.chapter_id,
            status="blocked",
            context_bundle_id=compiled.context_bundle_id,
            context_manifest_path=compiled.manifest_path,
            context_manifest_sha256=compiled.manifest_sha256,
            issues=issues,
        )

    brief = _portable_brief(request, source_root, issues)
    if issues:
        return WriterPacketPreview(
            chapter_id=request.chapter_id,
            status="blocked",
            context_bundle_id=compiled.context_bundle_id,
            context_manifest_path=compiled.manifest_path,
            context_manifest_sha256=compiled.manifest_sha256,
            issues=issues,
        )

    context_receipt = {
        "context_bundle_id": compiled.context_bundle_id,
        "manifest_sha256": compiled.manifest_sha256,
        "loaded_file_count": len(records),
        "loaded_context_bytes": writer_context_bytes,
        "duplicate_context_ratio": writer_duplicate_ratio,
    }
    messages = [
        {
            "role": "system",
            "content": (
                "Act only as the prose Writer for this chapter. Preserve the "
                "CreativeBrief and supplied canon/state facts. Facts absent from "
                "the sealed evidence remain unknown and must not be invented. "
                "Apply fact_invention_policy literally: only transient scene "
                "texture is creative freedom; never create persistent backstory, "
                "institutions, rules, classifications, debts, resources, or "
                "relationships without sealed evidence. "
                "Treat must_not_repeat and forbidden_facts as hard prohibitions. "
                "Supporting-actor state is causal guidance, not permission to "
                "enter another character's mind; preserve the declared POV and "
                "show hidden motives only through observable evidence. "
                "Return exactly one fiction_draft.md prose candidate containing "
                "only a chapter title and fiction prose; do not emit reader "
                "questions, author notes, reports, audits, state ledgers, "
                "promotion decisions, or workspace edits. Use readable paragraph "
                "breaks instead of a few oversized paragraphs."
            ),
        },
        {
            "role": "user",
            "content": (
                "Write one candidate-only chapter from the CreativeBrief and "
                "sealed context below. Facts not present remain unknown.\n\n"
                "## CreativeBrief\n\n"
                + yaml.safe_dump(brief, sort_keys=False, allow_unicode=True).strip()
                + "\n\n## Context bundle receipt\n\n"
                + yaml.safe_dump(
                    context_receipt,
                    sort_keys=False,
                    allow_unicode=True,
                ).strip()
                + "\n\n"
                + "\n\n".join(sections)
            ),
        },
    ]
    plan = SimpleNamespace(
        included_agents={"Writer": {"required_outputs": ["fiction_draft.md"]}},
        project=project,
        task_id=task_id,
        execution_backend="narrative_candidate_preview",
        budget_mode="preview_only",
        risk_level="candidate_only",
    )
    payload = _task_packet_payload("Writer", plan, sealed_messages=messages)
    payload_json = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    payload_bytes = len(payload_json.encode("utf-8"))
    return WriterPacketPreview(
        chapter_id=request.chapter_id,
        status="pass",
        payload=payload,
        payload_json=payload_json,
        payload_bytes=payload_bytes,
        token_estimate=(payload_bytes + 3) // 4,
        loaded_file_count=len(records),
        loaded_context_bytes=writer_context_bytes,
        duplicate_context_ratio=writer_duplicate_ratio,
        context_bundle_id=compiled.context_bundle_id,
        context_manifest_path=compiled.manifest_path,
        context_manifest_sha256=compiled.manifest_sha256,
    )


def _render_record(
    source_root: Path,
    record: dict[str, Any],
    issues: list[str],
) -> str | None:
    relative = Path(str(record.get("path") or ""))
    try:
        resolved = (source_root / relative).resolve()
        resolved.relative_to(source_root)
    except (OSError, ValueError):
        issues.append(f"context_source_outside_root:{relative.as_posix()}")
        return None
    try:
        raw = resolved.read_bytes()
    except OSError:
        issues.append(f"context_source_unreadable:{relative.as_posix()}")
        return None
    observed_hash = hashlib.sha256(raw).hexdigest()
    if observed_hash != str(record.get("sha256") or ""):
        issues.append(f"context_source_hash_changed:{relative.as_posix()}")
        return None
    if len(raw) != int(record.get("bytes") or -1):
        issues.append(f"context_source_size_changed:{relative.as_posix()}")
        return None
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        issues.append(f"context_source_not_utf8:{relative.as_posix()}")
        return None
    return (
        f"## {relative.as_posix()}\n"
        f"sha256: {observed_hash}\n\n"
        f"{content.rstrip()}"
    )


def _portable_brief(
    request: ContextRequest,
    source_root: Path,
    issues: list[str],
) -> dict[str, Any]:
    brief = request.creative_brief.to_dict()
    portable_hashes: dict[str, str] = {}
    for raw_path, digest in request.creative_brief.source_hashes.items():
        try:
            relative = Path(raw_path).resolve().relative_to(source_root)
        except (OSError, ValueError):
            issues.append(f"creative_brief_source_outside_root:{raw_path}")
            continue
        portable_hashes[relative.as_posix()] = digest
    brief["source_hashes"] = portable_hashes
    return brief


def _is_any_project_production_path(path: Path) -> bool:
    parts = path.resolve().parts
    return any(
        parts[index] == "projects" and parts[index + 2] == "production"
        for index in range(max(0, len(parts) - 2))
    )


def _writer_duplicate_ratio(
    request: ContextRequest,
    source_root: Path,
    records: list[dict[str, Any]],
) -> float:
    requested: list[Path] = [
        request.canon_snapshot_path,
        request.hard_state_path,
    ]
    if request.predecessor_prose_path is not None:
        requested.append(request.predecessor_prose_path)
    requested.extend(Path(path) for path in request.creative_brief.source_hashes)
    requested.extend(request.voice_memory_paths)
    requested.extend(request.life_debt_paths)
    requested.extend(request.pattern_signal_paths)
    requested.extend(request.reader_question_paths)
    requested.extend(request.role_slices.get("Writer") or [])

    resolved_requested = [Path(path).resolve() for path in requested]
    naive_bytes = sum(path.stat().st_size for path in resolved_requested if path.is_file())
    requested_set = set(resolved_requested)
    unique_bytes = sum(path.stat().st_size for path in requested_set if path.is_file())

    for record in records:
        record_path = (source_root / str(record.get("path") or "")).resolve()
        if record_path not in requested_set:
            record_bytes = int(record.get("bytes") or 0)
            naive_bytes += record_bytes
            unique_bytes += record_bytes
    if naive_bytes <= 0:
        return 0.0
    return round((naive_bytes - unique_bytes) / naive_bytes, 6)
