"""Content-addressed Candidate Set creation, freezing, and stale detection."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from agent_runtime.atomic_io import atomic_write_yaml, safe_read_yaml


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_REQUIRED_CHAPTER_FIELDS = (
    "chapter_id",
    "artifact_path",
    "source_run_id",
    "source_model",
    "model_tier",
    "context_manifest_sha256",
    "generation_receipt",
    "correctness_audit",
    "literary_audit",
    "cost_receipt",
)


def _artifact(project_root: Path, value: str) -> Path:
    root = Path(project_root).resolve()
    path = (root / value).resolve()
    path.relative_to(root)
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_sha256(manifest: Mapping[str, Any]) -> str:
    content = dict(manifest)
    content.pop("candidate_set_sha256", None)
    return hashlib.sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def create_candidate_set(
    project_root: Path,
    *,
    candidate_set_id: str,
    created_at: str,
    canon_snapshot_sha256: str,
    scorecard_version: int,
    chapters: Iterable[Mapping[str, Any]],
) -> dict[str, object]:
    """Create one draft Candidate Set manifest without touching Production."""
    if not _SAFE_ID.fullmatch(candidate_set_id):
        raise ValueError("invalid candidate_set_id")
    root = Path(project_root).resolve()
    directory = root / "candidates" / "sets" / candidate_set_id
    manifest_path = directory / "candidate_set_manifest.yml"
    if directory.exists():
        raise FileExistsError(directory)
    records: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw in chapters:
        missing = [field for field in _REQUIRED_CHAPTER_FIELDS if raw.get(field) is None]
        if missing:
            raise ValueError("candidate chapter missing fields: " + ",".join(missing))
        chapter_id = int(raw["chapter_id"])
        if chapter_id in seen:
            raise ValueError(f"duplicate candidate chapter: {chapter_id}")
        seen.add(chapter_id)
        artifact = _artifact(root, str(raw["artifact_path"]))
        if not artifact.is_file():
            raise FileNotFoundError(artifact)
        record = dict(raw)
        record["chapter_id"] = chapter_id
        record["artifact_sha256"] = _sha256(artifact)
        records.append(record)
    if not records:
        raise ValueError("candidate set must include at least one chapter")
    manifest: dict[str, Any] = {
        "manifest_version": 1,
        "candidate_set_id": candidate_set_id,
        "created_at": created_at,
        "canon_snapshot_sha256": canon_snapshot_sha256,
        "scorecard_version": int(scorecard_version),
        "candidate_only": True,
        "production_modified": False,
        "chapters": sorted(records, key=lambda item: int(item["chapter_id"])),
        "status": "draft",
    }
    manifest["candidate_set_sha256"] = _manifest_sha256(manifest)
    directory.mkdir(parents=True)
    atomic_write_yaml(manifest_path, manifest)
    return {**manifest, "manifest_path": str(manifest_path)}


def validate_candidate_set(
    project_root: Path,
    manifest_path: Path,
) -> dict[str, object]:
    """Recompute every candidate hash and mark frozen audit evidence stale."""
    manifest = safe_read_yaml(Path(manifest_path), default=None)
    if not isinstance(manifest, dict):
        raise ValueError("candidate set manifest is invalid")
    stale: list[int] = []
    issues: list[str] = []
    for record in manifest.get("chapters") or []:
        chapter_id = int(record.get("chapter_id") or 0)
        try:
            artifact = _artifact(Path(project_root), str(record.get("artifact_path") or ""))
        except ValueError:
            issues.append(f"unsafe_artifact_path:{chapter_id}")
            stale.append(chapter_id)
            continue
        if not artifact.is_file():
            issues.append(f"missing_artifact:{chapter_id}")
            stale.append(chapter_id)
        elif _sha256(artifact) != record.get("artifact_sha256"):
            issues.append(f"artifact_hash_changed:{chapter_id}")
            stale.append(chapter_id)
    expected_manifest_hash = _manifest_sha256(manifest)
    if manifest.get("candidate_set_sha256") != expected_manifest_hash:
        issues.append("candidate_set_manifest_hash_mismatch")
    status = "stale" if stale or issues else "pass"
    return {
        "schema_version": 1,
        "candidate_set_id": manifest.get("candidate_set_id"),
        "status": status,
        "stale_chapters": sorted(set(stale)),
        "issues": issues,
        "audit_status": "stale" if status == "stale" else "current",
        "candidate_set_sha256": manifest.get("candidate_set_sha256"),
    }


def freeze_candidate_set(
    project_root: Path,
    manifest_path: Path,
    *,
    frozen_at: str | None = None,
) -> dict[str, object]:
    """Freeze a hash-valid draft Candidate Set before audit begins."""
    path = Path(manifest_path)
    manifest = safe_read_yaml(path, default=None)
    if not isinstance(manifest, dict) or manifest.get("status") != "draft":
        raise ValueError("only a draft candidate set can be frozen")
    validation = validate_candidate_set(project_root, path)
    if validation["status"] != "pass":
        raise ValueError("candidate set is stale before freeze")
    manifest["status"] = "frozen"
    manifest["frozen_at"] = frozen_at or datetime.now(timezone.utc).isoformat()
    manifest["candidate_set_sha256"] = _manifest_sha256(manifest)
    atomic_write_yaml(path, manifest)
    return {**manifest, "manifest_path": str(path)}
