"""Deterministic validation for an AgentLab-authored longform blueprint."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any
import hashlib
import json
import re
import tempfile

import yaml

from agent_runtime.artifact_digest import artifact_sha256
from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.narrative.fact_authority import (
    load_fact_authority,
    verify_registered_fact_authority,
)
from agent_runtime.project_reset import fact_distillation_issues


REQUIRED_CANONICAL_KINDS = frozenset(
    {
        "character",
        "relationship",
        "faction",
        "location",
        "magic_rule",
        "item",
        "event",
        "knowledge",
        "worldline",
        "foreshadowing",
        "part_arc",
    }
)
REQUIRED_CHARACTER_CONTENT_POLICY_IDS = frozenset(
    {
        "policy_adult_dark_intimacy",
        "policy_women_agency_and_appearance",
        "profile_isabella_visual",
        "profile_lia_adult_depiction",
        "profile_existing_women_motifs",
    }
)
BLUEPRINT_AUTHORITY_PATH = "production/blueprint_authority.yml"
BLUEPRINT_COMPONENT_PATHS = (
    "production/series_scale_decision.yml",
    "production/chapter_length_policy.yml",
    "production/canonical",
    "production/chapter_cards",
)
BLUEPRINT_ARTIFACT_PATHS = (BLUEPRINT_AUTHORITY_PATH,)
BLUEPRINT_MEMORY_PATHS = (
    "project_brain/fact_distillation.yml",
    "project_brain/project_fact_snapshot.yml",
)
CROWN_BLUEPRINT_DELIVERY_EVIDENCE_ROOT = (
    "deliveries/crown_blueprint_authority_20260724_user_policy_override_final/"
    "projects/Crown_of_Ash"
)
REQUIRED_CHARACTER_CONTENT_EVIDENCE_PATHS = frozenset(
    {
        f"{CROWN_BLUEPRINT_DELIVERY_EVIDENCE_ROOT}/runs/"
        "task_crown_mature_sensual_beastfolk_overlay_20260722/outputs/"
        "mature_sensual_beastfolk_overlay_v1.yml",
        f"{CROWN_BLUEPRINT_DELIVERY_EVIDENCE_ROOT}/runs/"
        "task_crown_female_age_rebalance_20260722/outputs/"
        "female_age_rebalance_patch_v1.yml",
        f"{CROWN_BLUEPRINT_DELIVERY_EVIDENCE_ROOT}/runs/"
        "task_crown_uncanny_manifestations_worldtexture_20260722/outputs/"
        "uncanny_manifestations_worldtexture_patch_v1.yml",
        f"{CROWN_BLUEPRINT_DELIVERY_EVIDENCE_ROOT}/runs/"
        "task_crown_uncanny_manifestations_worldtexture_20260722/outputs/"
        "writing_memory_absorption_contract_v1.yml",
        f"{CROWN_BLUEPRINT_DELIVERY_EVIDENCE_ROOT}/runs/"
        "task_crown_character_policy_user_override_20260724/outputs/"
        "user_policy_override_v1.yml",
        "production/outlines/03_感情戏执行准则.md",
    }
)
BLUEPRINT_BUNDLE_FIELDS = frozenset(
    {
        "schema_version",
        "project",
        "status",
        "candidate_only",
        "blueprint_authority",
        "series_scale_decision",
        "chapter_length_policy",
        "canonical_fragments",
        "chapter_cards",
    }
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(path: Path, issues: list[str], label: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        issues.append(f"unreadable:{label}:{type(exc).__name__}")
        return {}
    if not isinstance(value, dict):
        issues.append(f"not_mapping:{label}")
        return {}
    return value


def _has_symlink_component(path: Path, root: Path) -> bool:
    if root.absolute().is_symlink():
        return True
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError:
        return True
    cursor = root.absolute()
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return True
    return False


def _relative_file(project_root: Path, relative: str, prefix: str) -> Path | None:
    pure = PurePosixPath(str(relative))
    if (
        pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or not pure.as_posix().startswith(prefix)
    ):
        return None
    raw_path = project_root / Path(*pure.parts)
    if _has_symlink_component(raw_path, project_root):
        return None
    path = raw_path.resolve()
    if project_root not in path.parents or not path.is_file():
        return None
    return path


def _candidate_blueprint_bundle_path(project_root: Path, bundle_path: Path) -> Path:
    bundle = Path(bundle_path).resolve()
    try:
        relative = bundle.relative_to(project_root)
    except ValueError as exc:
        raise ValueError("blueprint bundle must stay inside the project") from exc
    if (
        len(relative.parts) < 4
        or relative.parts[0] != "runs"
        or relative.parts[2] != "artifacts"
        or bundle.suffix not in {".yml", ".yaml"}
        or not bundle.is_file()
    ):
        raise ValueError(
            "blueprint bundle must be a YAML artifact under runs/<task_id>/artifacts/"
        )
    cursor = project_root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("blueprint bundle path must not contain symlinks")
    return bundle


def _bundle_fragment_path(raw: Any) -> str:
    relative = str(raw or "").strip()
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or not relative.startswith("production/canonical/")
        or relative == "production/canonical/index.yml"
        or pure.suffix not in {".yml", ".yaml"}
    ):
        raise ValueError(f"unsafe canonical fragment path: {relative or '<blank>'}")
    return pure.as_posix()


def _write_blueprint_bundle_tree(project_root: Path, bundle: dict[str, Any]) -> None:
    fragments = bundle.get("canonical_fragments")
    cards = bundle.get("chapter_cards")
    if not isinstance(fragments, list) or not fragments:
        raise ValueError("blueprint bundle requires canonical_fragments")
    if not isinstance(cards, dict):
        raise ValueError("blueprint bundle requires chapter_cards")
    card_index = cards.get("index")
    card_items = cards.get("cards")
    if not isinstance(card_index, dict) or not isinstance(card_items, list):
        raise ValueError("chapter_cards requires index and cards")

    atomic_write_yaml(
        project_root / "production" / "series_scale_decision.yml",
        bundle.get("series_scale_decision"),
    )
    atomic_write_yaml(
        project_root / "production" / "chapter_length_policy.yml",
        bundle.get("chapter_length_policy"),
    )

    fragment_index: list[dict[str, Any]] = []
    seen_fragment_paths: set[str] = set()
    for item in fragments:
        if not isinstance(item, dict) or not isinstance(item.get("document"), dict):
            raise ValueError("canonical fragment entries require path and document")
        relative = _bundle_fragment_path(item.get("path"))
        if relative in seen_fragment_paths:
            raise ValueError(f"duplicate canonical fragment path: {relative}")
        seen_fragment_paths.add(relative)
        path = project_root / relative
        atomic_write_yaml(path, item["document"])
        fragment_index.append({"path": relative, "sha256": _sha256(path)})
    atomic_write_yaml(
        project_root / "production" / "canonical" / "index.yml",
        {"schema_version": 1, "fragments": fragment_index},
    )

    atomic_write_yaml(
        project_root / "production" / "chapter_cards" / "index.yml",
        card_index,
    )
    seen_chapters: set[int] = set()
    for card in card_items:
        if not isinstance(card, dict) or type(card.get("chapter")) is not int:
            raise ValueError("chapter card entries require an integer chapter")
        chapter = int(card["chapter"])
        if chapter < 1 or chapter in seen_chapters:
            raise ValueError(f"invalid or duplicate chapter card: {chapter}")
        seen_chapters.add(chapter)
        atomic_write_yaml(
            project_root / "production" / "chapter_cards" / f"ch{chapter:03d}.yml",
            card,
        )
    authority = bundle.get("blueprint_authority")
    if not isinstance(authority, dict):
        raise ValueError("blueprint bundle requires blueprint_authority")
    atomic_write_yaml(project_root / BLUEPRINT_AUTHORITY_PATH, authority)
    _seal_blueprint_authority(
        project_root,
        project=str(bundle.get("project") or ""),
    )


def materialize_crown_blueprint(
    agentlab_root: Path,
    *,
    bundle_path: Path,
    project: str = "Crown_of_Ash",
) -> dict[str, Any]:
    """Validate then atomically install an AgentLab-authored blueprint bundle."""
    root = Path(agentlab_root).resolve()
    project_root = (root / "projects" / project).resolve()
    bundle_file = _candidate_blueprint_bundle_path(project_root, bundle_path)
    try:
        raw = yaml.safe_load(bundle_file.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read blueprint bundle: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != BLUEPRINT_BUNDLE_FIELDS:
        raise ValueError("blueprint bundle has invalid root fields")
    if (
        raw.get("schema_version") != 1
        or raw.get("project") != project
        or raw.get("status") != "approved"
        or raw.get("candidate_only") is not True
        or not isinstance(raw.get("blueprint_authority"), dict)
        or not isinstance(raw.get("series_scale_decision"), dict)
        or not isinstance(raw.get("chapter_length_policy"), dict)
    ):
        raise ValueError("blueprint bundle has invalid identity or decision payload")

    production = project_root / "production"
    retained_guide = production / "outlines" / "03_感情戏执行准则.md"
    if production.exists():
        allowed_existing = (
            production.is_dir()
            and not production.is_symlink()
            and (
                not any(production.iterdir())
                or (
                    retained_guide.is_file()
                    and not retained_guide.is_symlink()
                    and {
                        path.relative_to(production).as_posix()
                        for path in production.rglob("*")
                    }
                    == {
                        "outlines",
                        "outlines/03_感情戏执行准则.md",
                    }
                )
            )
        )
        if not allowed_existing:
            raise ValueError(
                "production blueprint root must be absent, empty, or contain only "
                "the bound relationship-guide evidence"
            )

    with tempfile.TemporaryDirectory(prefix=".blueprint-stage-", dir=project_root) as raw_stage:
        stage_root = Path(raw_stage) / "agentlab"
        stage_project = stage_root / "projects" / project
        for relative in BLUEPRINT_MEMORY_PATHS:
            source = project_root / relative
            if not source.is_file():
                raise ValueError(f"blueprint memory input is missing: {relative}")
            destination = stage_project / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
        for relative in sorted(REQUIRED_CHARACTER_CONTENT_EVIDENCE_PATHS):
            source = project_root / relative
            if (
                _has_symlink_component(source, project_root)
                or not source.is_file()
                or source.is_symlink()
            ):
                raise ValueError(
                    f"character content evidence input is missing or unsafe: {relative}"
                )
            destination = stage_project / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
        _write_blueprint_bundle_tree(stage_project, raw)
        validation = validate_crown_blueprint(stage_root, project=project)
        if validation.get("status") != "pass":
            raise ValueError(
                "blueprint bundle validation blocked: "
                + ", ".join(str(item) for item in validation.get("issues") or [])
            )
        staged_production = stage_project / "production"
        if production.exists():
            if retained_guide.exists():
                retained_guide.unlink()
                retained_guide.parent.rmdir()
            production.rmdir()
        staged_production.replace(production)

    return {
        "schema_version": 1,
        "status": "materialized",
        "project": project,
        "bundle_path": bundle_file.relative_to(root).as_posix(),
        "bundle_sha256": _sha256(bundle_file),
        "validation": validation,
    }


def _record_refs(record: dict[str, Any]) -> set[str]:
    refs = {str(item) for item in record.get("refs") or []}
    for key, value in record.items():
        if key.endswith("_ref") and isinstance(value, str):
            refs.add(value)
        elif key.endswith("_refs") and isinstance(value, list):
            refs.update(str(item) for item in value)
    if record.get("kind") == "relationship":
        refs.update(str(item) for item in record.get("participants") or [])
    return refs


def _as_int(value: Any, issues: list[str], label: str) -> int:
    if isinstance(value, bool):
        issues.append(f"invalid_integer:{label}")
        return 0
    try:
        if isinstance(value, int):
            return value
        text = str(value).strip()
        if not re.fullmatch(r"-?\d+", text):
            raise ValueError(text)
        return int(text)
    except (TypeError, ValueError):
        issues.append(f"invalid_integer:{label}")
        return 0


def _blueprint_artifact_hashes(project_root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for relative in (
        *BLUEPRINT_ARTIFACT_PATHS,
        *BLUEPRINT_COMPONENT_PATHS,
        *BLUEPRINT_MEMORY_PATHS,
    ):
        path = project_root / relative
        if _has_symlink_component(path, project_root):
            raise ValueError(f"blueprint artifact path contains a symlink: {relative}")
        if not (path.is_file() or path.is_dir()):
            raise ValueError(f"blueprint artifact is missing: {relative}")
        hashes[relative] = artifact_sha256(path)
    return hashes


def _seal_blueprint_authority(project_root: Path, *, project: str) -> dict[str, Any]:
    authority_path = project_root / BLUEPRINT_AUTHORITY_PATH
    try:
        authority = yaml.safe_load(authority_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot seal blueprint authority: {exc}") from exc
    if (
        not isinstance(authority, dict)
        or authority.get("schema_version") != "crown-blueprint-authority/v1"
        or authority.get("project") != project
        or authority.get("status") != "active"
        or authority.get("sole_writer_entrypoint") is not True
        or authority.get("conflict_action")
        != "fail_closed_before_context_compilation"
    ):
        raise ValueError("blueprint authority identity or fail-closed policy is invalid")
    sealed_components: list[dict[str, str]] = []
    for relative in BLUEPRINT_COMPONENT_PATHS:
        path = project_root / relative
        if _has_symlink_component(path, project_root):
            raise ValueError(
                f"blueprint authority component contains a symlink: {relative}"
            )
        if not (path.is_file() or path.is_dir()):
            raise ValueError(f"blueprint authority component is missing: {relative}")
        sealed_components.append(
            {"path": relative, "sha256": artifact_sha256(path)}
        )
    authority = {**authority, "components": sealed_components}
    atomic_write_yaml(authority_path, authority)
    return authority


def seal_crown_blueprint(
    agentlab_root: Path,
    *,
    project: str = "Crown_of_Ash",
    source_task: str | None = None,
    source_run_artifact: str | None = None,
    allow_registered_blueprint_drift: bool = False,
) -> dict[str, Any]:
    """Hash AgentLab-authored blueprint files without changing their decisions."""
    root = Path(agentlab_root).resolve()
    raw_project_root = root / "projects" / project
    if _has_symlink_component(raw_project_root, root / "projects"):
        raise ValueError("project path must not contain symlinks")
    project_root = raw_project_root.resolve()
    artifact_index_path = project_root / "project_artifact_index.yml"
    try:
        existing_artifact_index = (
            yaml.safe_load(artifact_index_path.read_text(encoding="utf-8")) or {}
            if artifact_index_path.is_file()
            else {}
        )
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read current project artifact index: {exc}") from exc
    if not isinstance(existing_artifact_index, dict):
        raise ValueError("current project artifact index must be a mapping")
    if artifact_index_path.is_file() and (
        existing_artifact_index.get("schema_version") != 1
        or existing_artifact_index.get("project") != project
    ):
        raise ValueError("current project artifact index schema or project mismatch")
    existing_artifacts = existing_artifact_index.get("artifacts", [])
    if not isinstance(existing_artifacts, list):
        raise ValueError("current project artifact index artifacts must be a list")
    existing_current = existing_artifact_index.get("current", {})
    if not isinstance(existing_current, dict):
        raise ValueError("current project artifact index current must be a mapping")
    current_records: dict[str, dict[str, Any]] = {}
    historical_records: list[dict[str, Any]] = []
    for raw in existing_artifacts:
        if not isinstance(raw, dict):
            raise ValueError("current project artifact index entry must be a mapping")
        if raw.get("status") != "current":
            historical_records.append(dict(raw))
            continue
        artifact_id = str(raw.get("artifact_id") or "").strip()
        relative = PurePosixPath(str(raw.get("production_path") or ""))
        expected_sha256 = str(raw.get("production_sha256") or "")
        if (
            not artifact_id
            or artifact_id in current_records
            or relative.is_absolute()
            or not relative.parts
            or relative.parts[0] not in {"production", "project_brain"}
            or any(part in {"", ".", ".."} for part in relative.parts)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
        ):
            raise ValueError("current project artifact index has an invalid current entry")
        raw_target = project_root / Path(*relative.parts)
        if _has_symlink_component(raw_target, project_root):
            raise ValueError(
                f"current project artifact path contains a symlink: {relative}"
            )
        target = raw_target.resolve()
        if project_root not in target.parents or not (
            target.is_file() or target.is_dir()
        ):
            raise ValueError(f"current project artifact is missing: {relative}")
        is_blueprint_record = (
            artifact_id.startswith("crown_blueprint_")
            or relative.as_posix() == BLUEPRINT_AUTHORITY_PATH
            or relative.as_posix() in BLUEPRINT_COMPONENT_PATHS
        )
        if (
            artifact_sha256(target) != expected_sha256
            and not (is_blueprint_record and allow_registered_blueprint_drift)
        ):
            raise ValueError(f"current project artifact hash mismatch: {relative}")
        current_records[artifact_id] = dict(raw)
    expected_current = {
        artifact_id: record["production_path"]
        for artifact_id, record in current_records.items()
    }
    if existing_current != expected_current:
        raise ValueError("current project artifact index current mapping mismatch")
    authority_path = project_root / "production" / "fact_authority.yml"
    selected_authority: dict[str, Any] | None = None
    if authority_path.is_file():
        try:
            authority, authority_sha256 = load_fact_authority(
                authority_path,
                project=project,
            )
            selected_authority = verify_registered_fact_authority(
                project_root,
                authority,
                authority_sha256,
            )
        except ValueError as exc:
            raise ValueError(
                f"cannot preserve active fact authority: {exc}"
            ) from exc
    elif "production/fact_authority.yml" in existing_current.values():
        raise ValueError("selected fact authority file is missing")
    if bool(source_task) != bool(source_run_artifact):
        raise ValueError(
            "source_task and source_run_artifact must be provided together"
        )
    lineage: dict[str, str] = {}
    if source_task and source_run_artifact:
        task = PurePosixPath(source_task)
        artifact = PurePosixPath(source_run_artifact)
        if len(task.parts) != 1 or task.parts[0] in {"", ".", ".."}:
            raise ValueError("source_task must be one safe task id")
        if (
            artifact.is_absolute()
            or len(artifact.parts) < 2
            or artifact.parts[0] != "artifacts"
            or any(part in {"", ".", ".."} for part in artifact.parts)
        ):
            raise ValueError(
                "source_run_artifact must stay under the task artifacts directory"
            )
        source = _candidate_blueprint_bundle_path(
            project_root,
            project_root / "runs" / task.as_posix() / Path(*artifact.parts),
        )
        lineage = {
            "source_task": task.as_posix(),
            "source_run_artifact": artifact.as_posix(),
            "source_run_artifact_sha256": _sha256(source),
        }
    index_path = project_root / "production" / "canonical" / "index.yml"
    try:
        index = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot seal canonical index: {exc}") from exc
    fragments = index.get("fragments") if isinstance(index, dict) else None
    if not isinstance(fragments, list) or not fragments:
        raise ValueError("cannot seal blueprint without canonical fragments")
    sealed_fragments: list[dict[str, Any]] = []
    for raw in fragments:
        if not isinstance(raw, dict):
            raise ValueError("canonical fragment entries must be mappings")
        relative = str(raw.get("path") or "")
        path = _relative_file(project_root, relative, "production/canonical/")
        if path is None or path == index_path:
            raise ValueError(f"unsafe or missing canonical fragment: {relative}")
        sealed_fragments.append({**raw, "sha256": _sha256(path)})
    atomic_write_yaml(index_path, {**index, "fragments": sealed_fragments})
    _seal_blueprint_authority(project_root, project=project)

    card_index_path = project_root / "production" / "chapter_cards" / "index.yml"
    try:
        card_index = yaml.safe_load(card_index_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot seal chapter card index: {exc}") from exc
    card_entries = (
        card_index.get("chapter_state_plan")
        if isinstance(card_index, dict)
        else None
    )
    card_chapters = [
        entry.get("chapter")
        for entry in (card_entries or [])
        if isinstance(entry, dict)
        and isinstance(entry.get("chapter"), int)
        and not isinstance(entry.get("chapter"), bool)
    ]
    if not card_chapters:
        raise ValueError("cannot seal blueprint without chapter card entries")
    validation = validate_crown_blueprint(
        root,
        project=project,
        chapter_start=min(card_chapters),
        chapter_end=max(card_chapters),
    )
    if validation.get("status") != "pass":
        raise ValueError(
            "blueprint validation blocked: "
            + ", ".join(str(item) for item in validation.get("issues") or [])
        )
    artifact_hashes = _blueprint_artifact_hashes(project_root)
    validation_payload = json.dumps(
        validation,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    validation_receipt = {
        "schema_version": 1,
        "status": "pass",
        "project": project,
        "validation_sha256": hashlib.sha256(
            validation_payload.encode("utf-8")
        ).hexdigest(),
        "validation": validation,
        "artifact_hashes": artifact_hashes,
    }
    validation_receipt_path = (
        project_root / "project_brain" / "blueprint_validation_receipt.yml"
    )
    atomic_write_yaml(validation_receipt_path, validation_receipt)

    artifacts: list[dict[str, Any]] = list(historical_records)
    preserved_current = [
        record
        for artifact_id, record in current_records.items()
        if not artifact_id.startswith("crown_blueprint_")
        and record.get("production_path") not in BLUEPRINT_COMPONENT_PATHS
        and record.get("production_path") != "production/fact_authority.yml"
    ]
    for number, relative in enumerate(BLUEPRINT_ARTIFACT_PATHS, start=1):
        artifacts.append(
            {
                "artifact_id": f"crown_blueprint_{number:02d}",
                "status": "current",
                "production_path": relative,
                "production_sha256": artifact_hashes[relative],
                "evidence_only": False,
                **lineage,
            }
        )
    artifacts.extend(preserved_current)
    if selected_authority is not None:
        artifacts.append(selected_authority)
    artifact_index = {
        "schema_version": 1,
        "project": project,
        "candidate_prose_promoted": bool(
            existing_artifact_index.get("candidate_prose_promoted", False)
        ),
        "artifacts": artifacts,
        "current": {
            item["artifact_id"]: item["production_path"]
            for item in artifacts
            if item.get("status") == "current"
        },
    }
    atomic_write_yaml(artifact_index_path, artifact_index)
    return {
        "schema_version": 1,
        "status": "sealed",
        "project": project,
        "fragment_count": len(sealed_fragments),
        "artifact_count": len(artifacts),
        "artifact_index": artifact_index_path.relative_to(root).as_posix(),
        "artifact_index_sha256": _sha256(artifact_index_path),
        "validation_receipt": validation_receipt_path.relative_to(root).as_posix(),
        "validation_receipt_sha256": _sha256(validation_receipt_path),
    }


def validate_blueprint_seal(
    agentlab_root: Path,
    *,
    project: str = "Crown_of_Ash",
    chapter_start: int = 1,
    chapter_end: int = 20,
) -> dict[str, Any]:
    """Verify the current blueprint still matches its passed seal receipt."""
    root = Path(agentlab_root).resolve()
    raw_project_root = root / "projects" / project
    if _has_symlink_component(raw_project_root, root / "projects"):
        return {
            "schema_version": 1,
            "status": "blocked",
            "project": project,
            "validation_receipt": (
                Path("projects")
                / project
                / "project_brain"
                / "blueprint_validation_receipt.yml"
            ).as_posix(),
            "issues": ["unsafe_project_path_symlink"],
        }
    project_root = raw_project_root.resolve()
    receipt_path = project_root / "project_brain" / "blueprint_validation_receipt.yml"
    if _has_symlink_component(receipt_path, project_root):
        return {
            "schema_version": 1,
            "status": "blocked",
            "project": project,
            "validation_receipt": receipt_path.relative_to(root).as_posix(),
            "issues": ["unsafe_blueprint_artifact_symlink"],
        }
    issues: list[str] = []
    receipt = _mapping(receipt_path, issues, "blueprint_validation_receipt")
    if receipt.get("status") != "pass" or receipt.get("project") != project:
        issues.append("receipt_not_passed")
    receipt_validation = receipt.get("validation")
    sealed_range = (
        receipt_validation.get("chapter_range")
        if isinstance(receipt_validation, dict)
        else None
    )
    valid_sealed_range = bool(
        isinstance(sealed_range, list)
        and len(sealed_range) == 2
        and all(
            isinstance(item, int) and not isinstance(item, bool)
            for item in sealed_range
        )
        and int(sealed_range[0]) >= 1
        and int(sealed_range[1]) >= int(sealed_range[0])
    )
    if valid_sealed_range:
        sealed_start, sealed_end = int(sealed_range[0]), int(sealed_range[1])
        if (
            chapter_start < sealed_start
            or chapter_end > sealed_end
            or chapter_end < chapter_start
        ):
            issues.append("requested_window_outside_sealed_range")
    else:
        sealed_start, sealed_end = chapter_start, chapter_end
        issues.append("validation_receipt_range_invalid")
    validation = validate_crown_blueprint(
        root,
        project=project,
        chapter_start=sealed_start,
        chapter_end=sealed_end,
    )
    if validation.get("status") != "pass":
        issues.append("current_blueprint_invalid")
    if receipt.get("validation") != validation:
        issues.append("validation_receipt_drift")
    payload = json.dumps(
        validation,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if receipt.get("validation_sha256") != hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest():
        issues.append("validation_hash_mismatch")
    try:
        current_hashes = _blueprint_artifact_hashes(project_root)
    except ValueError:
        current_hashes = {}
        issues.append("blueprint_artifact_missing")
    if receipt.get("artifact_hashes") != current_hashes:
        issues.append("blueprint_artifact_hash_drift")
    return {
        "schema_version": 1,
        "status": "pass" if not issues else "blocked",
        "project": project,
        "validation_receipt": receipt_path.relative_to(root).as_posix(),
        "issues": sorted(set(issues)),
    }


def validate_crown_blueprint(
    agentlab_root: Path,
    *,
    project: str = "Crown_of_Ash",
    chapter_start: int = 1,
    chapter_end: int = 20,
) -> dict[str, Any]:
    """Validate structure and invariants without choosing creative parameters."""
    root = Path(agentlab_root).resolve()
    raw_project_root = root / "projects" / project
    if _has_symlink_component(raw_project_root, root / "projects"):
        return {
            "schema_version": 1,
            "status": "blocked",
            "project": project,
            "chapter_range": [chapter_start, chapter_end],
            "issues": ["unsafe_project_path_symlink"],
            "counts": {},
        }
    project_root = raw_project_root.resolve()
    issues: list[str] = []
    unsafe_fixed_paths = [
        relative
        for relative in (
            *BLUEPRINT_ARTIFACT_PATHS,
            *BLUEPRINT_COMPONENT_PATHS,
            *BLUEPRINT_MEMORY_PATHS,
        )
        if _has_symlink_component(project_root / relative, project_root)
    ]
    if unsafe_fixed_paths:
        return {
            "schema_version": 1,
            "status": "blocked",
            "project": project,
            "chapter_range": [chapter_start, chapter_end],
            "issues": [
                f"unsafe_blueprint_artifact_symlink:{relative}"
                for relative in unsafe_fixed_paths
            ],
            "counts": {},
        }
    blueprint_authority = _mapping(
        project_root / BLUEPRINT_AUTHORITY_PATH,
        issues,
        "blueprint_authority",
    )
    scale = _mapping(
        project_root / "production" / "series_scale_decision.yml",
        issues,
        "series_scale_decision",
    )
    length = _mapping(
        project_root / "production" / "chapter_length_policy.yml",
        issues,
        "chapter_length_policy",
    )
    distillation = _mapping(
        project_root / "project_brain" / "fact_distillation.yml",
        issues,
        "fact_distillation",
    )
    project_fact_snapshot = _mapping(
        project_root / "project_brain" / "project_fact_snapshot.yml",
        issues,
        "project_fact_snapshot",
    )
    distilled_source_hashes = {
        str(source.get("sha256") or "")
        for source in distillation.get("sources") or []
        if isinstance(source, dict) and source.get("sha256")
    }
    distilled_sources = [
        source
        for source in distillation.get("sources") or []
        if isinstance(source, dict)
    ]
    for relative, expected_status in (
        (BLUEPRINT_AUTHORITY_PATH, "sole_blueprint_entrypoint"),
        (
            "production/canonical/character_content_policy.yml",
            "active_character_content_authority",
        ),
    ):
        matching_sources = [
            source
            for source in distilled_sources
            if source.get("path") == relative
        ]
        current_path = project_root / relative
        if (
            len(matching_sources) != 1
            or matching_sources[0].get("status") != expected_status
            or not current_path.is_file()
            or _has_symlink_component(current_path, project_root)
            or matching_sources[0].get("sha256") != _sha256(current_path)
        ):
            issues.append(
                f"fact_distillation:current_authority_source_mismatch:{relative}"
            )
    isabella_conflicts = [
        conflict
        for conflict in distillation.get("conflicts") or []
        if isinstance(conflict, dict)
        and conflict.get("id") == "conflict_isabella_appearance"
    ]
    expected_isabella_resolution = {
        "authority_path": (
            "production/canonical/character_content_policy.yml"
        ),
        "authority_source_hash": (
            "4c678740622dc7128eeec46b2bb8f614198f2da828cffaee663b20eb272ae543"
        ),
        "selected_claim": "full_figured_mature_type",
        "retired_claim": "pathologically_slender",
    }
    if (
        len(isabella_conflicts) != 1
        or isabella_conflicts[0].get("status") != "resolved"
        or isabella_conflicts[0].get("resolution")
        != expected_isabella_resolution
    ):
        issues.append(
            "fact_distillation:isabella_appearance_resolution_mismatch"
        )

    if (
        blueprint_authority.get("schema_version")
        != "crown-blueprint-authority/v1"
        or blueprint_authority.get("project") != project
        or blueprint_authority.get("status") != "active"
        or blueprint_authority.get("sole_writer_entrypoint") is not True
    ):
        issues.append("blueprint_authority:not_active_sole_entrypoint")
    if (
        blueprint_authority.get("conflict_action")
        != "fail_closed_before_context_compilation"
    ):
        issues.append("blueprint_authority:not_fail_closed")
    component_entries = blueprint_authority.get("components")
    component_by_path = {
        str(item.get("path") or ""): str(item.get("sha256") or "")
        for item in (component_entries or [])
        if isinstance(item, dict)
    }
    if set(component_by_path) != set(BLUEPRINT_COMPONENT_PATHS):
        issues.append("blueprint_authority:component_set_mismatch")
    for relative in BLUEPRINT_COMPONENT_PATHS:
        path = project_root / relative
        if not (path.is_file() or path.is_dir()):
            issues.append(f"blueprint_authority:missing_component:{relative}")
        elif component_by_path.get(relative) != artifact_sha256(path):
            issues.append(f"blueprint_authority:component_hash_mismatch:{relative}")

    for label, decision in (("series_scale", scale), ("chapter_length", length)):
        if decision.get("status") != "approved" or not str(
            decision.get("decision_maker") or ""
        ).startswith("AgentLab."):
            issues.append(f"{label}:not_agentlab_approved")
        if not isinstance(decision.get("evidence"), list) or not decision["evidence"]:
            issues.append(f"{label}:missing_evidence")
        else:
            for index, evidence in enumerate(decision["evidence"], start=1):
                hashes = evidence.get("source_hashes") if isinstance(evidence, dict) else None
                if not isinstance(hashes, list) or not hashes:
                    issues.append(f"{label}:missing_evidence_hashes:{index}")
                elif any(str(item) not in distilled_source_hashes for item in hashes):
                    issues.append(f"{label}:unbound_evidence_hash:{index}")
    parts = scale.get("parts")
    if not isinstance(parts, list) or len(parts) != 3:
        issues.append("series_scale:requires_exactly_three_parts")
        parts = []
    part_counts = [
        _as_int(item.get("planned_chapters"), issues, f"series_scale.parts.{index}")
        for index, item in enumerate(parts, start=1)
        if isinstance(item, dict)
    ]
    if len(part_counts) != 3 or any(count < 500 for count in part_counts):
        issues.append("series_scale:each_part_below_500")
    total = _as_int(
        scale.get("planned_total_chapters"),
        issues,
        "series_scale.planned_total_chapters",
    )
    if not 1800 <= total <= 2200:
        issues.append("series_scale:not_near_2000")
    if part_counts and sum(part_counts) != total:
        issues.append("series_scale:part_total_mismatch")
    constraints = scale.get("constraints") or {}
    if constraints.get("three_parts") is not True or constraints.get("anti_padding") is not True:
        issues.append("series_scale:upper_constraints_missing")
    authority_scope = blueprint_authority.get("scope") or {}
    if authority_scope.get("planned_total_chapters") != total:
        issues.append("blueprint_authority:scale_mismatch")
    if authority_scope.get("detailed_chapter_contract_range") != [
        chapter_start,
        chapter_end,
    ]:
        issues.append("blueprint_authority:detailed_range_mismatch")
    policy_refs = blueprint_authority.get("policy_refs") or {}
    if (
        policy_refs.get("character_content_authority")
        != "production/canonical/character_content_policy.yml"
    ):
        issues.append("blueprint_authority:character_content_policy_missing")

    length_values = [
        _as_int(length.get(key), issues, f"chapter_length.{key}")
        for key in ("soft_min", "target", "soft_max")
    ]
    if not (0 < length_values[0] <= length_values[1] <= length_values[2]):
        issues.append("chapter_length:invalid_agent_selected_range")
    anti_padding = length.get("anti_padding") or {}
    if (
        anti_padding.get("prohibit_filler") is not True
        or anti_padding.get("allow_scene_density_override") is not True
    ):
        issues.append("chapter_length:anti_padding_policy_missing")

    for issue in fact_distillation_issues(distillation):
        issues.append(f"fact_distillation:{issue}")

    canonical_index = _mapping(
        project_root / "production" / "canonical" / "index.yml",
        issues,
        "canonical_index",
    )
    fragment_entries = canonical_index.get("fragments")
    if not isinstance(fragment_entries, list) or not fragment_entries:
        issues.append("canonical:missing_fragments")
        fragment_entries = []
    records: dict[str, dict[str, Any]] = {}
    fragment_paths: set[str] = set()
    kinds: set[str] = set()
    character_content_policy: dict[str, Any] = {}
    character_content_policy_record_ids: set[str] = set()
    for entry in fragment_entries:
        if not isinstance(entry, dict):
            issues.append("canonical:invalid_fragment_entry")
            continue
        relative = str(entry.get("path") or "")
        path = _relative_file(project_root, relative, "production/canonical/")
        if path is None:
            issues.append(f"canonical:unsafe_or_missing_fragment:{relative}")
            continue
        fragment_paths.add(relative)
        if str(entry.get("sha256") or "") != _sha256(path):
            issues.append(f"canonical:fragment_hash_mismatch:{relative}")
        fragment = _mapping(path, issues, relative)
        if relative == "production/canonical/character_content_policy.yml":
            character_content_policy = fragment
        fragment_records = fragment.get("records") or []
        if relative == "production/canonical/character_content_policy.yml":
            character_content_policy_record_ids = {
                str(record.get("id") or "")
                for record in fragment_records
                if isinstance(record, dict) and record.get("id")
            }
        for record in fragment_records:
            if not isinstance(record, dict) or not record.get("id") or not record.get("kind"):
                issues.append(f"canonical:invalid_record:{relative}")
                continue
            record_id = str(record["id"])
            if record_id in records:
                issues.append(f"canonical:duplicate_id:{record_id}")
                continue
            records[record_id] = record
            kinds.add(str(record["kind"]))
            source_hashes = record.get("source_hashes")
            if not isinstance(source_hashes, list) or not source_hashes:
                issues.append(f"canonical:missing_source_hashes:{record_id}")
            elif any(str(item) not in distilled_source_hashes for item in source_hashes):
                issues.append(f"canonical:unbound_source_hash:{record_id}")
    for missing_kind in sorted(REQUIRED_CANONICAL_KINDS - kinds):
        issues.append(f"canonical:missing_kind:{missing_kind}")
    missing_policy_ids = (
        REQUIRED_CHARACTER_CONTENT_POLICY_IDS
        - character_content_policy_record_ids
    )
    if character_content_policy.get("policy_revision") != 3:
        issues.append("character_content_policy:revision_mismatch")
    for policy_id in sorted(missing_policy_ids):
        issues.append(f"character_content_policy:missing_record:{policy_id}")
    adult_policy = records.get("policy_adult_dark_intimacy") or {}
    consent = adult_policy.get("consent_contract") or {}
    contextual_consent = consent.get("contextual_consent") or {}
    scene_controls = adult_policy.get("scene_controls") or {}
    if (
        adult_policy.get("rating") != "mature_sensual_non_graphic"
        or consent.get("minimum_age") != 18
        or consent.get("mutuality_required") is not True
        or consent.get("silence_is_not_consent") is not True
        or contextual_consent.get("automatic_invalidation") is not False
        or set(contextual_consent.get("applicable_contexts") or [])
        != {"权力", "债务", "囚禁", "救命", "医疗", "魔法"}
        or contextual_consent.get("adult_required") is not True
        or contextual_consent.get("clear_minded_at_the_time_required") is not True
        or contextual_consent.get(
            "intimacy_not_exchanged_for_power_or_control"
        )
        is not True
        or not adult_policy.get("allowed")
        or not adult_policy.get("disallowed")
        or scene_controls.get("maximum_sensual_beats_per_scene") != 4
        or scene_controls.get("prohibit_repeated_body_inventory") is not True
        or scene_controls.get("chapter_card_must_declare_level_above_1") is not True
    ):
        issues.append("character_content_policy:adult_contract_incomplete")
    women_policy = records.get("policy_women_agency_and_appearance") or {}
    agency_contract = women_policy.get("agency_contract") or {}
    appearance_contract = women_policy.get("appearance_contract") or {}
    women_principles = women_policy.get("principles") or []
    prohibited_templates = women_policy.get("prohibited_templates") or []
    if (
        len(women_principles) < 5
        or any(not str(item).strip() for item in women_principles)
        or len(prohibited_templates) < 5
        or any(not str(item).strip() for item in prohibited_templates)
        or any(
            agency_contract.get(key) is not True
            for key in (
                "independent_goal_required",
                "independent_resources_required",
                "independent_judgment_required",
                "meaningful_exit_required",
                "body_never_reward_or_container",
            )
        )
        or any(
            appearance_contract.get(key) is not True
            for key in (
                "must_serve_profession_class_choice_cost_or_action",
                "attraction_requires_mutual_viewpoint_decision_and_risk",
                "clothing_or_body_detail_never_implies_consent",
                "physical_contact_never_replaces_conflict_resolution",
            )
        )
    ):
        issues.append("character_content_policy:women_agency_contract_incomplete")
    isabella_profile = records.get("profile_isabella_visual") or {}
    isabella_identity = isabella_profile.get("stable_identity") or {}
    isabella_visual_contract = isabella_profile.get("visual_contract") or {}
    isabella_ref = str(isabella_profile.get("character_ref") or "")
    if (
        (records.get(isabella_ref) or {}).get("kind") != "character"
        or not str(isabella_profile.get("evidence_grade") or "").startswith(
            "user_locked"
        )
        or isabella_visual_contract.get("active_build_id")
        != "full_figured_mature"
        or isabella_visual_contract.get("retired_build_ids")
        != ["pathologically_slender"]
        or isabella_visual_contract.get("authority_source_path")
        != (
            f"{CROWN_BLUEPRINT_DELIVERY_EVIDENCE_ROOT}/runs/"
            "task_crown_character_policy_user_override_20260724/"
            "outputs/user_policy_override_v1.yml"
        )
        or isabella_identity.get("height_cm") != 165
        or not str(isabella_identity.get("build") or "").strip()
        or not isabella_profile.get("use_rules")
    ):
        issues.append("character_content_policy:isabella_profile_incomplete")
    snapshot_facts = {
        str(item.get("id") or ""): item
        for item in project_fact_snapshot.get("facts") or []
        if isinstance(item, dict) and item.get("id")
    }
    snapshot_isabella = snapshot_facts.get("fact_character_isabella") or {}
    snapshot_isabella_value = snapshot_isabella.get("value") or {}
    snapshot_isabella_appearance = (
        snapshot_isabella_value.get("appearance") or {}
    )
    direct_override_sha256 = (
        expected_isabella_resolution["authority_source_hash"]
    )
    if (
        snapshot_isabella_appearance.get("build")
        != isabella_visual_contract.get("active_build_id")
        or snapshot_isabella_appearance.get("retired_build")
        != (isabella_visual_contract.get("retired_build_ids") or [None])[0]
        or direct_override_sha256
        not in (snapshot_isabella.get("source_hashes") or [])
        or snapshot_isabella.get("conflict_status") != "resolved"
        or snapshot_isabella.get("conflict_conclusion")
        != (
            "user_locked_full_figured_mature_profile_supersedes_"
            "pathologically_slender_ch03_profile"
        )
    ):
        issues.append(
            "project_fact_snapshot:isabella_visual_projection_mismatch"
        )
    snapshot_relationship = (
        snapshot_facts.get("fact_relationship_execution_policy") or {}
    )
    snapshot_relationship_value = snapshot_relationship.get("value") or {}
    snapshot_contextual_consent = (
        snapshot_relationship_value.get("contextual_consent") or {}
    )
    expected_context_ids = {
        "权力": "power",
        "债务": "debt",
        "囚禁": "captivity",
        "救命": "rescue",
        "医疗": "medical",
        "魔法": "magic",
    }
    if (
        snapshot_contextual_consent.get("automatic_invalidation")
        is not contextual_consent.get("automatic_invalidation")
        or set(snapshot_contextual_consent.get("applicable_contexts") or [])
        != {
            expected_context_ids[item]
            for item in contextual_consent.get("applicable_contexts") or []
            if item in expected_context_ids
        }
        or snapshot_contextual_consent.get("adult_required")
        is not contextual_consent.get("adult_required")
        or snapshot_contextual_consent.get(
            "clear_minded_at_the_time_required"
        )
        is not contextual_consent.get("clear_minded_at_the_time_required")
        or snapshot_contextual_consent.get(
            "intimacy_not_exchanged_for_power_or_control"
        )
        is not contextual_consent.get(
            "intimacy_not_exchanged_for_power_or_control"
        )
        or direct_override_sha256
        not in (snapshot_relationship.get("source_hashes") or [])
        or snapshot_relationship.get("conflict_status") != "resolved"
        or snapshot_relationship.get("conflict_conclusion")
        != (
            "user_locked_contextual_consent_is_valid_when_adult_clear_"
            "minded_and_not_exchanged_for_power_or_control"
        )
    ):
        issues.append(
            "project_fact_snapshot:contextual_consent_projection_mismatch"
        )
    lia_profile = records.get("profile_lia_adult_depiction") or {}
    lia_identity = lia_profile.get("adult_identity") or {}
    lia_ref = str(lia_profile.get("character_ref") or "")
    if (
        (records.get(lia_ref) or {}).get("kind") != "character"
        or lia_profile.get("current_age") != 18
        or lia_profile.get("historical_continuous_selfhood_age") != 16
        or lia_identity.get("height_cm") != 151
        or not lia_profile.get("relationship_boundary")
    ):
        issues.append("character_content_policy:lia_adult_boundary_incomplete")
    motif_profile = records.get("profile_existing_women_motifs") or {}
    motif_contract = motif_profile.get("motif_contract") or {}
    required_motif_characters = {
        "char_alicia",
        "char_elena",
        "char_cecilia",
        "char_lilian",
    }
    if (
        set(motif_contract) != required_motif_characters
        or any(
            not isinstance(motif_contract.get(character), dict)
            or len(motif_contract[character].get("motifs") or []) < 3
            or not str(motif_contract[character].get("meaning") or "").strip()
            or not str(motif_contract[character].get("gate") or "").strip()
            for character in required_motif_characters
        )
    ):
        issues.append("character_content_policy:motif_contract_incomplete")
    dispositions = character_content_policy.get("candidate_evidence_dispositions")
    disposition_by_path = {
        str(item.get("source_path") or ""): item
        for item in (dispositions or [])
        if isinstance(item, dict)
    }
    required_disposition_paths = REQUIRED_CHARACTER_CONTENT_EVIDENCE_PATHS
    if not required_disposition_paths.issubset(disposition_by_path):
        issues.append("character_content_policy:evidence_dispositions_incomplete")
    for relative in sorted(required_disposition_paths):
        disposition = disposition_by_path.get(relative) or {}
        pure = PurePosixPath(relative)
        source_path = project_root / Path(*pure.parts)
        if (
            pure.is_absolute()
            or any(part in {"", ".", ".."} for part in pure.parts)
            or _has_symlink_component(source_path, project_root)
            or not source_path.is_file()
            or not str(disposition.get("disposition") or "").strip()
            or not re.fullmatch(
                r"[0-9a-f]{64}",
                str(disposition.get("sha256") or ""),
            )
            or (
                source_path.is_file()
                and (
                    source_path.is_symlink()
                    or _has_symlink_component(source_path, project_root)
                )
            )
            or (
                source_path.is_file()
                and str(disposition.get("sha256") or "") != _sha256(source_path)
            )
        ):
            issues.append(
                f"character_content_policy:invalid_evidence_disposition:{relative}"
            )
    for record_id, record in records.items():
        for ref in sorted(_record_refs(record)):
            if ref not in records:
                issues.append(f"canonical:dangling_ref:{record_id}:{ref}")

    for record_id, record in records.items():
        if record.get("kind") != "relationship" or record.get("adult_intimacy") is not True:
            continue
        for participant in record.get("participants") or []:
            character = records.get(str(participant)) or {}
            age = _as_int(
                character.get("age"),
                issues,
                f"canonical.character_age.{participant}",
            )
            if character.get("kind") != "character" or age < 18:
                issues.append(f"canonical:adult_boundary:{record_id}:{participant}")

    state_updates: dict[tuple[str, str, str, str], Any] = {}
    updates_by_subject: dict[tuple[str, str, str], list[tuple[int, Any]]] = defaultdict(list)
    for record_id, record in records.items():
        worldline = str(record.get("worldline_ref") or "default")
        time_index = _as_int(
            record.get("time_index", 0),
            issues,
            f"canonical.time_index.{record_id}",
        )
        for update in record.get("state_updates") or []:
            if not isinstance(update, dict):
                issues.append(f"canonical:invalid_state_update:{record_id}")
                continue
            subject = str(update.get("subject_ref") or "")
            field = str(update.get("field") or "")
            value = update.get("value")
            key = (worldline, str(time_index), subject, field)
            if key in state_updates and state_updates[key] != value:
                issues.append(f"canonical:timeline_conflict:{record_id}:{subject}:{field}")
            state_updates[key] = value
            updates_by_subject[(worldline, subject, field)].append((time_index, value))
    for record_id, record in records.items():
        current = record.get("current_state")
        if not isinstance(current, dict):
            continue
        worldline = str(record.get("worldline_ref") or "default")
        for field in ("alive", "owner_ref"):
            updates = sorted(updates_by_subject.get((worldline, record_id, field)) or [])
            if updates and field in current and current[field] != updates[-1][1]:
                issues.append(f"canonical:current_state_mismatch:{record_id}:{field}")
        owner = current.get("owner_ref")
        if owner is not None and str(owner) not in records:
            issues.append(f"canonical:dangling_owner:{record_id}:{owner}")

    expected_chapters = list(range(chapter_start, chapter_end + 1))
    card_index = _mapping(
        project_root / "production" / "chapter_cards" / "index.yml",
        issues,
        "chapter_card_index",
    )
    raw_indexed_chapters = card_index.get("chapters") or [
        entry.get("chapter")
        for entry in card_index.get("chapter_state_plan") or []
        if isinstance(entry, dict)
    ]
    if not isinstance(raw_indexed_chapters, list):
        issues.append("chapter_cards:index_chapters_not_list")
        raw_indexed_chapters = []
    indexed_chapters = [
        _as_int(item, issues, f"chapter_cards.index.{index}")
        for index, item in enumerate(raw_indexed_chapters, start=1)
    ]
    if indexed_chapters != expected_chapters:
        issues.append("chapter_cards:index_not_exact_range")
    from agent_runtime.narrative_delivery import validate_chapter_state_plan

    try:
        state_plan_validation = validate_chapter_state_plan(
            project_root,
            "production/chapter_cards/index.yml",
            expected_chapters=expected_chapters,
        )
    except (TypeError, ValueError) as exc:
        state_plan_validation = {
            "status": "fail",
            "issues": [{"check": f"invalid_generated_value_{type(exc).__name__}"}],
        }
    if state_plan_validation.get("status") != "pass":
        issues.extend(
            f"chapter_state_plan:{item.get('check', 'invalid')}:{item.get('chapter', item.get('field', ''))}"
            for item in state_plan_validation.get("issues") or []
            if isinstance(item, dict)
        )
    timeline_slots: set[str] = set()
    scene_goals: set[str] = set()
    for chapter in expected_chapters:
        relative = f"production/chapter_cards/ch{chapter:03d}.yml"
        card = _mapping(project_root / relative, issues, relative)
        if _as_int(
            card.get("chapter"),
            issues,
            f"chapter_cards.chapter.{chapter}",
        ) != chapter:
            issues.append(f"chapter_cards:number_mismatch:{chapter}")
        for field, seen in (("timeline_slot", timeline_slots), ("scene_goal", scene_goals)):
            value = str(card.get(field) or "")
            if not value or value in seen:
                issues.append(f"chapter_cards:missing_or_duplicate_{field}:{chapter}")
            seen.add(value)
        pov = str(card.get("pov_ref") or "")
        if not pov or (records.get(pov) or {}).get("kind") != "character":
            issues.append(f"chapter_cards:invalid_pov:{chapter}:{pov}")
        requirements = card.get("knowledge_requirements")
        if not isinstance(requirements, dict):
            issues.append(f"chapter_cards:missing_knowledge_requirements:{chapter}")
            continue
        for group in ("character_state", "timeline_world_rules", "foreshadowing"):
            refs = requirements.get(group)
            if not isinstance(refs, list) or not refs:
                issues.append(f"chapter_cards:missing_group:{chapter}:{group}")
            for ref in refs if isinstance(refs, list) else []:
                if str(ref) not in fragment_paths:
                    issues.append(f"chapter_cards:unknown_fragment:{chapter}:{ref}")

    return {
        "schema_version": 1,
        "status": "pass" if not issues else "blocked",
        "project": project,
        "chapter_range": [chapter_start, chapter_end],
        "record_count": len(records),
        "fragment_count": len(fragment_paths),
        "chapter_card_count": len(expected_chapters),
        "issues": sorted(set(issues)),
    }
