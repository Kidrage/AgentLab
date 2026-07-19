"""Fail-closed, hash-bound, atomic narrative Candidate Set promotion."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Any, Mapping

from agent_runtime.atomic_io import atomic_write_yaml, safe_read_yaml
from agent_runtime.narrative.candidates.manifest import validate_candidate_set


_PASS = {"pass", "passed", "completed", "accepted"}


def _load_mapping(path: Path, *, label: str) -> dict[str, Any]:
    value = safe_read_yaml(path, default=None)
    if not isinstance(value, dict):
        raise ValueError(f"{label} is missing or invalid")
    return value


def _validate_receipt(
    project_root: Path,
    path_value: str,
    *,
    candidate_set_sha256: str,
    artifact_sha256: str,
    label: str,
) -> None:
    root = Path(project_root).resolve()
    path = (root / path_value).resolve()
    path.relative_to(root)
    receipt = _load_mapping(path, label=label)
    if str(receipt.get("status") or "").lower() not in _PASS:
        raise ValueError(f"{label} did not pass")
    if receipt.get("candidate_set_sha256") != candidate_set_sha256:
        raise ValueError(f"{label} candidate set hash mismatch")
    if receipt.get("artifact_sha256") != artifact_sha256:
        raise ValueError(f"{label} artifact hash mismatch")
    if int(receipt.get("blocking_count") or 0) != 0:
        raise ValueError(f"{label} contains blocking findings")


def promote_candidate_set(
    project_root: Path,
    *,
    manifest_path: Path,
    user_acceptance_receipt: Path,
    edition_id: str,
    release_slot: str,
    promoted_at: str,
) -> dict[str, object]:
    """Stage a complete edition and atomically switch the formal index pointer."""
    root = Path(project_root).resolve()
    manifest = _load_mapping(Path(manifest_path), label="candidate set manifest")
    if manifest.get("status") != "frozen":
        raise ValueError("candidate set must be frozen before promotion")
    validation = validate_candidate_set(root, Path(manifest_path))
    if validation["status"] != "pass":
        raise ValueError("candidate set is stale")
    candidate_set_sha256 = str(manifest.get("candidate_set_sha256") or "")
    if not candidate_set_sha256:
        raise ValueError("candidate set hash is missing")

    approval = _load_mapping(
        Path(user_acceptance_receipt),
        label="user acceptance receipt",
    )
    if str(approval.get("status") or "").lower() != "accepted":
        raise ValueError("user acceptance receipt is not accepted")
    if approval.get("candidate_set_id") != manifest.get("candidate_set_id"):
        raise ValueError("user acceptance candidate set id mismatch")
    if approval.get("candidate_set_sha256") != candidate_set_sha256:
        raise ValueError("stale user acceptance receipt")

    chapters = manifest.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise ValueError("candidate set chapters are missing")
    for record in chapters:
        if not isinstance(record, Mapping):
            raise ValueError("candidate chapter record is invalid")
        if record.get("model_tier") != "final":
            raise ValueError("candidate chapter model tier is not final eligible")
        for field, label in (
            ("generation_receipt", "generation receipt"),
            ("correctness_audit", "correctness audit"),
            ("literary_audit", "literary audit"),
            ("cost_receipt", "cost receipt"),
        ):
            _validate_receipt(
                root,
                str(record.get(field) or ""),
                candidate_set_sha256=candidate_set_sha256,
                artifact_sha256=str(record.get("artifact_sha256") or ""),
                label=f"{label} chapter {record.get('chapter_id')}",
            )

    index_path = root / "project_artifact_index.yml"
    index = safe_read_yaml(index_path, default={}) or {}
    if not isinstance(index, dict):
        raise ValueError("project artifact index is invalid")
    existing_releases = index.get("releases") or []
    for release in existing_releases:
        if not isinstance(release, Mapping):
            continue
        for chapter_id in release.get("chapter_ids") or []:
            if (
                release.get("release_slot") == release_slot
                and release.get("edition_id") == edition_id
                and int(chapter_id) in {int(item["chapter_id"]) for item in chapters}
            ):
                raise ValueError("duplicate release slot, chapter, and edition")

    first_publication = not isinstance(index.get("current_release"), Mapping)
    staging = root / ".promotion_staging" / (
        f"{manifest['candidate_set_id']}-{edition_id}"
    )
    target = root / "production" / "editions" / edition_id
    if staging.exists() or target.exists():
        raise FileExistsError(staging if staging.exists() else target)
    staging.mkdir(parents=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    promoted_chapters: list[dict[str, Any]] = []
    try:
        for record in chapters:
            source = (root / str(record["artifact_path"])).resolve()
            destination = staging / f"chapter_{int(record['chapter_id']):03d}.md"
            shutil.copy2(source, destination)
            if validate_candidate_set(root, Path(manifest_path))["status"] != "pass":
                raise ValueError("candidate changed during promotion staging")
            promoted_chapters.append(
                {
                    "chapter_id": int(record["chapter_id"]),
                    "artifact_path": str(
                        Path("production") / "editions" / edition_id / destination.name
                    ),
                    "artifact_sha256": record["artifact_sha256"],
                }
            )
        promotion_receipt = {
            "schema_version": 1,
            "status": "promoted",
            "promoted_at": promoted_at,
            "candidate_set_id": manifest["candidate_set_id"],
            "candidate_set_sha256": candidate_set_sha256,
            "edition_id": edition_id,
            "release_slot": release_slot,
            "user_acceptance_receipt": str(Path(user_acceptance_receipt)),
            "chapters": promoted_chapters,
            "production_modified": True,
        }
        atomic_write_yaml(staging / "promotion_receipt.yml", promotion_receipt)
        os.replace(staging, target)
        release_record = {
            "release_slot": release_slot,
            "edition_id": edition_id,
            "candidate_set_id": manifest["candidate_set_id"],
            "candidate_set_sha256": candidate_set_sha256,
            "chapter_ids": [int(record["chapter_id"]) for record in chapters],
            "promotion_receipt": str(
                Path("production") / "editions" / edition_id / "promotion_receipt.yml"
            ),
        }
        updated_index = dict(index)
        updated_index["schema_version"] = max(int(index.get("schema_version") or 0), 1)
        updated_index["releases"] = [*existing_releases, release_record]
        updated_index["current_release"] = release_record
        atomic_write_yaml(index_path, updated_index)
    except Exception:
        if target.exists():
            shutil.rmtree(target)
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return {
        "status": "promoted",
        "first_publication": first_publication,
        "edition_id": edition_id,
        "release_slot": release_slot,
        "candidate_set_id": manifest["candidate_set_id"],
        "candidate_set_sha256": candidate_set_sha256,
        "promotion_receipt": str(target / "promotion_receipt.yml"),
        "production_modified": True,
    }
