"""Compile bounded, evidence-bound literary memory for one chapter."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
from typing import Any

import yaml

from agent_runtime.atomic_io import atomic_write_text


MEMORY_CATEGORIES: tuple[str, ...] = (
    "voice_examples",
    "emotional_debts",
    "life_detail_anchors",
    "recent_scene_signatures",
    "unresolved_reader_questions",
)

MEMORY_REASON_CODES: dict[str, str] = {
    "voice_examples": "same_pov_or_character_voice",
    "emotional_debts": "unresolved_relationship_or_obligation",
    "life_detail_anchors": "concrete_carried_life_detail",
    "recent_scene_signatures": "recent_scene_pattern",
    "unresolved_reader_questions": "open_reader_question",
}

MEMORY_CHAPTER_WINDOW = 5
MAX_ITEMS_PER_CATEGORY = 3
MAX_UNIQUE_SOURCES = 8
MAX_SELECTION_BYTES = 128 * 1024
MAX_SOURCE_BYTES = 256 * 1024
MAX_TOTAL_SOURCE_BYTES = 512 * 1024
MAX_EXCERPT_CHARS = 1000
MAX_LINE_RANGE = 20
MAX_APPLIES_TO = 8

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_CHAPTER_PATH_RE = re.compile(
    r"(?:^|[_-])(?:chapter|ch)[_-]?0*(\d+)(?=[_.-]|$)",
    flags=re.IGNORECASE,
)
_YAML_PATH_SEGMENT_RE = re.compile(
    r"^(?P<key>[A-Za-z_][A-Za-z0-9_-]*)(?P<indexes>(?:\[\d+\])*)$"
)
_YAML_PATH_INDEX_RE = re.compile(r"\[(\d+)\]")


@dataclass
class LiteraryMemoryResult:
    chapter_id: int
    status: str
    snapshot_path: str = ""
    snapshot_sha256: str = ""
    source_paths: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    metrics: dict[str, int] = field(default_factory=dict)
    candidate_only: bool = True
    production_modified: bool = False


@dataclass(frozen=True)
class _SourceArtifact:
    path: Path
    relative_path: str
    raw: bytes
    text: str
    sha256: str


@dataclass(frozen=True)
class _ChapterObservation:
    chapter_id: int | None = None
    conflicting_authorities: bool = False


def compile_literary_memory_snapshot(
    *,
    project_id: str,
    chapter_id: int,
    selection_path: str | Path | None,
    output_path: str | Path | None,
    source_root: str | Path | None,
) -> LiteraryMemoryResult:
    """Validate a bounded selection and atomically write a schema-v2 snapshot.

    Selection schemas v1 and v2 are read. V1 selections retain compatibility by
    deriving a line locator from the submitted exact excerpt; every snapshot is
    written as v2. New selections must use v2 machine-verifiable locators and a
    category-specific relevance declaration.
    """
    safe_chapter_id = chapter_id if _is_positive_int(chapter_id) else 0
    issues: list[str] = []
    metrics = {
        "selection_read_count": 0,
        "source_read_count": 0,
        "unique_source_count": 0,
        "duplicate_source_reloads": 0,
        "selection_bytes_loaded": 0,
        "source_bytes_loaded": 0,
    }
    if safe_chapter_id == 0:
        issues.append("memory_chapter_id_must_be_positive_integer")
    safe_project_id = str(project_id or "").strip()
    if not _PROJECT_ID_RE.fullmatch(safe_project_id):
        issues.append("memory_project_id_invalid")

    root = _resolve_path(source_root, "memory_source_root_unresolvable", issues)
    raw_selection_path = _coerce_path(
        selection_path, "memory_selection_path_unresolvable", issues
    )
    raw_output_path = _coerce_path(
        output_path, "memory_output_path_unresolvable", issues
    )
    if raw_output_path is not None and raw_output_path.is_symlink():
        issues.append("memory_output_must_not_be_symlink")
    if root is None:
        return _blocked(safe_chapter_id, issues, metrics)

    selection = (
        _resolve_path(raw_selection_path, "memory_selection_path_unresolvable", issues)
        if raw_selection_path is not None
        else None
    )
    output = (
        _resolve_path(raw_output_path, "memory_output_path_unresolvable", issues)
        if raw_output_path is not None
        else None
    )
    selection_relative = _relative_to_root(
        selection, root, "memory_selection_outside_source_root", issues
    )
    output_relative = _relative_to_root(
        output, root, "memory_output_outside_source_root", issues
    )
    if output_relative is not None and not _is_candidate_snapshot_path(
        output_relative, safe_project_id
    ):
        issues.append("memory_output_must_be_candidate_snapshot")
    if selection is not None and output is not None and selection == output:
        issues.append("memory_output_must_not_overwrite_selection")

    selection_raw = b""
    selection_data: Any = {}
    if selection is not None and selection_relative is not None:
        selection_raw = _read_bounded_bytes(
            selection,
            MAX_SELECTION_BYTES,
            "memory_selection",
            issues,
        )
        if selection_raw:
            metrics["selection_read_count"] = 1
            metrics["selection_bytes_loaded"] = len(selection_raw)
            selection_data = _decode_yaml(
                selection_raw,
                "memory_selection",
                issues,
            )
    if not isinstance(selection_data, dict):
        selection_data = {}
        issues.append("memory_selection_root_must_be_mapping")

    selection_schema = selection_data.get("schema_version")
    if selection_schema not in (1, 2):
        issues.append("memory_selection_schema_version_must_be_1_or_2")
    selected_chapter = selection_data.get("chapter_id")
    if not _is_positive_int(selected_chapter) or selected_chapter != safe_chapter_id:
        issues.append("memory_selection_chapter_mismatch")
    if selection_data.get("candidate_only") is not True:
        issues.append("memory_selection_must_be_candidate_only")
    if selection_data.get("production_modified") is not False:
        issues.append("memory_selection_production_modified_must_be_false")

    categories = selection_data.get("categories") or {}
    if not isinstance(categories, dict):
        categories = {}
        issues.append("memory_categories_must_be_mapping")

    source_cache: dict[str, _SourceArtifact | None] = {}
    source_inventory: dict[str, dict[str, Any]] = {}
    compiled_categories: dict[str, list[dict[str, Any]]] = {}
    used_text_hashes: set[str] = set()
    used_line_ranges: dict[str, list[tuple[int, int]]] = {}
    legacy_item_count = 0

    for category in MEMORY_CATEGORIES:
        items = categories.get(category) or []
        if not isinstance(items, list) or not items:
            issues.append(f"memory_category_missing:{category}")
            continue
        if len(items) > MAX_ITEMS_PER_CATEGORY:
            issues.append(f"memory_category_item_limit_exceeded:{category}")
            continue
        compiled_items: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                issues.append(f"memory_item_must_be_mapping:{category}:{index}")
                continue
            source_ref = item.get("source") or {}
            if not isinstance(source_ref, dict):
                issues.append(f"memory_source_must_be_mapping:{category}:{index}")
                continue
            relative = str(source_ref.get("path") or "").strip()
            declared_hash = str(source_ref.get("sha256") or "").strip().lower()
            if not _SHA256_RE.fullmatch(declared_hash):
                issues.append(f"memory_source_sha256_invalid:{category}:{index}")
                continue
            artifact = _load_source_once(
                root=root,
                project_id=safe_project_id,
                relative=relative,
                cache=source_cache,
                metrics=metrics,
                issues=issues,
            )
            if artifact is None:
                continue
            if artifact.sha256 != declared_hash:
                issues.append(f"memory_source_hash_mismatch:{artifact.relative_path}")
                continue

            if selection_schema == 2:
                relevance = _validate_relevance(
                    item.get("relevance"),
                    category=category,
                    chapter_id=safe_chapter_id,
                    index=index,
                    issues=issues,
                )
                extracted = _extract_v2_locator(
                    artifact,
                    item.get("locator"),
                    category=category,
                    index=index,
                    issues=issues,
                )
            else:
                relevance = {
                    "reason_code": "legacy_explicit_selection",
                    "source_chapter_id": safe_chapter_id,
                    "applies_to": ["legacy_selection"],
                }
                extracted = _extract_v1_excerpt(
                    artifact,
                    item,
                    category=category,
                    index=index,
                    issues=issues,
                )
                legacy_item_count += 1
            if relevance is None or extracted is None:
                continue
            text, locator = extracted
            chapter_observation = _observed_source_chapter_id(artifact, locator)
            if chapter_observation.conflicting_authorities:
                issues.append(f"memory_source_chapter_conflict:{category}:{index}")
                continue
            observed_chapter_id = chapter_observation.chapter_id
            if observed_chapter_id is None:
                issues.append(f"memory_source_chapter_unverifiable:{category}:{index}")
                continue
            if selection_schema == 2:
                if relevance["source_chapter_id"] != observed_chapter_id:
                    issues.append(f"memory_source_chapter_mismatch:{category}:{index}")
                    continue
            else:
                relevance["source_chapter_id"] = observed_chapter_id
                if not _chapter_is_in_window(observed_chapter_id, safe_chapter_id):
                    issues.append(
                        f"memory_relevance_chapter_outside_window:{category}:{index}"
                    )
                    continue
            if _evidence_is_reused(
                artifact=artifact,
                text=text,
                locator=locator,
                used_text_hashes=used_text_hashes,
                used_line_ranges=used_line_ranges,
            ):
                issues.append(f"memory_evidence_reused_across_categories:{category}:{index}")
                continue
            source_inventory[artifact.relative_path] = {
                "path": artifact.relative_path,
                "sha256": artifact.sha256,
                "bytes": len(artifact.raw),
            }
            compiled_items.append(
                {
                    "text": text,
                    "source_path": artifact.relative_path,
                    "source_sha256": artifact.sha256,
                    "locator": locator,
                    "relevance": relevance,
                }
            )
        if compiled_items:
            compiled_categories[category] = compiled_items

    metrics["unique_source_count"] = len(source_cache)
    if issues:
        return _blocked(safe_chapter_id, issues, metrics)

    source_hashes = {
        path: item["sha256"] for path, item in sorted(source_inventory.items())
    }
    snapshot = {
        "schema_version": 2,
        "chapter_id": safe_chapter_id,
        "candidate_only": True,
        "production_modified": False,
        "memory_contract_complete": all(
            compiled_categories.get(category) for category in MEMORY_CATEGORIES
        ),
        "quality_equivalent_memory_complete": (
            selection_schema == 2
            and all(compiled_categories.get(category) for category in MEMORY_CATEGORIES)
        ),
        "selection": {
            "path": selection_relative.as_posix() if selection_relative else "",
            "sha256": hashlib.sha256(selection_raw).hexdigest(),
            "schema_version": selection_schema,
        },
        "derivation": {
            "compiler": "literary_memory_v2",
            "chapter_window": MEMORY_CHAPTER_WINDOW,
            "legacy_item_count": legacy_item_count,
            "source_inventory": [
                source_inventory[path] for path in sorted(source_inventory)
            ],
        },
        "limits": {
            "max_items_per_category": MAX_ITEMS_PER_CATEGORY,
            "max_unique_sources": MAX_UNIQUE_SOURCES,
            "max_selection_bytes": MAX_SELECTION_BYTES,
            "max_source_bytes": MAX_SOURCE_BYTES,
            "max_total_source_bytes": MAX_TOTAL_SOURCE_BYTES,
            "max_excerpt_chars": MAX_EXCERPT_CHARS,
            "max_line_range": MAX_LINE_RANGE,
        },
        "source_hashes": source_hashes,
        "metrics": metrics,
        "categories": compiled_categories,
    }
    serialized = yaml.safe_dump(snapshot, sort_keys=False, allow_unicode=True)
    try:
        atomic_write_text(output, serialized, encoding="utf-8")
    except OSError:
        return _blocked(
            safe_chapter_id,
            ["memory_output_write_failed"],
            metrics,
        )
    return LiteraryMemoryResult(
        chapter_id=safe_chapter_id,
        status="pass",
        snapshot_path=str(output),
        snapshot_sha256=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        source_paths=sorted(source_hashes),
        metrics=dict(metrics),
    )


def _blocked(
    chapter_id: int,
    issues: list[str],
    metrics: dict[str, int],
) -> LiteraryMemoryResult:
    return LiteraryMemoryResult(
        chapter_id=chapter_id,
        status="blocked",
        issues=list(dict.fromkeys(issues)),
        metrics=dict(metrics),
    )


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _coerce_path(value: Any, issue: str, issues: list[str]) -> Path | None:
    try:
        return Path(value)
    except (OSError, RuntimeError, ValueError, TypeError):
        issues.append(issue)
        return None


def _resolve_path(path: Any, issue: str, issues: list[str]) -> Path | None:
    try:
        return Path(path).resolve()
    except (OSError, RuntimeError, ValueError, TypeError):
        issues.append(issue)
        return None


def _relative_to_root(
    path: Path | None,
    root: Path,
    issue: str,
    issues: list[str],
) -> Path | None:
    if path is None:
        return None
    try:
        return path.relative_to(root)
    except ValueError:
        issues.append(issue)
        return None


def _is_candidate_snapshot_path(relative: Path, project_id: str) -> bool:
    parts = relative.parts
    return (
        len(parts) >= 5
        and parts[0] == "projects"
        and parts[1] == project_id
        and parts[2] == "candidates"
        and bool(parts[3])
        and parts[-1] == "narrative_memory_snapshot.yml"
    )


def _read_bounded_bytes(
    path: Path,
    limit: int,
    prefix: str,
    issues: list[str],
) -> bytes:
    try:
        with path.open("rb") as handle:
            raw = handle.read(limit + 1)
    except OSError:
        issues.append(f"{prefix}_unreadable")
        return b""
    if len(raw) > limit:
        issues.append(f"{prefix}_size_limit_exceeded")
        return b""
    if not raw:
        issues.append(f"{prefix}_empty")
    return raw


def _decode_yaml(raw: bytes, prefix: str, issues: list[str]) -> Any:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        issues.append(f"{prefix}_must_be_utf8")
        return {}
    try:
        return yaml.safe_load(text) or {}
    except yaml.YAMLError:
        issues.append(f"{prefix}_yaml_invalid")
        return {}


def _load_source_once(
    *,
    root: Path,
    project_id: str,
    relative: str,
    cache: dict[str, _SourceArtifact | None],
    metrics: dict[str, int],
    issues: list[str],
) -> _SourceArtifact | None:
    resolved = _resolve_source(root, project_id, relative, issues)
    if resolved is None:
        return None
    source, normalized_relative = resolved
    if normalized_relative in cache:
        return cache[normalized_relative]
    if len(cache) >= MAX_UNIQUE_SOURCES:
        issues.append("memory_unique_source_limit_exceeded")
        return None
    raw = _read_bounded_bytes(source, MAX_SOURCE_BYTES, "memory_source", issues)
    if not raw:
        cache[normalized_relative] = None
        return None
    metrics["source_read_count"] += 1
    metrics["source_bytes_loaded"] += len(raw)
    if metrics["source_bytes_loaded"] > MAX_TOTAL_SOURCE_BYTES:
        issues.append("memory_total_source_bytes_limit_exceeded")
        cache[normalized_relative] = None
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        issues.append(f"memory_source_must_be_utf8:{normalized_relative}")
        cache[normalized_relative] = None
        return None
    artifact = _SourceArtifact(
        path=source,
        relative_path=normalized_relative,
        raw=raw,
        text=text,
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    cache[normalized_relative] = artifact
    return artifact


def _resolve_source(
    root: Path,
    project_id: str,
    relative: str,
    issues: list[str],
) -> tuple[Path, str] | None:
    if not relative or Path(relative).is_absolute():
        issues.append("memory_source_path_must_be_relative")
        return None
    source = _resolve_path(root / relative, "memory_source_path_unresolvable", issues)
    canonical = _relative_to_root(
        source,
        root,
        f"memory_source_outside_root:{relative}",
        issues,
    )
    if source is None or canonical is None:
        return None
    expected_project_root = Path("projects") / project_id
    try:
        canonical.relative_to(expected_project_root)
    except ValueError:
        issues.append(f"memory_source_outside_project:{relative}")
        return None
    if not source.is_file():
        issues.append(f"memory_source_missing:{relative}")
        return None
    return source, canonical.as_posix()


def _observed_source_chapter_id(
    artifact: _SourceArtifact,
    locator: dict[str, Any],
) -> _ChapterObservation:
    if locator.get("kind") == "yaml_path":
        observed = _yaml_locator_chapter_id(
            artifact.raw,
            str(locator.get("value") or ""),
        )
        if observed.conflicting_authorities or observed.chapter_id is not None:
            return observed
    path_matches = {
        int(match)
        for part in Path(artifact.relative_path).parts
        for match in _CHAPTER_PATH_RE.findall(part)
    }
    if len(path_matches) == 1:
        return _ChapterObservation(chapter_id=next(iter(path_matches)))
    return _ChapterObservation()


def _yaml_locator_chapter_id(raw: bytes, path: str) -> _ChapterObservation:
    try:
        current: Any = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError):
        return _ChapterObservation()
    observed: set[int] = set()
    for segment in path.split("."):
        match = _YAML_PATH_SEGMENT_RE.fullmatch(segment)
        if match is None or not isinstance(current, dict):
            return _ChapterObservation()
        _collect_mapping_chapter_id(current, observed)
        key = match.group("key")
        if key not in current:
            return _ChapterObservation()
        current = current[key]
        for raw_index in _YAML_PATH_INDEX_RE.findall(match.group("indexes")):
            item_index = int(raw_index)
            if not isinstance(current, list) or item_index >= len(current):
                return _ChapterObservation()
            current = current[item_index]
            if isinstance(current, dict):
                _collect_mapping_chapter_id(current, observed)
    if isinstance(current, dict):
        _collect_mapping_chapter_id(current, observed)
    if len(observed) == 1:
        return _ChapterObservation(chapter_id=next(iter(observed)))
    if len(observed) > 1:
        return _ChapterObservation(conflicting_authorities=True)
    return _ChapterObservation()


def _collect_mapping_chapter_id(mapping: dict[str, Any], observed: set[int]) -> None:
    for key in ("chapter_id", "chapter", "chapter_number"):
        value = mapping.get(key)
        if _is_positive_int(value):
            observed.add(value)


def _chapter_is_in_window(source_chapter_id: int, chapter_id: int) -> bool:
    return (
        source_chapter_id <= chapter_id
        and source_chapter_id >= max(1, chapter_id - MEMORY_CHAPTER_WINDOW)
    )


def _evidence_is_reused(
    *,
    artifact: _SourceArtifact,
    text: str,
    locator: dict[str, Any],
    used_text_hashes: set[str],
    used_line_ranges: dict[str, list[tuple[int, int]]],
) -> bool:
    normalized_text = " ".join(text.split()).casefold()
    text_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    if text_hash in used_text_hashes:
        return True
    if locator.get("kind") == "line_range":
        start = int(locator["start"])
        end = int(locator["end"])
        ranges = used_line_ranges.setdefault(artifact.relative_path, [])
        if any(max(start, old_start) <= min(end, old_end) for old_start, old_end in ranges):
            return True
        ranges.append((start, end))
    used_text_hashes.add(text_hash)
    return False


def _validate_relevance(
    raw: Any,
    *,
    category: str,
    chapter_id: int,
    index: int,
    issues: list[str],
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        issues.append(f"memory_relevance_must_be_mapping:{category}:{index}")
        return None
    reason_code = str(raw.get("reason_code") or "").strip()
    source_chapter_id = raw.get("source_chapter_id")
    applies_to = raw.get("applies_to")
    valid = True
    if reason_code != MEMORY_REASON_CODES[category]:
        issues.append(f"memory_relevance_reason_invalid:{category}:{index}")
        valid = False
    if not _is_positive_int(source_chapter_id) or not _chapter_is_in_window(
        source_chapter_id, chapter_id
    ):
        issues.append(f"memory_relevance_chapter_outside_window:{category}:{index}")
        valid = False
    if (
        not isinstance(applies_to, list)
        or not applies_to
        or len(applies_to) > MAX_APPLIES_TO
        or any(not isinstance(value, str) or not value.strip() for value in applies_to)
    ):
        issues.append(f"memory_relevance_applies_to_invalid:{category}:{index}")
        valid = False
    if not valid:
        return None
    return {
        "reason_code": reason_code,
        "source_chapter_id": source_chapter_id,
        "applies_to": [value.strip() for value in applies_to],
    }


def _extract_v2_locator(
    artifact: _SourceArtifact,
    raw: Any,
    *,
    category: str,
    index: int,
    issues: list[str],
) -> tuple[str, dict[str, Any]] | None:
    if not isinstance(raw, dict):
        issues.append(f"memory_locator_must_be_mapping:{category}:{index}")
        return None
    kind = str(raw.get("kind") or "").strip()
    if kind == "line_range":
        start = raw.get("start")
        end = raw.get("end")
        if (
            not _is_positive_int(start)
            or not _is_positive_int(end)
            or end < start
            or end - start + 1 > MAX_LINE_RANGE
        ):
            issues.append(f"memory_line_range_invalid:{category}:{index}")
            return None
        lines = artifact.text.splitlines()
        if end > len(lines):
            issues.append(f"memory_line_range_outside_source:{category}:{index}")
            return None
        text = "\n".join(lines[start - 1 : end]).strip()
        locator = {"kind": "line_range", "start": start, "end": end}
    elif kind == "yaml_path":
        value = str(raw.get("value") or "").strip()
        text = _extract_yaml_path(
            artifact.raw,
            value,
            category=category,
            index=index,
            issues=issues,
        )
        if text is None:
            return None
        locator = {"kind": "yaml_path", "value": value}
    else:
        issues.append(f"memory_locator_kind_invalid:{category}:{index}")
        return None
    if not text:
        issues.append(f"memory_locator_empty:{category}:{index}")
        return None
    if len(text) > MAX_EXCERPT_CHARS:
        issues.append(f"memory_excerpt_size_limit_exceeded:{category}:{index}")
        return None
    return text, locator


def _extract_yaml_path(
    raw: bytes,
    path: str,
    *,
    category: str,
    index: int,
    issues: list[str],
) -> str | None:
    if not path:
        issues.append(f"memory_yaml_path_invalid:{category}:{index}")
        return None
    try:
        current: Any = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError):
        issues.append(f"memory_yaml_source_invalid:{category}:{index}")
        return None
    for segment in path.split("."):
        match = _YAML_PATH_SEGMENT_RE.fullmatch(segment)
        if match is None or not isinstance(current, dict):
            issues.append(f"memory_yaml_path_unresolved:{category}:{index}")
            return None
        key = match.group("key")
        if key not in current:
            issues.append(f"memory_yaml_path_unresolved:{category}:{index}")
            return None
        current = current[key]
        for raw_index in _YAML_PATH_INDEX_RE.findall(match.group("indexes")):
            item_index = int(raw_index)
            if not isinstance(current, list) or item_index >= len(current):
                issues.append(f"memory_yaml_path_unresolved:{category}:{index}")
                return None
            current = current[item_index]
    if not isinstance(current, str):
        issues.append(f"memory_yaml_path_must_resolve_to_text:{category}:{index}")
        return None
    return current.strip()


def _extract_v1_excerpt(
    artifact: _SourceArtifact,
    item: dict[str, Any],
    *,
    category: str,
    index: int,
    issues: list[str],
) -> tuple[str, dict[str, Any]] | None:
    text = str(item.get("text") or "").strip()
    legacy_locator = str(item.get("locator") or "").strip()
    if not text or not legacy_locator:
        issues.append(f"memory_item_fields_missing:{category}:{index}")
        return None
    if len(text) > MAX_EXCERPT_CHARS:
        issues.append(f"memory_excerpt_size_limit_exceeded:{category}:{index}")
        return None
    offset = artifact.text.find(text)
    if offset < 0:
        issues.append(f"memory_excerpt_not_found:{category}:{index}")
        return None
    start = artifact.text.count("\n", 0, offset) + 1
    end = start + text.count("\n")
    if end - start + 1 > MAX_LINE_RANGE:
        issues.append(f"memory_line_range_invalid:{category}:{index}")
        return None
    return text, {
        "kind": "line_range",
        "start": start,
        "end": end,
        "legacy_label": legacy_locator,
    }
