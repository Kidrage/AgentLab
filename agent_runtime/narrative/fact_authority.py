"""Single-lineage authority for field-level narrative fact overrides."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping, MutableMapping

import yaml


FACT_AUTHORITY_SCHEMA = "narrative-fact-authority/v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ENTITY_TARGETS = {
    "characters",
    "relationships",
    "foreshadowing",
    "world_axes",
}


def load_fact_authority(
    path: Path,
    *,
    project: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Load and validate one active authority revision and return its file hash."""

    source = Path(path).resolve(strict=True)
    try:
        source_bytes = source.read_bytes()
        document = yaml.safe_load(source_bytes.decode("utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"fact authority is not valid UTF-8 YAML: {source}") from exc
    if not isinstance(document, dict):
        raise ValueError("fact authority must be a mapping")
    normalized = validate_fact_authority(document, project=project)
    return normalized, hashlib.sha256(source_bytes).hexdigest()


def validate_fact_authority(
    document: Mapping[str, Any],
    *,
    project: str | None = None,
    allow_legacy_semantic_authority: bool = False,
) -> dict[str, Any]:
    """Validate the closed schema used by the current authority revision."""

    if document.get("schema_version") != FACT_AUTHORITY_SCHEMA:
        raise ValueError(f"fact authority schema must be {FACT_AUTHORITY_SCHEMA}")
    authority_project = str(document.get("project") or "").strip()
    if not authority_project:
        raise ValueError("fact authority project is required")
    if project is not None and authority_project != project:
        raise ValueError("fact authority project mismatch")
    authority_id = str(document.get("authority_id") or "").strip()
    if not authority_id:
        raise ValueError("fact authority authority_id is required")
    revision = document.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("fact authority revision must be a positive integer")
    if document.get("status") != "active":
        raise ValueError("fact authority status must be active")
    effective_at = str(document.get("effective_at") or "").strip()
    if not effective_at:
        raise ValueError("fact authority effective_at is required")
    supersedes = document.get("supersedes_authority_sha256")
    if supersedes is not None and not _SHA256.fullmatch(str(supersedes)):
        raise ValueError(
            "fact authority supersedes_authority_sha256 must be null or lowercase 64-hex"
        )
    facts = document.get("facts")
    if not isinstance(facts, list) or not facts:
        raise ValueError("fact authority facts must be a non-empty list")

    seen_fact_ids: set[str] = set()
    seen_fields: set[tuple[str, str, str]] = set()
    for fact in facts:
        if not isinstance(fact, Mapping):
            raise ValueError("fact authority fact must be a mapping")
        fact_id = str(fact.get("fact_id") or "").strip()
        target = str(fact.get("target") or "").strip()
        entity_id = str(fact.get("entity_id") or "").strip()
        field = str(fact.get("field") or "").strip()
        if not fact_id or fact_id in seen_fact_ids:
            raise ValueError(f"fact authority fact_id is missing or duplicated: {fact_id}")
        if target not in _ENTITY_TARGETS:
            raise ValueError(f"fact authority target is unsupported: {target}")
        if not entity_id:
            raise ValueError(f"fact authority entity_id is required: {fact_id}")
        if not field or any(not part for part in field.split(".")):
            raise ValueError(f"fact authority field is invalid: {fact_id}")
        key = (target, entity_id, field)
        if key in seen_fields:
            raise ValueError(
                f"fact authority defines more than one value for {target}.{entity_id}.{field}"
            )
        if "value" not in fact:
            raise ValueError(f"fact authority value is required: {fact_id}")
        seen_fact_ids.add(fact_id)
        seen_fields.add(key)

    evidence_policy = document.get("evidence_policy")
    if revision >= 2 and evidence_policy is None:
        raise ValueError(
            "fact authority revision 2+ requires an evidence_policy"
        )
    if evidence_policy is not None:
        if not isinstance(evidence_policy, Mapping):
            raise ValueError("fact authority evidence_policy must be a mapping")
        semantic_authority = evidence_policy.get("sole_semantic_authority")
        if semantic_authority != "project_brain/narrative_state_events.jsonl" and not (
            allow_legacy_semantic_authority
            and revision == 1
            and semantic_authority == "production/fact_authority.yml"
        ):
            raise ValueError(
                "fact authority sole_semantic_authority must be the narrative event ledger"
            )
        projections = evidence_policy.get("projections")
        if not isinstance(projections, list) or not projections:
            raise ValueError(
                "fact authority evidence_policy projections must be non-empty"
            )
        registries = evidence_policy.get("registries", [])
        if not isinstance(registries, list):
            raise ValueError("fact authority evidence_policy registries must be a list")
        seen_paths: set[str] = set()
        for raw_path in [*projections, *registries]:
            path = _validated_relative_path(raw_path)
            if path in seen_paths:
                raise ValueError(f"fact authority evidence path is duplicated: {path}")
            seen_paths.add(path)
    return deepcopy(dict(document))


def _validated_relative_path(value: Any) -> str:
    pure = PurePosixPath(str(value or ""))
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError(f"fact authority evidence path is unsafe: {value!r}")
    return pure.as_posix()


def _project_file(project_root: Path, relative: str) -> Path:
    root = Path(project_root).resolve(strict=True)
    normalized = _validated_relative_path(relative)
    cursor = root
    try:
        for part in PurePosixPath(normalized).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError(
                    f"fact authority evidence path is unsafe: {normalized}"
                )
        path = cursor.resolve(strict=True)
    except OSError as exc:
        raise ValueError(
            f"fact authority evidence path is missing: {normalized}"
        ) from exc
    if root not in path.parents or not path.is_file():
        raise ValueError(f"fact authority evidence path is unsafe: {normalized}")
    return path


def verify_registered_fact_authority(
    project_root: Path,
    authority: Mapping[str, Any],
    source_sha256: str,
) -> dict[str, Any]:
    """Require the authority revision to be the sole selected production artifact."""

    validated = validate_fact_authority(authority)
    if not _SHA256.fullmatch(str(source_sha256)):
        raise ValueError("fact authority source hash must be lowercase 64-hex")
    root = Path(project_root).resolve(strict=True)
    index_path = root / "project_artifact_index.yml"
    try:
        index = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError("project artifact index is missing or invalid") from exc
    if not isinstance(index, Mapping):
        raise ValueError("project artifact index must be a mapping")
    if index.get("schema_version") != 1:
        raise ValueError("project artifact index schema_version must be 1")
    if index.get("project") != validated["project"]:
        raise ValueError("project artifact index project mismatch")
    artifacts = index.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("project artifact index has no artifacts list")
    active_authorities = [
        item
        for item in artifacts
        if isinstance(item, Mapping)
        and item.get("status") == "current"
        and (
            item.get("authority_id") is not None
            or "fact_authority" in str(item.get("artifact_id") or "")
            or str(item.get("production_path") or "").endswith(
                "/fact_authority.yml"
            )
        )
    ]
    if len(active_authorities) != 1:
        raise ValueError(
            "project artifact index must select exactly one current fact authority"
        )
    selected = active_authorities[0]
    if selected.get("production_path") != "production/fact_authority.yml":
        raise ValueError(
            "project artifact index current fact authority path is not canonical"
        )
    if (
        selected.get("production_sha256") != source_sha256
        or selected.get("authority_id") != validated["authority_id"]
        or selected.get("authority_revision") != validated["revision"]
    ):
        raise ValueError("project artifact index fact authority binding mismatch")
    current = index.get("current")
    artifact_id = str(selected.get("artifact_id") or "")
    if (
        not artifact_id
        or not isinstance(current, Mapping)
        or current.get(artifact_id) != "production/fact_authority.yml"
        or sum(
            1
            for path in current.values()
            if path == "production/fact_authority.yml"
        )
        != 1
    ):
        raise ValueError("project artifact index current fact authority is not unique")
    return deepcopy(dict(selected))


def _projection_records(
    document: Mapping[str, Any],
    *,
    target: str,
) -> Mapping[str, Any] | None:
    direct = document.get(target)
    if isinstance(direct, Mapping):
        return direct
    records = document.get("records")
    if isinstance(records, list):
        by_id: dict[str, Any] = {}
        for raw in records:
            if not isinstance(raw, Mapping):
                continue
            entity_id = str(raw.get("id") or "").strip()
            if entity_id:
                by_id[entity_id] = raw
        return by_id
    entity_id = str(document.get("id") or "").strip()
    if entity_id:
        return {entity_id: document}
    return None


def _assert_fact_authority_registry(
    document: Mapping[str, Any],
    authority: Mapping[str, Any],
    source_sha256: str,
) -> None:
    records = document.get("facts")
    if not isinstance(records, list):
        raise ValueError("fact authority registry has no facts list")
    matches = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        value = record.get("value")
        if (
            isinstance(value, Mapping)
            and value.get("authority_id") == authority["authority_id"]
        ):
            matches.append(value)
    if len(matches) != 1:
        raise ValueError(
            "fact authority registry must contain exactly one active authority record"
        )
    registered = matches[0]
    if (
        registered.get("authority_revision") != authority["revision"]
        or registered.get("authority_path") != "production/fact_authority.yml"
        or registered.get("authority_sha256") != source_sha256
    ):
        raise ValueError("fact authority registry binding mismatch")
    expected_ages = {
        fact["entity_id"]: fact["value"]
        for fact in authority["facts"]
        if fact["target"] == "characters" and fact["field"] == "age"
    }
    if expected_ages and registered.get("current_age_projection") != expected_ages:
        raise ValueError("fact authority registry age projection mismatch")


def assert_fact_authority_evidence(
    project_root: Path,
    authority: Mapping[str, Any],
    *,
    source_sha256: str,
) -> None:
    """Validate every declared projection and registry against one revision."""

    validated = validate_fact_authority(authority)
    policy = validated.get("evidence_policy")
    if not isinstance(policy, Mapping):
        return
    targets = {fact["target"] for fact in validated["facts"]}
    for relative in policy["projections"]:
        path = _project_file(project_root, str(relative))
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ValueError(
                f"fact authority projection is invalid: {relative}"
            ) from exc
        if not isinstance(document, Mapping):
            raise ValueError(f"fact authority projection is invalid: {relative}")
        state: dict[str, Any] = {}
        for target in targets:
            records = _projection_records(document, target=target)
            if records is not None:
                state[target] = records
        assert_fact_authority_projection(state, validated)
    for relative in policy.get("registries", []):
        path = _project_file(project_root, str(relative))
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ValueError(f"fact authority registry is invalid: {relative}") from exc
        if not isinstance(document, Mapping):
            raise ValueError(f"fact authority registry is invalid: {relative}")
        _assert_fact_authority_registry(document, validated, source_sha256)


def _field_value(record: Mapping[str, Any], field: str) -> Any:
    cursor: Any = record
    for part in field.split("."):
        if not isinstance(cursor, Mapping) or part not in cursor:
            raise ValueError(f"fact authority projection field is missing: {field}")
        cursor = cursor[part]
    return cursor


def _set_field(record: MutableMapping[str, Any], field: str, value: Any) -> None:
    parts = field.split(".")
    cursor: MutableMapping[str, Any] = record
    for part in parts[:-1]:
        child = cursor.get(part)
        if not isinstance(child, MutableMapping):
            raise ValueError(f"fact authority target field is not a mapping: {field}")
        cursor = child
    cursor[parts[-1]] = deepcopy(value)


def assert_fact_authority_projection(
    state: Mapping[str, Any],
    authority: Mapping[str, Any],
) -> None:
    """Fail closed when a derived state disagrees with its sole authority."""

    validated = validate_fact_authority(authority)
    for fact in validated["facts"]:
        target = fact["target"]
        entity_id = fact["entity_id"]
        records = state.get(target)
        if not isinstance(records, Mapping) or not isinstance(
            records.get(entity_id), Mapping
        ):
            raise ValueError(
                f"fact authority projection target is missing: {target}.{entity_id}"
            )
        actual = _field_value(records[entity_id], fact["field"])
        if actual != fact["value"]:
            raise ValueError(
                "fact authority projection mismatch: "
                f"{target}.{entity_id}.{fact['field']}"
            )


def apply_fact_authority(
    state: MutableMapping[str, Any],
    authority: Mapping[str, Any],
    *,
    allow_legacy_semantic_authority: bool = False,
) -> None:
    """Apply one validated authority revision to a mutable state projection."""

    validated = validate_fact_authority(
        authority,
        allow_legacy_semantic_authority=allow_legacy_semantic_authority,
    )
    for fact in validated["facts"]:
        target = fact["target"]
        entity_id = fact["entity_id"]
        records = state.get(target)
        if not isinstance(records, MutableMapping) or not isinstance(
            records.get(entity_id), MutableMapping
        ):
            raise ValueError(
                f"fact authority target is missing: {target}.{entity_id}"
            )
        _set_field(records[entity_id], fact["field"], fact["value"])


__all__ = [
    "FACT_AUTHORITY_SCHEMA",
    "apply_fact_authority",
    "assert_fact_authority_evidence",
    "assert_fact_authority_projection",
    "load_fact_authority",
    "validate_fact_authority",
    "verify_registered_fact_authority",
]
