"""Reproduce provider-free Writer packet measurements from a hash-bound spec."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from statistics import median
from typing import Any

import yaml

from agent_runtime.atomic_io import atomic_write_text
from agent_runtime.narrative.production.brief_compiler import BriefCompiler
from agent_runtime.narrative.production.context_compiler import ContextRequest
from agent_runtime.narrative.production.writer_packet_preview import (
    build_writer_packet_preview,
)


def measure_frozen_writer_packets(
    manifest_path: Path,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Return exact packet metrics and create only deterministic candidate inputs."""
    repository_root = repository_root.resolve()
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if not isinstance(manifest, dict):
        raise ValueError("measurement_manifest_root_must_be_mapping")
    project = str(manifest.get("project") or "").strip()
    if not project or Path(project).name != project:
        raise ValueError("measurement_project_name_is_invalid")
    if manifest.get("candidate_only") is not True:
        raise ValueError("measurement_must_be_candidate_only")

    candidate_root = (repository_root / "projects" / project / "candidates").resolve()
    derived_dir = _resolved_input_path(
        repository_root,
        {"path": manifest.get("derived_candidate_dir")},
        require_hash=False,
    )
    if derived_dir != candidate_root and candidate_root not in derived_dir.parents:
        raise ValueError("derived_inputs_must_stay_under_project_candidates")
    derived_dir.mkdir(parents=True, exist_ok=True)

    source_plan_ref = _verified_ref(repository_root, manifest.get("source_plan"))
    source_plan = yaml.safe_load(source_plan_ref.read_text(encoding="utf-8")) or {}
    if not isinstance(source_plan, dict):
        raise ValueError("source_plan_root_must_be_mapping")
    chapter_rows = source_plan.get("chapter_state_plan") or []
    if not isinstance(chapter_rows, list):
        raise ValueError("source_plan_chapter_state_plan_must_be_list")

    canon_path = _verified_ref(repository_root, manifest.get("canon_snapshot"))
    shared_memory_paths = [
        _verified_ref(repository_root, ref)
        for ref in manifest.get("shared_memory_sources") or []
    ]
    writer_private_paths = [
        _verified_ref(repository_root, ref)
        for ref in manifest.get("writer_private_sources") or []
    ]
    source_plan_sha256 = _sha256(source_plan_ref)
    target_range = source_plan.get("target_character_range")
    hard_range = source_plan.get("hard_character_range")

    rows: list[dict[str, Any]] = []
    derived_sources: list[dict[str, Any]] = []
    for chapter_input in manifest.get("chapter_inputs") or []:
        if not isinstance(chapter_input, dict):
            raise ValueError("chapter_input_must_be_mapping")
        chapter_id = int(chapter_input.get("chapter_id") or 0)
        matches = [
            row for row in chapter_rows
            if isinstance(row, dict) and int(row.get("chapter") or 0) == chapter_id
        ]
        if len(matches) != 1:
            raise ValueError(f"chapter_selector_must_match_once:{chapter_id}")
        projected = copy.deepcopy(matches[0])
        if target_range is not None:
            projected["target_character_range"] = copy.deepcopy(target_range)
        if hard_range is not None:
            projected["hard_character_range"] = copy.deepcopy(hard_range)
        fragment_path = derived_dir / f"creative_brief_source_ch{chapter_id:03d}.yml"
        fragment_bytes = yaml.safe_dump(
            projected,
            sort_keys=False,
            allow_unicode=True,
        ).encode("utf-8")
        if fragment_path.is_symlink():
            raise ValueError(f"derived_source_must_not_be_symlink:{chapter_id}")
        atomic_write_text(fragment_path, fragment_bytes.decode("utf-8"))
        fragment_sha256 = hashlib.sha256(fragment_bytes).hexdigest()
        derived_sources.append(
            {
                "chapter_id": chapter_id,
                "selector": f"chapter_state_plan[chapter={chapter_id}]",
                "inherits_root_fields": [
                    "target_character_range",
                    "hard_character_range",
                ],
                "path": fragment_path.relative_to(repository_root).as_posix(),
                "bytes": len(fragment_bytes),
                "sha256": fragment_sha256,
            }
        )

        brief = BriefCompiler.from_v1_state_plan(
            projected,
            chapter_id=chapter_id,
            source_paths=[str(fragment_path)],
        )
        predecessor = _verified_ref(
            repository_root, chapter_input.get("predecessor_prose")
        )
        hard_state = _verified_ref(repository_root, chapter_input.get("hard_state"))
        preview = build_writer_packet_preview(
            ContextRequest(
                chapter_id=chapter_id,
                creative_brief=brief,
                canon_snapshot_path=canon_path,
                hard_state_path=hard_state,
                predecessor_prose_path=predecessor,
                predecessor_chapter_id=chapter_id - 1,
                predecessor_prose_sha256=_sha256(predecessor),
                voice_memory_paths=shared_memory_paths,
                role_slices={"Writer": writer_private_paths},
                output_dir=derived_dir / "context_bundles" / f"ch{chapter_id:03d}",
                source_root=repository_root,
            ),
            project=project,
            task_id=f"phase2r_node_b_ch{chapter_id:03d}_preview",
        )
        if preview.status != "pass" or preview.payload is None:
            raise ValueError(
                f"writer_packet_preview_blocked:{chapter_id}:{','.join(preview.issues)}"
            )
        rows.append(
            {
                "chapter_id": chapter_id,
                "payload_bytes": preview.payload_bytes,
                "payload_sha256": hashlib.sha256(
                    preview.payload_json.encode("utf-8")
                ).hexdigest(),
                "token_estimate": preview.token_estimate,
                "loaded_file_count": preview.loaded_file_count,
                "loaded_context_bytes": preview.loaded_context_bytes,
                "duplicate_context_ratio": preview.duplicate_context_ratio,
                "context_bundle_id": preview.context_bundle_id,
                "context_manifest_path": Path(preview.context_manifest_path)
                .resolve()
                .relative_to(repository_root)
                .as_posix(),
                "context_manifest_sha256": preview.context_manifest_sha256,
                "word_count_target": list(brief.word_count_target or []),
            }
        )

    legacy = _load_legacy_medians(
        repository_root,
        manifest.get("legacy_baseline_sources") or [],
    )
    medians = {
        "payload_bytes": int(median(row["payload_bytes"] for row in rows)),
        "token_estimate": int(median(row["token_estimate"] for row in rows)),
        "loaded_file_count": int(median(row["loaded_file_count"] for row in rows)),
        "loaded_context_bytes": int(
            median(row["loaded_context_bytes"] for row in rows)
        ),
    }
    reductions = {
        "payload_bytes": _reduction(legacy.get("payload_bytes"), medians["payload_bytes"]),
        "file_count": _reduction(
            legacy.get("inventory_files"), medians["loaded_file_count"]
        ),
        "context_bytes": _reduction(
            legacy.get("inventory_bytes"), medians["loaded_context_bytes"]
        ),
    }
    return {
        "schema_version": 2,
        "measurement_id": manifest.get("freeze_id"),
        "source_plan_sha256": source_plan_sha256,
        "provider_calls": 0,
        "production_writes": 0,
        "candidate_only": True,
        "packet_contract": "agentlab_sealed_role_session_v2_preview",
        "rows": rows,
        "derived_sources": derived_sources,
        "medians": medians,
        "legacy_medians": legacy,
        "reductions_percent": reductions,
        "target": {
            "ordinary_input_context_median_reduction_percent": 25,
            "input_contract_evaluated": True,
            "input_contract_met": reductions["payload_bytes"] >= 25.0,
            "quality_preserving_evaluated": False,
            "phase_acceptance_met": False,
        },
        "checks": {
            "word_count_contract_present": all(row["word_count_target"] for row in rows),
            "writer_template_present": any(
                path.name == "writer.md" for path in writer_private_paths
            ),
            "provider_execution_requested": False,
            "production_modified": False,
        },
    }


def _resolved_input_path(
    repository_root: Path,
    ref: Any,
    *,
    require_hash: bool,
) -> Path:
    if not isinstance(ref, dict):
        raise ValueError("input_reference_must_be_mapping")
    raw_path = str(ref.get("path") or "").strip()
    if not raw_path or Path(raw_path).is_absolute():
        raise ValueError("input_reference_path_must_be_repository_relative")
    path = (repository_root / raw_path).resolve()
    try:
        path.relative_to(repository_root)
    except ValueError as exc:
        raise ValueError("input_reference_outside_repository") from exc
    if require_hash and not str(ref.get("sha256") or ""):
        raise ValueError(f"input_reference_hash_missing:{raw_path}")
    return path


def _verified_ref(repository_root: Path, ref: Any) -> Path:
    path = _resolved_input_path(repository_root, ref, require_hash=True)
    if not path.is_file():
        raise ValueError(f"input_reference_missing:{path.relative_to(repository_root)}")
    expected = str(ref.get("sha256"))
    observed = _sha256(path)
    if observed != expected:
        raise ValueError(
            f"input_reference_hash_mismatch:{path.relative_to(repository_root)}"
        )
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_legacy_medians(
    repository_root: Path,
    refs: list[Any],
) -> dict[str, int]:
    rows: list[dict[str, int]] = []
    for ref in refs:
        path = _verified_ref(repository_root, ref)
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        try:
            inventory = payload["source_inventory"]
            rows.append(
                {
                    "payload_bytes": int(payload["payload"]["bytes"]),
                    "inventory_files": int(inventory["count"]),
                    "inventory_bytes": sum(
                        int(item["bytes"]) for item in inventory["files"]
                    ),
                }
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"legacy_manifest_contract_invalid:{path}") from exc
    if not rows:
        raise ValueError("legacy_baseline_sources_are_required")
    return {
        key: int(median(row[key] for row in rows))
        for key in ("payload_bytes", "inventory_files", "inventory_bytes")
    }


def _reduction(baseline: Any, current: int) -> float:
    baseline_int = int(baseline or 0)
    if baseline_int <= 0:
        raise ValueError("legacy_median_must_be_positive")
    return round((baseline_int - current) * 100.0 / baseline_int, 4)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--repository-root", type=Path, required=True)
    args = parser.parse_args()
    result = measure_frozen_writer_packets(
        args.manifest,
        repository_root=args.repository_root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
