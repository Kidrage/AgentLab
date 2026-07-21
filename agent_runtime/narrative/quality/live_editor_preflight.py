"""Provider-free publication of one hash-bound anonymous literary A/B packet."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.narrative.production.live_revision import (
    validate_live_revision_request,
)
from agent_runtime.narrative.production.live_revision_preflight import (
    _mapping,
    _safe_spec_path,
)
from agent_runtime.narrative.production.live_writer_preflight import (
    _tree_digest,
    _verified_ref,
)
from agent_runtime.narrative.quality.live_editor import (
    LITERARY_EDITOR_DIMENSIONS,
)


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_AUDIT_CHECKS = {
    "v2_required_artifacts",
    "v2_artifact_snapshot_stable",
    "session_identity_and_request_hash",
    "output_contract_and_hash",
    "prose_length_contract",
    "draft_is_prose_only",
    "production_manuscript_not_modified",
}


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _ref(root: Path, path: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": _sha256(path.read_bytes()),
    }


def _request_reference_paths(root: Path, request: Mapping[str, Any]) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for key in (
        "source_writer_request",
        "source_candidate",
        "triggering_audit",
        "revision_contract",
        "attempt_receipt",
    ):
        paths[key] = _verified_ref(root, request.get(key))
    return paths


def _validated_output_contract(
    run_dir: Path,
    *,
    task_id: str,
    prose_sha256: str,
) -> dict[str, Any]:
    path = run_dir / "writer_v2_output_contract.yml"
    value = _mapping(path.read_bytes(), "literary_ab_output_contract_invalid")
    expected = {
        "schema_version": 1,
        "status": "pass",
        "task_id": task_id,
        "candidate_only": True,
        "production_modified": False,
        "prose_sha256": prose_sha256,
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise ValueError("literary_ab_output_contract_mismatch")
    return value


def _validated_deterministic_audit(
    audit: Mapping[str, Any],
    *,
    project: str,
    revised_task_id: str,
    revised_sha256: str,
) -> dict[str, Any]:
    if (
        audit.get("schema_version") != 1
        or isinstance(audit.get("schema_version"), bool)
        or audit.get("contract_version") != 2
        or isinstance(audit.get("contract_version"), bool)
        or audit.get("project") != project
        or audit.get("task_id") != revised_task_id
        or audit.get("candidate_sha256") != revised_sha256
        or audit.get("status") != "pass"
    ):
        raise ValueError("literary_ab_deterministic_audit_mismatch")
    checks = audit.get("checks")
    if not isinstance(checks, list):
        raise ValueError("literary_ab_deterministic_audit_incomplete")
    indexed = {
        item.get("id"): item
        for item in checks
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    if not _AUDIT_CHECKS <= set(indexed) or any(
        indexed[name].get("status") != "pass" for name in _AUDIT_CHECKS
    ):
        raise ValueError("literary_ab_deterministic_audit_incomplete")
    return dict(audit)


def _blind_mapping(
    *,
    pair_id: str,
    original_sha256: str,
    revised_sha256: str,
) -> dict[str, str]:
    order = hashlib.sha256(
        f"{pair_id}:{original_sha256}:{revised_sha256}".encode("utf-8")
    ).digest()[0]
    if order % 2:
        return {"A": original_sha256, "B": revised_sha256}
    return {"A": revised_sha256, "B": original_sha256}


def _context_sources(root: Path, request: Mapping[str, Any]) -> list[Path]:
    refs: list[Any] = [
        request.get("writer_input_manifest"),
        request.get("creative_brief_source"),
        request.get("canon_snapshot"),
        request.get("hard_state"),
        request.get("predecessor_prose"),
        request.get("literary_memory"),
        *(request.get("supplemental_context_sources") or []),
    ]
    paths: list[Path] = []
    seen_hashes: set[str] = set()
    for raw_ref in refs:
        path = _verified_ref(root, raw_ref)
        digest = _sha256(path.read_bytes())
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        paths.append(path)
    return paths


def _editor_context(
    *,
    chapter_id: int,
    pair_id: str,
    context_sources: list[Path],
    manuscripts: Mapping[str, str],
) -> str:
    dimensions = "\n".join(f"- {name}" for name in LITERARY_EDITOR_DIMENSIONS)
    sections = [
        "# Independent Literary Editor Packet",
        "",
        f"- Chapter: {chapter_id}",
        f"- Pair ID: {pair_id}",
        "- Boundary: candidate-only; no rewrite; no state projection; no Production write",
        "- Manuscript provenance is intentionally hidden. Judge only A/B.",
        "",
        "## Required dimensions",
        "",
        dimensions,
        "",
        "Use 1-2=blocking, 3=warn, 4-5=pass. For rhetorical_fatigue and "
        "explanation_density, higher means better control and less report-like prose.",
        "Every dimension needs a scene and exact locator. Compare causality, strategy, "
        "agency, tension, curiosity and reading momentum; do not infer which manuscript "
        "is newer. A tie is valid.",
    ]
    for index, path in enumerate(context_sources, start=1):
        sections.extend(
            [
                "",
                f"## Story Context {index:02d}",
                "",
                path.read_text(encoding="utf-8", errors="replace").rstrip(),
            ]
        )
    for label in ("A", "B"):
        sections.extend(
            [
                "",
                f"## Manuscript {label}",
                "",
                manuscripts[label].rstrip(),
            ]
        )
    return "\n".join(sections).rstrip() + "\n"


def preflight_literary_ab_review(
    spec_path: Path,
    *,
    repository_root: Path,
    deterministic_audit_rebuilder: Callable[[Path, str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Publish an exact anonymous packet without calling a provider."""
    root = Path(repository_root).resolve()
    safe_spec = _safe_spec_path(root, Path(spec_path))
    spec_raw = safe_spec.read_bytes()
    spec = _mapping(spec_raw, "literary_ab_spec_invalid")
    project = str(spec.get("project") or "")
    task_id = str(spec.get("task_id") or "")
    original_run_id = str(spec.get("original_run_id") or "")
    revised_run_id = str(spec.get("revised_run_id") or "")
    pair_id = str(spec.get("pair_id") or "")
    chapter_id = spec.get("chapter_id")
    for key, value in {
        "project": project,
        "task_id": task_id,
        "original_run_id": original_run_id,
        "revised_run_id": revised_run_id,
        "pair_id": pair_id,
    }.items():
        if not _IDENTIFIER_RE.fullmatch(value):
            raise ValueError(f"literary_ab_invalid_identity:{key}")
    if isinstance(chapter_id, bool) or not isinstance(chapter_id, int) or chapter_id < 1:
        raise ValueError("literary_ab_invalid_chapter_id")
    if (
        spec.get("schema_version") != 1
        or isinstance(spec.get("schema_version"), bool)
        or spec.get("job_kind") != "narrative_audit"
        or spec.get("run_mode") != "independent_reaudit"
        or spec.get("candidate_only") is not True
        or spec.get("production_modified") is not False
        or spec.get("external_context_approval_required") is not True
        or spec.get("review_model_route") != "NarrativeEditor"
    ):
        raise ValueError("literary_ab_spec_identity_mismatch")
    if original_run_id == revised_run_id or task_id in {original_run_id, revised_run_id}:
        raise ValueError("literary_ab_runs_must_be_distinct")

    project_root = root / "projects" / project
    original_run = project_root / "runs" / original_run_id
    revised_run = project_root / "runs" / revised_run_id
    original_request_path = original_run / "narrative_v2_writer_request.yml"
    revised_request_path = revised_run / "narrative_v2_writer_request.yml"
    original_request = _mapping(
        original_request_path.read_bytes(), "literary_ab_original_request_invalid"
    )
    revised_request = _mapping(
        revised_request_path.read_bytes(), "literary_ab_revised_request_invalid"
    )
    if any(
        original_request.get(key) != value
        for key, value in {
            "schema_version": 1,
            "job_kind": "narrative_generation",
            "run_mode": "generate_candidate",
            "project": project,
            "task_id": original_run_id,
            "chapter_id": chapter_id,
            "candidate_only": True,
            "production_modified": False,
        }.items()
    ):
        raise ValueError("literary_ab_original_request_identity_mismatch")
    if revised_request.get("source_run_id") != original_run_id:
        raise ValueError("literary_ab_revision_source_mismatch")
    revision_paths = _request_reference_paths(root, revised_request)
    _contract, revision_issues = validate_live_revision_request(
        root=root,
        project=project,
        task_id=revised_run_id,
        chapter_id=chapter_id,
        request=revised_request,
        paths=revision_paths,
    )
    if revision_issues:
        raise ValueError("literary_ab_revision_invalid:" + ",".join(revision_issues))

    original_path = original_run / "fiction_draft.md"
    revised_path = revised_run / "fiction_draft.md"
    original_raw = original_path.read_bytes()
    revised_raw = revised_path.read_bytes()
    original_sha256 = _sha256(original_raw)
    revised_sha256 = _sha256(revised_raw)
    if original_sha256 == revised_sha256:
        raise ValueError("literary_ab_candidates_identical")
    if revised_request.get("source_candidate", {}).get("sha256") != original_sha256:
        raise ValueError("literary_ab_original_hash_mismatch")
    _validated_output_contract(
        original_run,
        task_id=original_run_id,
        prose_sha256=original_sha256,
    )
    _validated_output_contract(
        revised_run,
        task_id=revised_run_id,
        prose_sha256=revised_sha256,
    )

    audit_path = _verified_ref(root, spec.get("deterministic_audit"))
    audit = _mapping(audit_path.read_bytes(), "literary_ab_deterministic_audit_invalid")
    if deterministic_audit_rebuilder is not None:
        rebuilt = deterministic_audit_rebuilder(root, revised_run_id)
        if not isinstance(rebuilt, Mapping):
            raise ValueError("literary_ab_deterministic_rebuild_invalid")
        if dict(rebuilt) != audit:
            raise ValueError("literary_ab_deterministic_audit_stale")
    _validated_deterministic_audit(
        audit,
        project=project,
        revised_task_id=revised_run_id,
        revised_sha256=revised_sha256,
    )

    mapping = _blind_mapping(
        pair_id=pair_id,
        original_sha256=original_sha256,
        revised_sha256=revised_sha256,
    )
    prose_by_hash = {
        original_sha256: original_raw.decode("utf-8"),
        revised_sha256: revised_raw.decode("utf-8"),
    }
    context_sources = _context_sources(root, revised_request)
    context = _editor_context(
        chapter_id=chapter_id,
        pair_id=pair_id,
        context_sources=context_sources,
        manuscripts={label: prose_by_hash[digest] for label, digest in mapping.items()},
    )
    production_digest = _tree_digest(project_root / "production")
    run_dir = project_root / "runs" / task_id
    if run_dir.exists():
        raise ValueError("literary_ab_run_already_exists")
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        request_text = (
            f"独立审计长篇小说第 {chapter_id} 章匿名候选稿 A/B。"
            "这是 narrative_audit / independent_reaudit，只做文学评分和盲选；"
            "不得重写正文、推断新旧版本、更新状态或写入 Production。"
        )
        atomic_write_text(run_dir / "user_request.md", request_text + "\n")
        atomic_write_text(run_dir / "narrative_audit_context.md", context)
        atomic_write_yaml(run_dir / "brain_decisions.yml", {"decisions": []})
        atomic_write_yaml(run_dir / "cost_ledger.yml", {"entries": []})
        atomic_write_yaml(
            run_dir / "mission_contract.yml",
            {
                "schema_version": 1,
                "job_kind": "narrative_audit",
                "run_mode": "independent_reaudit",
                "project": project,
                "task_id": task_id,
                "chapter_id": chapter_id,
                "candidate_only": True,
                "production_modified": False,
            },
        )
        mapping_payload = {
            "schema_version": 1,
            "status": "sealed_until_judge_completed",
            "pair_id": pair_id,
            "mapping": {
                label: {
                    "candidate_sha256": digest,
                    "source_run_id": (
                        original_run_id if digest == original_sha256 else revised_run_id
                    ),
                }
                for label, digest in mapping.items()
            },
        }
        atomic_write_yaml(run_dir / "blind_mapping.yml", mapping_payload)
        mapping_sha256 = _sha256(
            json.dumps(mapping, sort_keys=True).encode("utf-8")
        )
        manifest = {
            "schema_version": 1,
            "report_type": "agentlab_narrative_literary_ab_preflight",
            "status": "ready",
            "job_kind": "narrative_audit",
            "run_mode": "independent_reaudit",
            "project": project,
            "task_id": task_id,
            "chapter_id": chapter_id,
            "pair_id": pair_id,
            "candidate_only": True,
            "production_modified": False,
            "external_context_approval_required": True,
            "review_model_route": "NarrativeEditor",
            "original_run_id": original_run_id,
            "revised_run_id": revised_run_id,
            "original_sha256": original_sha256,
            "revised_sha256": revised_sha256,
            "automatic_rewrite_number": revised_request["automatic_rewrite_number"],
            "deterministic_audit": _ref(root, audit_path),
            "preflight_spec": _ref(root, safe_spec),
            "context_sources": [_ref(root, path) for path in context_sources],
            "context_sha256": _sha256(context.encode("utf-8")),
            "blind_mapping_sha256": mapping_sha256,
            "production_digest": production_digest,
            "provider_calls": 0,
        }
        atomic_write_yaml(run_dir / "narrative_audit_manifest.yml", manifest)
        atomic_write_yaml(
            run_dir / "narrative_heavy_audit_reviewer_output_contract.yml",
            {
                "schema_version": 1,
                "status": "ready",
                "structured_output": "narrative_literary_ab",
                "pair_id": pair_id,
                "candidate_only": True,
                "production_modified": False,
            },
        )
    except Exception:
        shutil.rmtree(run_dir)
        raise
    if _tree_digest(project_root / "production") != production_digest:
        shutil.rmtree(run_dir)
        raise ValueError("production_changed_during_literary_ab_preflight")
    return {
        **manifest,
        "run_dir": str(run_dir),
        "manifest_path": str(run_dir / "narrative_audit_manifest.yml"),
        "context_path": str(run_dir / "narrative_audit_context.md"),
        "mapping_path": str(run_dir / "blind_mapping.yml"),
    }
