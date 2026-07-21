"""Provider-free replay for hash-bound live Writer sessions."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from statistics import median
from typing import Any

import yaml

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.narrative.production.live_writer import (
    LIVE_WRITER_REQUEST_NAME,
    prepare_live_writer_session,
)
from agent_runtime.narrative.production.writer_packet_measurement import (
    measure_frozen_writer_packets,
)
from agent_runtime.schemas import AgentRoute, WorkflowPlan


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def preflight_live_writer_sessions(
    spec_path: Path,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Build every declared live session without starting a provider."""
    root = repository_root.resolve()
    lexical_spec = spec_path if spec_path.is_absolute() else root / spec_path
    if _has_symlink_component(root, lexical_spec):
        raise ValueError("live_preflight_spec_outside_root_or_symlinked")
    spec_path = lexical_spec.resolve()
    try:
        spec_path.relative_to(root)
    except ValueError as exc:
        raise ValueError("live_preflight_spec_outside_root_or_symlinked") from exc
    spec = _load_mapping(spec_path)
    if spec.get("candidate_only") is not True:
        raise ValueError("live_preflight_must_be_candidate_only")
    project = str(spec.get("project") or "").strip()
    task_prefix = str(spec.get("task_prefix") or "").strip()
    if not _IDENTIFIER_RE.fullmatch(project):
        raise ValueError("live_preflight_project_invalid")
    if not _IDENTIFIER_RE.fullmatch(task_prefix):
        raise ValueError("live_preflight_task_prefix_invalid")
    writer_manifest_path = _verified_ref(root, spec.get("writer_input_manifest"))
    writer_manifest = _load_mapping(writer_manifest_path)
    if writer_manifest.get("project") != project:
        raise ValueError("live_preflight_writer_manifest_project_mismatch")

    production_root = root / "projects" / project / "production"
    production_before = _tree_digest(production_root)
    preview_metrics = measure_frozen_writer_packets(
        writer_manifest_path,
        repository_root=root,
    )
    derived = {
        int(item["chapter_id"]): {
            "path": item["path"],
            "sha256": item["sha256"],
        }
        for item in preview_metrics.get("derived_sources") or []
    }
    chapter_inputs = {
        int(item["chapter_id"]): item
        for item in writer_manifest.get("chapter_inputs") or []
    }
    memory_refs = {
        int(item["chapter_id"]): item["snapshot"]
        for item in spec.get("literary_memories") or []
    }
    chapters = [int(item) for item in spec.get("chapters") or []]
    if set(chapters) != set(derived) or set(chapters) != set(memory_refs):
        raise ValueError("live_preflight_chapter_set_mismatch")

    rows: list[dict[str, Any]] = []
    for chapter_id in chapters:
        memory = _verified_ref(root, memory_refs[chapter_id])
        chapter_input = chapter_inputs.get(chapter_id)
        if chapter_input is None:
            raise ValueError(f"live_preflight_chapter_input_missing:{chapter_id}")
        task_id = f"{task_prefix}_ch{chapter_id:03d}"
        if not _IDENTIFIER_RE.fullmatch(task_id):
            raise ValueError("live_preflight_task_id_invalid")
        run_dir = _safe_run_dir(root, project, task_id)
        request = {
            "schema_version": 1,
            "job_kind": "narrative_generation",
            "run_mode": "generate_candidate",
            "project": project,
            "task_id": task_id,
            "chapter_id": chapter_id,
            "candidate_only": True,
            "production_modified": False,
            "external_context_approval_required": True,
            "writer_input_manifest": {
                "path": writer_manifest_path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(writer_manifest_path.read_bytes()).hexdigest(),
            },
            "creative_brief_source": derived[chapter_id],
            "canon_snapshot": writer_manifest["canon_snapshot"],
            "hard_state": chapter_input["hard_state"],
            "predecessor_prose": {
                **chapter_input["predecessor_prose"],
                "chapter_id": chapter_id - 1,
            },
            "literary_memory": {
                "path": memory.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(memory.read_bytes()).hexdigest(),
            },
            "supplemental_context_sources": list(
                writer_manifest.get("shared_memory_sources") or []
            ),
            "writer_private_sources": list(
                writer_manifest.get("writer_private_sources") or []
            ),
        }
        request_path = run_dir / LIVE_WRITER_REQUEST_NAME
        atomic_write_yaml(
            request_path,
            request,
            sort_keys=False,
            allow_unicode=True,
        )
        plan = WorkflowPlan(
            project=project,
            task_id=task_id,
            agentlab_root=str(root),
            project_root=str(root / "projects" / project),
            repo_path=str(root / "projects" / project / "repo"),
            run_dir=str(run_dir),
            user_request_path=str(request_path),
            included_agents={"Writer": {"required_outputs": ["fiction_draft.md"]}},
            route=AgentRoute(
                task_size="small",
                route_key="narrative_generation_v2",
                agents=["Writer"],
            ),
            execution_backend="agentlab_orchestrated_cli",
            budget_mode="balanced",
            risk_level="candidate_only",
            model_profiles={},
            execution_policy={"external_context_approval_required": True},
        )
        session = prepare_live_writer_session(root, plan)
        if session is None or session.status != "pass":
            issues = session.issues if session is not None else ["not_activated"]
            raise ValueError(
                f"live_preflight_session_blocked:{chapter_id}:{','.join(issues)}"
            )
        repeated = prepare_live_writer_session(root, plan)
        if repeated is None or repeated.status != "pass":
            repeated_issues = (
                repeated.issues if repeated is not None else ["not_activated"]
            )
            raise ValueError(
                "live_preflight_repeat_session_blocked:"
                f"{chapter_id}:{','.join(repeated_issues)}"
            )
        byte_stable = (
            session.packet_sha256 == repeated.packet_sha256
            and session.packet_bytes == repeated.packet_bytes
            and session.context_manifest_sha256 == repeated.context_manifest_sha256
        )
        rows.append(
            {
                "chapter_id": chapter_id,
                "task_id": task_id,
                "request_path": request_path.relative_to(root).as_posix(),
                "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
                "packet_sha256": session.packet_sha256,
                "repeat_packet_sha256": repeated.packet_sha256,
                "byte_stable_across_two_compiles": byte_stable,
                "packet_bytes": session.packet_bytes,
                "token_estimate": session.token_estimate,
                "loaded_file_count": session.loaded_file_count,
                "loaded_context_bytes": session.loaded_context_bytes,
                "duplicate_context_ratio": session.duplicate_context_ratio,
                "context_bundle_id": session.context_bundle_id,
                "context_manifest_sha256": session.context_manifest_sha256,
                "literary_memory_sha256": session.literary_memory_sha256,
                "literary_memory_occurrences": session.source_paths.count(memory),
                "provider_calls": session.provider_calls,
            }
        )

    legacy = preview_metrics.get("legacy_medians") or {}
    packet_median = int(median(row["packet_bytes"] for row in rows))
    context_median = int(median(row["loaded_context_bytes"] for row in rows))
    production_after = _tree_digest(production_root)
    result = {
        "schema_version": 1,
        "status": "pass",
        "project": project,
        "chapters": chapters,
        "candidate_only": True,
        "production_modified": production_before != production_after,
        "production_digest_before": production_before,
        "production_digest_after": production_after,
        "provider_calls": sum(row["provider_calls"] for row in rows),
        "rows": rows,
        "medians": {
            "packet_bytes": packet_median,
            "loaded_context_bytes": context_median,
        },
        "legacy_medians": legacy,
        "reductions_percent": {
            "packet_bytes": _reduction(legacy.get("payload_bytes"), packet_median),
            "context_bytes": _reduction(
                legacy.get("inventory_bytes"),
                context_median,
            ),
        },
        "checks": {
            "all_sessions_compiled": len(rows) == len(chapters),
            "literary_memory_present_once": all(
                row["literary_memory_occurrences"] == 1 for row in rows
            ),
            "byte_stable_across_two_compiles": all(
                row["byte_stable_across_two_compiles"] for row in rows
            ),
            "provider_execution_requested": False,
            "production_modified": production_before != production_after,
        },
        "quality_boundary": {
            "quality_equivalent_input_contract_complete": True,
            "literary_output_equivalence_proven": False,
            "positive_calibration_status": "missing_user_samples",
            "phase_2r_accepted": False,
            "gate_1_accepted": False,
        },
    }
    if (
        result["provider_calls"] != 0
        or result["production_modified"]
        or not result["checks"]["byte_stable_across_two_compiles"]
    ):
        raise ValueError("live_preflight_safety_invariant_failed")
    return result


def _safe_run_dir(root: Path, project: str, task_id: str) -> Path:
    run_dir = root / "projects" / project / "runs" / task_id
    if _has_symlink_component(root, run_dir):
        raise ValueError("live_preflight_run_dir_symlinked")
    run_dir.mkdir(parents=True, exist_ok=True)
    if _has_symlink_component(root, run_dir):
        raise ValueError("live_preflight_run_dir_symlinked")
    resolved = run_dir.resolve()
    if resolved != run_dir.absolute() or root not in resolved.parents:
        raise ValueError("live_preflight_run_dir_outside_root")
    return resolved


def _verified_ref(root: Path, raw: Any) -> Path:
    if not isinstance(raw, dict):
        raise ValueError("live_preflight_reference_must_be_mapping")
    raw_path = str(raw.get("path") or "").strip()
    expected = str(raw.get("sha256") or "").strip().lower()
    relative = Path(raw_path)
    if not raw_path or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("live_preflight_reference_path_invalid")
    lexical = root / relative
    if _has_symlink_component(root, lexical):
        raise ValueError(f"live_preflight_reference_symlinked:{raw_path}")
    path = lexical.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("live_preflight_reference_outside_root") from exc
    if not path.is_file():
        raise ValueError(f"live_preflight_reference_missing:{raw_path}")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError(f"live_preflight_reference_hash_mismatch:{raw_path}")
    return path


def _load_mapping(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"live_preflight_mapping_required:{path.name}")
    return value


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.is_dir():
        return digest.hexdigest()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _has_symlink_component(root: Path, path: Path) -> bool:
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError:
        return True
    current = root.absolute()
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _reduction(baseline: Any, current: int) -> float:
    try:
        base = int(baseline)
    except (TypeError, ValueError):
        return 0.0
    if base <= 0:
        return 0.0
    return round((base - current) * 100.0 / base, 2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = preflight_live_writer_sessions(
        args.spec,
        repository_root=args.repository_root,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        atomic_write_text(args.output, rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
