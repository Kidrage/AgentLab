"""Deterministic validation for an AgentLab-authored longform blueprint."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any
import hashlib
import re

import yaml

from agent_runtime.artifact_digest import artifact_sha256
from agent_runtime.atomic_io import atomic_write_yaml


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
_HASH = re.compile(r"^[0-9a-f]{64}$")


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


def _relative_file(project_root: Path, relative: str, prefix: str) -> Path | None:
    pure = PurePosixPath(str(relative))
    if (
        pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or not pure.as_posix().startswith(prefix)
    ):
        return None
    path = (project_root / Path(*pure.parts)).resolve()
    if project_root not in path.parents or not path.is_file():
        return None
    return path


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


def seal_crown_blueprint(
    agentlab_root: Path,
    *,
    project: str = "Crown_of_Ash",
) -> dict[str, Any]:
    """Hash AgentLab-authored blueprint files without changing their decisions."""
    root = Path(agentlab_root).resolve()
    project_root = (root / "projects" / project).resolve()
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

    artifact_paths = (
        "production/series_scale_decision.yml",
        "production/chapter_length_policy.yml",
        "production/canonical",
        "production/chapter_cards",
    )
    artifacts: list[dict[str, Any]] = []
    for number, relative in enumerate(artifact_paths, start=1):
        path = project_root / relative
        if not (path.is_file() or path.is_dir()):
            raise ValueError(f"blueprint artifact is missing: {relative}")
        artifacts.append(
            {
                "artifact_id": f"crown_blueprint_{number:02d}",
                "status": "current",
                "production_path": relative,
                "production_sha256": artifact_sha256(path),
                "evidence_only": False,
            }
        )
    artifact_index = {
        "schema_version": 1,
        "project": project,
        "candidate_prose_promoted": False,
        "artifacts": artifacts,
        "current": {item["artifact_id"]: item["production_path"] for item in artifacts},
    }
    artifact_index_path = project_root / "project_artifact_index.yml"
    atomic_write_yaml(artifact_index_path, artifact_index)
    return {
        "schema_version": 1,
        "status": "sealed",
        "project": project,
        "fragment_count": len(sealed_fragments),
        "artifact_count": len(artifacts),
        "artifact_index": artifact_index_path.relative_to(root).as_posix(),
        "artifact_index_sha256": _sha256(artifact_index_path),
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
    project_root = (root / "projects" / project).resolve()
    issues: list[str] = []
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

    for label, decision in (("series_scale", scale), ("chapter_length", length)):
        if decision.get("status") != "approved" or not str(
            decision.get("decision_maker") or ""
        ).startswith("AgentLab."):
            issues.append(f"{label}:not_agentlab_approved")
        if not isinstance(decision.get("evidence"), list) or not decision["evidence"]:
            issues.append(f"{label}:missing_evidence")
    parts = scale.get("parts")
    if not isinstance(parts, list) or len(parts) != 3:
        issues.append("series_scale:requires_exactly_three_parts")
        parts = []
    part_counts = [int(item.get("planned_chapters") or 0) for item in parts if isinstance(item, dict)]
    if len(part_counts) != 3 or any(count < 500 for count in part_counts):
        issues.append("series_scale:each_part_below_500")
    total = int(scale.get("planned_total_chapters") or 0)
    if not 1800 <= total <= 2200:
        issues.append("series_scale:not_near_2000")
    if part_counts and sum(part_counts) != total:
        issues.append("series_scale:part_total_mismatch")
    constraints = scale.get("constraints") or {}
    if constraints.get("three_parts") is not True or constraints.get("anti_padding") is not True:
        issues.append("series_scale:upper_constraints_missing")

    length_values = [
        int(length.get(key) or 0) for key in ("soft_min", "target", "soft_max")
    ]
    if not (0 < length_values[0] <= length_values[1] <= length_values[2]):
        issues.append("chapter_length:invalid_agent_selected_range")
    anti_padding = length.get("anti_padding") or {}
    if (
        anti_padding.get("prohibit_filler") is not True
        or anti_padding.get("allow_scene_density_override") is not True
    ):
        issues.append("chapter_length:anti_padding_policy_missing")

    if distillation.get("legacy_prose_retained") is not False:
        issues.append("fact_distillation:legacy_prose_retained")
    distilled_facts = distillation.get("facts")
    if not isinstance(distilled_facts, list) or not distilled_facts:
        issues.append("fact_distillation:missing_structured_facts")
    for fact in distilled_facts or []:
        hashes = fact.get("source_hashes") if isinstance(fact, dict) else None
        if not isinstance(hashes, list) or not hashes or any(
            not _HASH.fullmatch(str(item)) for item in hashes
        ):
            issues.append("fact_distillation:invalid_source_hash")

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
        for record in fragment.get("records") or []:
            if not isinstance(record, dict) or not record.get("id") or not record.get("kind"):
                issues.append(f"canonical:invalid_record:{relative}")
                continue
            record_id = str(record["id"])
            if record_id in records:
                issues.append(f"canonical:duplicate_id:{record_id}")
                continue
            records[record_id] = record
            kinds.add(str(record["kind"]))
    for missing_kind in sorted(REQUIRED_CANONICAL_KINDS - kinds):
        issues.append(f"canonical:missing_kind:{missing_kind}")
    for record_id, record in records.items():
        for ref in sorted(_record_refs(record)):
            if ref not in records:
                issues.append(f"canonical:dangling_ref:{record_id}:{ref}")

    for record_id, record in records.items():
        if record.get("kind") != "relationship" or record.get("adult_intimacy") is not True:
            continue
        for participant in record.get("participants") or []:
            character = records.get(str(participant)) or {}
            if character.get("kind") != "character" or int(character.get("age") or 0) < 18:
                issues.append(f"canonical:adult_boundary:{record_id}:{participant}")

    state_updates: dict[tuple[str, str, str, str], Any] = {}
    updates_by_subject: dict[tuple[str, str, str], list[tuple[int, Any]]] = defaultdict(list)
    for record_id, record in records.items():
        worldline = str(record.get("worldline_ref") or "default")
        time_index = int(record.get("time_index") or 0)
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
    indexed_chapters = [
        int(item)
        for item in (
            card_index.get("chapters")
            or [
                entry.get("chapter")
                for entry in card_index.get("chapter_state_plan") or []
                if isinstance(entry, dict)
            ]
        )
    ]
    if indexed_chapters != expected_chapters:
        issues.append("chapter_cards:index_not_exact_range")
    from agent_runtime.narrative_delivery import validate_chapter_state_plan

    state_plan_validation = validate_chapter_state_plan(
        project_root,
        "production/chapter_cards/index.yml",
        expected_chapters=expected_chapters,
    )
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
        if int(card.get("chapter") or 0) != chapter:
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
            for ref in refs or []:
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
