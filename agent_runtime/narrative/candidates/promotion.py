"""Fail-closed, hash-bound, atomic narrative Candidate Set promotion."""

from __future__ import annotations

import os
from pathlib import Path
import hashlib
import json
import re
import shutil
from typing import Any, Mapping

from agent_runtime.atomic_io import atomic_write_yaml, safe_read_yaml
from agent_runtime.narrative.candidates.manifest import validate_candidate_set
from agent_runtime.narrative.user_acceptance import (
    validate_candidate_acceptance,
)


_PASS = {"pass", "passed", "completed", "accepted"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _sync_release_knowledge(
    project_root: Path,
    *,
    edition_id: str,
    chapter_ids: list[int],
) -> dict[str, Any]:
    from agent_runtime.knowledge_system import sync_committed

    root = Path(project_root).resolve()
    agentlab_root = root.parent.parent
    project = root.name
    edition_prefix = Path("projects") / project / "release_objects" / "editions" / edition_id
    promoted_paths = [
        (edition_prefix / f"chapter_{chapter_id:03d}.md").as_posix()
        for chapter_id in chapter_ids
    ]
    promoted_paths.extend(
        [
            (edition_prefix / "promotion_receipt.yml").as_posix(),
            (Path("projects") / project / "project_artifact_index.yml").as_posix(),
        ]
    )
    return sync_committed(
        {
            "agentlab_root": agentlab_root,
            "project": project,
            "status": "promoted",
            "domain": "longform_narrative",
            "promoted_paths": promoted_paths,
        }
    ).as_dict()


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
) -> dict[str, Any]:
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
    return receipt


def _validate_crown_runtime_receipt(
    project_root: Path,
    receipt_path: str,
    receipt: Mapping[str, Any],
    *,
    field: str,
    chapter_id: int,
) -> None:
    """Require Crown promotion evidence to originate from verified runtime work."""

    from agent_runtime.task_runtime_v2 import TaskRuntime

    contracts = {
        "generation_receipt": (
            "narrative-generation-receipt/v1",
            "narrative-generation",
            "writer",
            "Writer",
        ),
        "correctness_audit": (
            "narrative-correctness-audit-receipt/v1",
            "narrative-correctness-audit",
            "canon_timeline_steward",
            "Reviewer",
        ),
        "literary_audit": (
            "narrative-literary-audit-receipt/v1",
            "narrative-literary-audit",
            "senior_editor",
            "Reviewer",
        ),
        "cost_receipt": (
            "narrative-cost-receipt/v1",
            "narrative-cost-audit",
            "authorial_director",
            "Supervisor",
        ),
    }
    schema_version, work_kind, agent_id, runtime_role = contracts[field]
    task_id = str(receipt.get("task_id") or "")
    attempt_id = str(receipt.get("attempt_id") or "")
    work_item_id = str(receipt.get("work_item_id") or "")
    if (
        receipt.get("schema_version") != schema_version
        or receipt.get("project") != project_root.name
        or receipt.get("chapter_id") != chapter_id
        or not task_id
        or not attempt_id
        or not work_item_id
    ):
        raise ValueError(f"{field} chapter {chapter_id} contract is invalid")
    runtime = TaskRuntime(
        project_root.parent.parent,
        project=project_root.name,
    )
    verification = runtime.verify_attempt_execution_receipt(
        task_id,
        attempt_id,
    )
    projection = runtime.load_task(task_id)
    attempt = (projection.get("attempts") or {}).get(attempt_id)
    work_item = (projection.get("work_items") or {}).get(work_item_id)
    execution_contract = (
        attempt.get("execution_contract")
        if isinstance(attempt, Mapping)
        else None
    )
    receipt_file = (project_root / receipt_path).resolve(strict=True)
    if (
        verification.get("ok") is not True
        or verification.get("output_sha256")
        != hashlib.sha256(receipt_file.read_bytes()).hexdigest()
        or receipt.get("execution_receipt_sha256")
        != verification.get("receipt_sha256")
        or receipt.get("provider") != verification.get("runtime_provider")
        or receipt.get("model_id") != verification.get("model_id")
        or not isinstance(attempt, Mapping)
        or attempt.get("work_item_id") != work_item_id
        or not isinstance(work_item, Mapping)
        or work_item.get("kind") != work_kind
        or work_item.get("assigned_agent_id") != agent_id
        or not isinstance(execution_contract, Mapping)
        or execution_contract.get("role") != runtime_role
    ):
        raise ValueError(
            f"{field} chapter {chapter_id} runtime evidence is invalid"
        )


def evidence_bundle_sha256(
    project_root: Path,
    manifest: Mapping[str, Any],
) -> str:
    """Hash the exact receipt bytes covered by a user acceptance decision."""
    root = Path(project_root).resolve()
    evidence: list[dict[str, str]] = []
    for record in manifest.get("chapters") or []:
        if not isinstance(record, Mapping):
            raise ValueError("candidate chapter record is invalid")
        for field in (
            "generation_receipt",
            "correctness_audit",
            "literary_audit",
            "cost_receipt",
        ):
            path = (root / str(record.get(field) or "")).resolve()
            path.relative_to(root)
            if not path.is_file():
                raise ValueError(f"missing candidate evidence: {field}")
            evidence.append(
                {
                    "chapter_id": str(record.get("chapter_id")),
                    "field": field,
                    "path": str(path.relative_to(root)),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    return hashlib.sha256(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _safe_child(project_root: Path, *parts: str) -> Path:
    base = Path(project_root).resolve()
    value = base.joinpath(*parts).resolve()
    value.relative_to(base)
    return value


def _staged_edition_matches(
    directory: Path,
    *,
    expected_receipt: Mapping[str, Any],
) -> bool:
    receipt = safe_read_yaml(directory / "promotion_receipt.yml", default=None)
    if not isinstance(receipt, dict) or receipt != dict(expected_receipt):
        return False
    for chapter in expected_receipt.get("chapters") or []:
        if not isinstance(chapter, Mapping):
            return False
        path = directory / f"chapter_{int(chapter['chapter_id']):03d}.md"
        if not path.is_file():
            return False
        if hashlib.sha256(path.read_bytes()).hexdigest() != chapter.get("artifact_sha256"):
            return False
    return True


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
    if not _SAFE_ID.fullmatch(edition_id):
        raise ValueError("invalid edition_id")
    if not _SAFE_ID.fullmatch(release_slot):
        raise ValueError("invalid release_slot")
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
    candidate_set_id = str(manifest.get("candidate_set_id") or "")
    if not _SAFE_ID.fullmatch(candidate_set_id):
        raise ValueError("invalid candidate_set_id")

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
    current_evidence_sha256 = evidence_bundle_sha256(root, manifest)
    approved_evidence_sha256 = approval.get("evidence_bundle_sha256")
    if not approved_evidence_sha256:
        raise ValueError("user acceptance evidence hash is missing")
    if approved_evidence_sha256 != current_evidence_sha256:
        raise ValueError("stale user acceptance evidence")
    validate_candidate_acceptance(
        root,
        Path(user_acceptance_receipt),
        candidate_set_id=candidate_set_id,
        candidate_set_sha256=candidate_set_sha256,
        evidence_bundle_sha256=current_evidence_sha256,
    )

    chapters = manifest.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise ValueError("candidate set chapters are missing")
    artifact_sha256_values = [
        str(record.get("artifact_sha256") or "")
        for record in chapters
        if isinstance(record, Mapping)
    ]
    if (
        len(artifact_sha256_values) != len(chapters)
        or len(set(artifact_sha256_values)) != len(artifact_sha256_values)
    ):
        raise ValueError("candidate chapters must have unique content hashes")
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
            receipt = _validate_receipt(
                root,
                str(record.get(field) or ""),
                candidate_set_sha256=candidate_set_sha256,
                artifact_sha256=str(record.get("artifact_sha256") or ""),
                label=f"{label} chapter {record.get('chapter_id')}",
            )
            if root.name == "Crown_of_Ash":
                _validate_crown_runtime_receipt(
                    root,
                    str(record.get(field) or ""),
                    receipt,
                    field=field,
                    chapter_id=int(record["chapter_id"]),
                )

    index_path = root / "project_artifact_index.yml"
    index = safe_read_yaml(index_path, default={}) or {}
    if not isinstance(index, dict):
        raise ValueError("project artifact index is invalid")
    existing_releases = index.get("releases") or []
    current_release = index.get("current_release")
    if isinstance(current_release, Mapping) and (
        current_release.get("release_slot") == release_slot
        and current_release.get("edition_id") == edition_id
        and current_release.get("candidate_set_id") == candidate_set_id
        and current_release.get("candidate_set_sha256") == candidate_set_sha256
    ):
        result = {
            "status": "promoted",
            "first_publication": False,
            "edition_id": edition_id,
            "release_slot": release_slot,
            "candidate_set_id": candidate_set_id,
            "candidate_set_sha256": candidate_set_sha256,
            "promotion_receipt": str(
                root / "release_objects" / "editions" / edition_id / "promotion_receipt.yml"
            ),
            "production_modified": False,
            "idempotent_replay": True,
        }
        result["knowledge_sync"] = _sync_release_knowledge(
            root,
            edition_id=edition_id,
            chapter_ids=[int(value) for value in current_release.get("chapter_ids") or []],
        )
        return result
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
    staging = _safe_child(
        root,
        ".promotion_staging",
        f"{candidate_set_id}-{edition_id}",
    )
    target = _safe_child(root, "release_objects", "editions", edition_id)
    promoted_chapters = [
        {
            "chapter_id": int(record["chapter_id"]),
            "artifact_path": str(
                Path("release_objects")
                / "editions"
                / edition_id
                / f"chapter_{int(record['chapter_id']):03d}.md"
            ),
            "artifact_sha256": record["artifact_sha256"],
        }
        for record in chapters
    ]
    promotion_receipt = {
        "schema_version": 1,
        "status": "promoted",
        "promoted_at": promoted_at,
        "candidate_set_id": manifest["candidate_set_id"],
        "candidate_set_sha256": candidate_set_sha256,
        "evidence_bundle_sha256": current_evidence_sha256,
        "edition_id": edition_id,
        "release_slot": release_slot,
        "user_acceptance_receipt": str(Path(user_acceptance_receipt)),
        "chapters": promoted_chapters,
        "production_modified": True,
    }
    resumed_target = target.exists()
    if resumed_target and not _staged_edition_matches(
        target,
        expected_receipt=promotion_receipt,
    ):
        raise FileExistsError(target)
    if staging.exists() and not _staged_edition_matches(
        staging,
        expected_receipt=promotion_receipt,
    ):
        raise FileExistsError(staging)
    staging_preexisting = staging.exists()
    staging_created = False
    target_installed = False
    try:
        if not resumed_target:
            if not staging.exists():
                staging.mkdir(parents=True)
                staging_created = True
                for record in chapters:
                    source = (root / str(record["artifact_path"])).resolve()
                    destination = staging / f"chapter_{int(record['chapter_id']):03d}.md"
                    shutil.copy2(source, destination)
                    if validate_candidate_set(root, Path(manifest_path))["status"] != "pass":
                        raise ValueError("candidate changed during promotion staging")
                atomic_write_yaml(staging / "promotion_receipt.yml", promotion_receipt)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, target)
            target_installed = True
        release_record = {
            "release_slot": release_slot,
            "edition_id": edition_id,
            "candidate_set_id": manifest["candidate_set_id"],
            "candidate_set_sha256": candidate_set_sha256,
            "chapter_ids": [int(record["chapter_id"]) for record in chapters],
            "promotion_receipt": str(
                Path("release_objects") / "editions" / edition_id / "promotion_receipt.yml"
            ),
        }
        updated_index = dict(index)
        updated_index["schema_version"] = max(int(index.get("schema_version") or 0), 1)
        updated_index["releases"] = [*existing_releases, release_record]
        updated_index["current_release"] = release_record
        atomic_write_yaml(index_path, updated_index)
    except Exception:
        if target_installed and target.exists():
            if staging_preexisting:
                os.replace(target, staging)
            else:
                shutil.rmtree(target)
        if staging_created and staging.exists():
            shutil.rmtree(staging)
        raise
    result = {
        "status": "promoted",
        "first_publication": first_publication,
        "edition_id": edition_id,
        "release_slot": release_slot,
        "candidate_set_id": manifest["candidate_set_id"],
        "candidate_set_sha256": candidate_set_sha256,
        "promotion_receipt": str(target / "promotion_receipt.yml"),
        "production_modified": True,
    }
    result["knowledge_sync"] = _sync_release_knowledge(
        root,
        edition_id=edition_id,
        chapter_ids=[int(record["chapter_id"]) for record in chapters],
    )
    return result
