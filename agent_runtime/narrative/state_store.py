"""Append-only narrative authority for long-form state.

The event ledger is authoritative.  YAML snapshots are deterministic egress
projections and may always be rebuilt from the ledger.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterator, Mapping

import yaml

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.narrative.fact_authority import (
    apply_fact_authority,
    load_fact_authority,
    verify_registered_fact_authority,
)
from agent_runtime.narrative.long_term_state import (
    apply_long_term_delta,
    validate_long_term_delta,
)


EVENT_SCHEMA = "narrative-state-event/v3"
SNAPSHOT_SCHEMA = "narrative-state/v3"
EVENTS_FILE = "narrative_state_events.jsonl"
SNAPSHOT_FILE = "narrative_state_snapshot.yml"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class NarrativeStateError(RuntimeError):
    """Base narrative-state failure."""


class NarrativeStateConflict(NarrativeStateError):
    """A commit conflicts with the current append-only authority."""


class NarrativeStateIntegrityError(NarrativeStateError):
    """The narrative ledger or a hash-bound source cannot be trusted."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def narrative_payload_sha256(value: Any) -> str:
    """Return the canonical hash used to bind narrative contracts."""

    return _sha256_json(value)


def _event_hash(event: Mapping[str, Any]) -> str:
    body = {key: value for key, value in event.items() if key != "event_hash"}
    return _sha256_json(body)


def _empty_snapshot(project: str) -> dict[str, Any]:
    return {
        "schema_version": SNAPSHOT_SCHEMA,
        "project": project,
        "series": {},
        "characters": {},
        "relationships": {},
        "foreshadowing": {},
        "world_axes": {},
        "fact_authorities": {},
        "chapters": {},
        "style_memory": [],
        "character_minds": {},
        "relationship_edges": {},
        "narrative_entities": {},
        "promise_graph": {},
        "offstage_actions": {},
        "truth_layers": {},
        "outline_tree": {},
        "summary_tree": {},
        "exact_name_index": {},
        "event_count": 0,
        "last_event_id": None,
        "last_event_sequence": 0,
        "generated_at": None,
        "state_sha256": "",
    }


def _state_hash(snapshot: Mapping[str, Any]) -> str:
    stable = {
        key: value
        for key, value in snapshot.items()
        if key not in {"state_sha256", "generated_at"}
    }
    return _sha256_json(stable)


class NarrativeStateStore:
    """Deep module for bootstrap, reads, and verified chapter commits."""

    def __init__(self, project_brain_dir: Path, *, project: str) -> None:
        self.project_brain_dir = Path(project_brain_dir).resolve(strict=False)
        self.project = str(project or "").strip()
        if not self.project:
            raise ValueError("project is required")

    @property
    def events_path(self) -> Path:
        return self.project_brain_dir / EVENTS_FILE

    @property
    def snapshot_path(self) -> Path:
        return self.project_brain_dir / SNAPSHOT_FILE

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.project_brain_dir.mkdir(parents=True, exist_ok=True)
        path = self.project_brain_dir / ".narrative_state.lock"
        with path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _load_events(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        events: list[dict[str, Any]] = []
        previous_hash: str | None = None
        for line_number, raw in enumerate(
            self.events_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not raw.strip():
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise NarrativeStateIntegrityError(
                    f"invalid narrative event JSON at line {line_number}"
                ) from exc
            if not isinstance(event, dict):
                raise NarrativeStateIntegrityError(
                    f"narrative event at line {line_number} is not a mapping"
                )
            if event.get("schema_version") != EVENT_SCHEMA:
                raise NarrativeStateIntegrityError("unsupported narrative event schema")
            if event.get("project") != self.project:
                raise NarrativeStateIntegrityError("narrative event project mismatch")
            if event.get("sequence") != len(events) + 1:
                raise NarrativeStateIntegrityError("narrative event sequence mismatch")
            if event.get("previous_event_hash") != previous_hash:
                raise NarrativeStateIntegrityError("narrative event hash chain mismatch")
            if event.get("event_hash") != _event_hash(event):
                raise NarrativeStateIntegrityError("narrative event hash mismatch")
            previous_hash = str(event["event_hash"])
            events.append(event)
        return events

    def _new_event(
        self,
        events: list[dict[str, Any]],
        *,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        sequence = len(events) + 1
        event = {
            "schema_version": EVENT_SCHEMA,
            "event_id": f"nse-{sequence:08d}-{_sha256_json(payload)[:12]}",
            "sequence": sequence,
            "project": self.project,
            "event_type": event_type,
            "recorded_at": _utc_now(),
            "previous_event_hash": events[-1]["event_hash"] if events else None,
            "payload": deepcopy(dict(payload)),
        }
        event["event_hash"] = _event_hash(event)
        return event

    def _append_event_to_ledger(self, event: Mapping[str, Any]) -> None:
        """Durably append one event; existing authority bytes are never rewritten."""

        self.project_brain_dir.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical_json(event) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _apply_event(self, snapshot: dict[str, Any], event: Mapping[str, Any]) -> None:
        payload = event.get("payload") or {}
        if event.get("event_type") == "NARRATIVE_BOOTSTRAPPED":
            base_state = payload.get("base_state") or {}
            if not isinstance(base_state, Mapping):
                raise NarrativeStateIntegrityError("bootstrap base_state is not a mapping")
            for key in (
                "series",
                "characters",
                "relationships",
                "foreshadowing",
                "world_axes",
                "fact_authorities",
                "chapters",
                "style_memory",
                "character_minds",
                "relationship_edges",
                "narrative_entities",
                "promise_graph",
                "offstage_actions",
                "truth_layers",
                "outline_tree",
                "summary_tree",
                "exact_name_index",
            ):
                if key in base_state:
                    snapshot[key] = deepcopy(base_state[key])
            snapshot["bootstrap"] = {
                "manifest_sha256": payload.get("manifest_sha256"),
                "precedence": deepcopy(payload.get("precedence") or []),
                "sources": deepcopy(payload.get("sources") or []),
            }
        elif event.get("event_type") == "VERIFIED_CHAPTER_COMMITTED":
            chapter = int(payload["chapter"])
            snapshot["chapters"][str(chapter)] = {
                "artifact_sha256": payload["artifact_sha256"],
                "brief_sha256": payload["brief_sha256"],
                "seal_receipt_sha256": payload["seal"]["receipt_sha256"],
                "delta_receipt_sha256": payload["delta_verification"][
                    "receipt_sha256"
                ],
                "event_id": event["event_id"],
            }
            delta = payload.get("state_delta") or {}
            for update in delta.get("character_updates") or []:
                if isinstance(update, Mapping) and str(update.get("id") or "").strip():
                    target = snapshot["characters"].setdefault(str(update["id"]), {})
                    target.update(
                        deepcopy({key: value for key, value in update.items() if key != "id"})
                    )
            for update in delta.get("relationship_updates") or []:
                if isinstance(update, Mapping) and str(update.get("id") or "").strip():
                    target = snapshot["relationships"].setdefault(str(update["id"]), {})
                    target.update(
                        deepcopy({key: value for key, value in update.items() if key != "id"})
                    )
            for update in delta.get("foreshadow_updates") or []:
                if isinstance(update, Mapping) and str(update.get("id") or "").strip():
                    target = snapshot["foreshadowing"].setdefault(str(update["id"]), {})
                    target.update(
                        deepcopy({key: value for key, value in update.items() if key != "id"})
                    )
                    target["last_touched_chapter"] = chapter
            for update in delta.get("world_updates") or []:
                if isinstance(update, Mapping) and str(update.get("axis") or "").strip():
                    snapshot["world_axes"][str(update["axis"])] = deepcopy(
                        update.get("value")
                    )
            for memory_event in delta.get("style_memory_events") or []:
                if isinstance(memory_event, Mapping):
                    snapshot["style_memory"].append(
                        {
                            **deepcopy(dict(memory_event)),
                            "chapter": chapter,
                            "source_artifact_sha256": payload["artifact_sha256"],
                        }
                    )
            if "long_term_schema" in delta:
                projected = apply_long_term_delta(
                    snapshot,
                    delta,
                    chapter=chapter,
                    prose_sha256=str(payload["artifact_sha256"]),
                )
                for key in (
                    "character_minds",
                    "relationship_edges",
                    "narrative_entities",
                    "promise_graph",
                    "offstage_actions",
                    "truth_layers",
                    "outline_tree",
                    "summary_tree",
                    "exact_name_index",
                    "last_projection",
                ):
                    snapshot[key] = projected[key]
        elif event.get("event_type") == "EDITORIAL_MEMORY_RECORDED":
            polarity = (
                "negative"
                if payload["memory_kind"] == "anti_pattern"
                else "guidance"
            )
            snapshot["style_memory"].append(
                {
                    "rule_id": payload["rule_id"],
                    "memory_kind": payload["memory_kind"],
                    "summary": payload["summary"],
                    "polarity": polarity,
                    "source_artifact_sha256": payload["source_artifact_sha256"],
                    "source_disposition": payload["source_disposition"],
                    "source_locator": payload["source_locator"],
                    "event_id": event["event_id"],
                }
            )
        elif event.get("event_type") == "FACT_AUTHORITY_COMMITTED":
            authority = payload.get("authority") or {}
            if not isinstance(authority, Mapping):
                raise NarrativeStateIntegrityError(
                    "fact authority event payload is not a mapping"
                )
            try:
                apply_fact_authority(
                    snapshot,
                    authority,
                    allow_legacy_semantic_authority=True,
                )
            except ValueError as exc:
                raise NarrativeStateIntegrityError(str(exc)) from exc
            snapshot["fact_authorities"] = {
                authority["authority_id"]: {
                    "revision": authority["revision"],
                    "source_path": payload["source_path"],
                    "source_sha256": payload["source_sha256"],
                    "event_id": event["event_id"],
                }
            }
        elif event.get("event_type") == "NARRATIVE_STATE_ROLLED_BACK":
            restored_state = payload.get("restored_state")
            if (
                not isinstance(restored_state, Mapping)
                or restored_state.get("schema_version") != SNAPSHOT_SCHEMA
                or restored_state.get("project") != self.project
                or restored_state.get("state_sha256")
                != _state_hash(restored_state)
                or payload.get("restored_state_sha256")
                != restored_state.get("state_sha256")
            ):
                raise NarrativeStateIntegrityError(
                    "rollback event restored state is invalid"
                )
            snapshot.clear()
            snapshot.update(deepcopy(dict(restored_state)))
        else:
            raise NarrativeStateIntegrityError(
                f"unsupported narrative event type: {event.get('event_type')}"
            )
        snapshot["event_count"] = int(event["sequence"])
        snapshot["last_event_id"] = event["event_id"]
        snapshot["last_event_sequence"] = int(event["sequence"])
        snapshot["generated_at"] = event["recorded_at"]

    def _project(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        snapshot = _empty_snapshot(self.project)
        for event in events:
            self._apply_event(snapshot, event)
        snapshot["state_sha256"] = _state_hash(snapshot)
        return snapshot

    @staticmethod
    def _active_authority_events(
        events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Resolve the active chapter lineage while retaining immutable history."""

        active: list[dict[str, Any]] = []
        for event in events:
            if event.get("event_type") != "NARRATIVE_STATE_ROLLED_BACK":
                active.append(event)
                continue
            target = int(
                (event.get("payload") or {}).get("target_chapter") or 0
            )
            active = [
                candidate
                for candidate in active
                if candidate.get("event_type")
                != "VERIFIED_CHAPTER_COMMITTED"
                or int(
                    (candidate.get("payload") or {}).get("chapter") or 0
                )
                <= target
            ]
        return active

    def _persist_snapshot(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        snapshot = self._project(events)
        atomic_write_yaml(self.snapshot_path, snapshot)
        return snapshot

    def _verified_receipt(
        self,
        receipt: Mapping[str, Any],
        *,
        label: str,
        expected_schema: str,
        expected_issuer: str,
        identity_field: str = "attempt_id",
    ) -> dict[str, Any]:
        reference = str(receipt.get("receipt_path") or "").strip()
        relative = Path(reference)
        if not reference or relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"{label} receipt_path must be project-relative")
        project_root = self.project_brain_dir.parent.resolve(strict=True)
        cursor = project_root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise NarrativeStateIntegrityError(f"{label} receipt path is unsafe")
        path = (project_root / relative).resolve(strict=True)
        if project_root not in path.parents or not path.is_file():
            raise NarrativeStateIntegrityError(f"{label} receipt path is unsafe")
        expected = str(receipt.get("receipt_sha256") or "")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise NarrativeStateIntegrityError(f"{label} receipt hash mismatch")
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise NarrativeStateIntegrityError(
                f"{label} receipt is not valid UTF-8 YAML"
            ) from exc
        if not isinstance(document, dict):
            raise NarrativeStateIntegrityError(f"{label} receipt must be a mapping")
        if document.get("schema_version") != expected_schema:
            raise NarrativeStateIntegrityError(f"{label} receipt schema mismatch")
        if document.get("issuer") != expected_issuer:
            raise NarrativeStateIntegrityError(f"{label} receipt issuer mismatch")
        for field in (identity_field, "evidence_binding_id"):
            value = document.get(field)
            if not isinstance(value, str) or not value.strip():
                raise NarrativeStateIntegrityError(
                    f"{label} receipt {field} is required"
                )
            if receipt.get(field) != value:
                raise NarrativeStateIntegrityError(
                    f"{label} receipt {field} binding mismatch"
                )
        return document

    def _receipt(self, events: list[dict[str, Any]], event: Mapping[str, Any]) -> dict[str, Any]:
        sequence = int(event["sequence"])
        snapshot = self._project(events[:sequence])
        payload = event.get("payload") or {}
        return {
            "schema_version": "narrative-state-commit-receipt/v1",
            "status": (
                "bootstrapped"
                if event.get("event_type") == "NARRATIVE_BOOTSTRAPPED"
                else "recorded"
                if event.get("event_type") == "EDITORIAL_MEMORY_RECORDED"
                else "overridden"
                if event.get("event_type") == "FACT_AUTHORITY_COMMITTED"
                else "rolled_back"
                if event.get("event_type") == "NARRATIVE_STATE_ROLLED_BACK"
                else "committed"
            ),
            "project": self.project,
            "event_id": event["event_id"],
            "event_sequence": sequence,
            "state_sha256": snapshot["state_sha256"],
            "manifest_sha256": payload.get("manifest_sha256"),
            "commit_sha256": payload.get("commit_sha256"),
            "target_chapter": payload.get("target_chapter"),
            "restored_state_sha256": payload.get("restored_state_sha256"),
        }

    def bootstrap(self, manifest: Mapping[str, Any]) -> dict[str, Any]:
        """Create the immutable hash-bound base event, or return it idempotently."""

        if not isinstance(manifest, Mapping):
            raise ValueError("bootstrap manifest must be a mapping")
        if manifest.get("schema_version") != "narrative-bootstrap/v1":
            raise ValueError("bootstrap schema_version must be narrative-bootstrap/v1")
        if manifest.get("project") != self.project:
            raise ValueError("bootstrap project mismatch")
        precedence = manifest.get("precedence")
        if not isinstance(precedence, list) or not precedence or not all(
            isinstance(item, str) and item.strip() for item in precedence
        ):
            raise ValueError("bootstrap precedence must be a non-empty string list")
        sources = manifest.get("sources")
        if not isinstance(sources, list) or not sources:
            raise ValueError("bootstrap sources must be non-empty")
        project_root = self.project_brain_dir.parent.resolve(strict=True)
        normalized_sources: list[dict[str, Any]] = []
        for source in sources:
            if not isinstance(source, Mapping):
                raise ValueError("bootstrap source must be a mapping")
            reference = Path(str(source.get("path") or ""))
            path = (
                reference.resolve(strict=True)
                if reference.is_absolute()
                else (project_root / reference).resolve(strict=True)
            )
            if project_root not in path.parents:
                raise NarrativeStateIntegrityError(
                    f"bootstrap source path is unsafe: {reference}"
                )
            expected = str(source.get("sha256") or "")
            if not _SHA256.fullmatch(expected):
                raise ValueError("bootstrap source sha256 must be lowercase 64-hex")
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise NarrativeStateIntegrityError(
                    f"bootstrap source hash mismatch: {path}"
                )
            normalized_sources.append(
                {
                    **deepcopy(dict(source)),
                    "path": path.relative_to(project_root).as_posix(),
                }
            )
        base_state = manifest.get("base_state")
        if not isinstance(base_state, Mapping):
            raise ValueError("bootstrap base_state must be a mapping")
        fact_authorities = base_state.get("fact_authorities", {})
        if not isinstance(fact_authorities, Mapping) or len(fact_authorities) > 1:
            raise ValueError(
                "bootstrap base_state must contain at most one active fact authority"
            )
        normalized_base_state = deepcopy(dict(base_state))
        if fact_authorities:
            authority_id, raw_metadata = next(iter(fact_authorities.items()))
            if not str(authority_id).strip() or not isinstance(raw_metadata, Mapping):
                raise ValueError("bootstrap fact authority metadata is invalid")
            revision = raw_metadata.get("revision")
            source_sha256 = str(raw_metadata.get("source_sha256") or "")
            source_reference = Path(str(raw_metadata.get("source_path") or ""))
            if (
                isinstance(revision, bool)
                or not isinstance(revision, int)
                or revision < 1
                or not _SHA256.fullmatch(source_sha256)
            ):
                raise ValueError("bootstrap fact authority metadata is invalid")
            authority_source = (
                source_reference.resolve(strict=True)
                if source_reference.is_absolute()
                else (project_root / source_reference).resolve(strict=True)
            )
            if project_root not in authority_source.parents:
                raise NarrativeStateIntegrityError(
                    "bootstrap fact authority source path is unsafe"
                )
            normalized_authority_path = authority_source.relative_to(
                project_root
            ).as_posix()
            if not any(
                source["path"] == normalized_authority_path
                and source["sha256"] == source_sha256
                for source in normalized_sources
            ):
                raise NarrativeStateIntegrityError(
                    "bootstrap fact authority metadata is not source-bound"
                )
            normalized_base_state["fact_authorities"] = {
                str(authority_id): {
                    **deepcopy(dict(raw_metadata)),
                    "source_path": normalized_authority_path,
                }
            }
        normalized_manifest = {
            **deepcopy(dict(manifest)),
            "sources": normalized_sources,
            "base_state": normalized_base_state,
        }
        manifest_sha256 = _sha256_json(normalized_manifest)
        with self._lock():
            events = self._load_events()
            if events:
                first = events[0]
                if (
                    first.get("event_type") == "NARRATIVE_BOOTSTRAPPED"
                    and (first.get("payload") or {}).get("manifest_sha256")
                    == manifest_sha256
                ):
                    self._persist_snapshot(events)
                    return self._receipt(events, first)
                raise NarrativeStateConflict(
                    "narrative state already has a different bootstrap authority"
                )
            event = self._new_event(
                events,
                event_type="NARRATIVE_BOOTSTRAPPED",
                payload={
                    "manifest_sha256": manifest_sha256,
                    "precedence": list(precedence),
                    "sources": normalized_sources,
                    "base_state": normalized_base_state,
                },
            )
            events.append(event)
            self._append_event_to_ledger(event)
            self._persist_snapshot(events)
            return self._receipt(events, event)

    def record_editorial_memory(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """Record feedback from rejected prose without storing prose excerpts."""

        if not isinstance(record, Mapping):
            raise ValueError("editorial memory record must be a mapping")
        if record.get("schema_version") != "editorial-memory-event/v1":
            raise ValueError("editorial memory schema mismatch")
        if record.get("project") != self.project:
            raise ValueError("editorial memory project mismatch")
        allowed_fields = {
            "schema_version",
            "project",
            "rule_id",
            "memory_kind",
            "summary",
            "source_artifact_sha256",
            "source_disposition",
            "source_locator",
        }
        unexpected = sorted(set(record) - allowed_fields)
        if unexpected:
            raise ValueError(
                "editorial memory contains unsupported fields: "
                + ", ".join(unexpected)
            )
        if record.get("memory_kind") not in {
            "anti_pattern",
            "mechanical_policy",
            "editorial_guidance",
        }:
            raise ValueError("unsupported editorial memory kind")
        for field in (
            "rule_id",
            "summary",
            "source_disposition",
            "source_locator",
        ):
            if not isinstance(record.get(field), str) or not record[field].strip():
                raise ValueError(f"editorial memory {field} is required")
        source_sha = str(record.get("source_artifact_sha256") or "")
        if not _SHA256.fullmatch(source_sha):
            raise ValueError("editorial memory source hash must be lowercase 64-hex")
        record_sha256 = _sha256_json(record)
        with self._lock():
            events = self._load_events()
            if not events:
                raise NarrativeStateConflict("narrative state must be bootstrapped first")
            for event in events:
                if event.get("event_type") != "EDITORIAL_MEMORY_RECORDED":
                    continue
                if (event.get("payload") or {}).get("record_sha256") == record_sha256:
                    self._persist_snapshot(events)
                    return self._receipt(events, event)
                if (event.get("payload") or {}).get("rule_id") == record["rule_id"]:
                    raise NarrativeStateConflict(
                        f"editorial rule {record['rule_id']} already has a different record"
                    )
            payload = deepcopy(dict(record))
            payload["record_sha256"] = record_sha256
            event = self._new_event(
                events,
                event_type="EDITORIAL_MEMORY_RECORDED",
                payload=payload,
            )
            events.append(event)
            self._append_event_to_ledger(event)
            self._persist_snapshot(events)
            return self._receipt(events, event)

    def commit_fact_authority(self, authority_path: Path) -> dict[str, Any]:
        """Commit one hash-bound fact revision on a single supersession lineage."""

        project_root = self.project_brain_dir.parent.resolve(strict=False)
        source = Path(authority_path).resolve(strict=True)
        expected_source = project_root / "production" / "fact_authority.yml"
        if source != expected_source:
            raise NarrativeStateIntegrityError(
                "fact authority source must be production/fact_authority.yml"
            )
        cursor = project_root
        for part in source.relative_to(project_root).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise NarrativeStateIntegrityError(
                    "fact authority source path is unsafe"
                )
        authority, source_sha256 = load_fact_authority(
            source,
            project=self.project,
        )
        try:
            verify_registered_fact_authority(
                project_root,
                authority,
                source_sha256,
            )
        except ValueError as exc:
            raise NarrativeStateIntegrityError(str(exc)) from exc
        with self._lock():
            events = self._load_events()
            if not events:
                raise NarrativeStateConflict(
                    "narrative state must be bootstrapped first"
                )
            current = self._project(events)
            active_authorities = current.get("fact_authorities") or {}
            if not isinstance(active_authorities, Mapping) or len(active_authorities) > 1:
                raise NarrativeStateIntegrityError(
                    "narrative state does not have a unique active fact authority"
                )
            if active_authorities:
                active_id, active_revision = next(iter(active_authorities.items()))
                if active_id != authority["authority_id"]:
                    raise NarrativeStateConflict(
                        "single active fact authority cannot change authority_id"
                    )
                if not isinstance(active_revision, Mapping):
                    raise NarrativeStateIntegrityError(
                        "active fact authority metadata is invalid"
                    )
            else:
                active_revision = None
            lineage = [
                event
                for event in events
                if event.get("event_type") == "FACT_AUTHORITY_COMMITTED"
                and (event.get("payload") or {})
                .get("authority", {})
                .get("authority_id")
                == authority["authority_id"]
            ]
            if active_revision is not None:
                if (
                    active_revision.get("source_sha256") == source_sha256
                    and active_revision.get("revision") == authority["revision"]
                ):
                    self._persist_snapshot(events)
                    return self._receipt(events, lineage[-1] if lineage else events[0])
                if authority["revision"] != int(active_revision["revision"]) + 1:
                    raise NarrativeStateConflict(
                        "fact authority revision must increment by one"
                    )
                if (
                    authority.get("supersedes_authority_sha256")
                    != active_revision.get("source_sha256")
                ):
                    raise NarrativeStateConflict(
                        "fact authority supersedes hash does not match active revision"
                    )
            elif authority["revision"] != 1 or authority.get(
                "supersedes_authority_sha256"
            ):
                raise NarrativeStateConflict(
                    "first fact authority revision must be revision 1 without supersedes"
                )

            try:
                apply_fact_authority(current, authority)
            except ValueError as exc:
                raise NarrativeStateConflict(str(exc)) from exc
            event = self._new_event(
                events,
                event_type="FACT_AUTHORITY_COMMITTED",
                payload={
                    "authority": authority,
                    "source_path": source.relative_to(project_root).as_posix(),
                    "source_sha256": source_sha256,
                },
            )
            events.append(event)
            self._append_event_to_ledger(event)
            self._persist_snapshot(events)
            return self._receipt(events, event)

    def read(
        self, *, at_version: int | None = None, chapter: int | None = None
    ) -> dict[str, Any]:
        """Read a deterministic snapshot at an event version or chapter boundary."""

        with self._lock():
            events = self._load_events()
            if at_version is not None:
                if isinstance(at_version, bool) or at_version < 0:
                    raise ValueError("at_version must be a non-negative integer")
                events = events[:at_version]
            if chapter is not None:
                if isinstance(chapter, bool) or chapter < 0:
                    raise ValueError("chapter must be a non-negative integer")
                events = [
                    event
                    for event in events
                    if (
                        event.get("event_type")
                        != "VERIFIED_CHAPTER_COMMITTED"
                        or int((event.get("payload") or {}).get("chapter") or 0)
                        <= chapter
                    )
                    and (
                        event.get("event_type")
                        != "NARRATIVE_STATE_ROLLED_BACK"
                        or int(
                            (event.get("payload") or {}).get(
                                "target_chapter"
                            )
                            or 0
                        )
                        <= chapter
                    )
                ]
            return self._project(events)

    def rollback_to_chapter(
        self,
        chapter: int,
        *,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Append an auditable rollback event and make that projection active."""

        if isinstance(chapter, bool) or not isinstance(chapter, int) or chapter < 0:
            raise ValueError("rollback chapter must be a non-negative integer")
        reason = str(reason or "").strip()
        idempotency_key = str(idempotency_key or "").strip()
        if not reason:
            raise ValueError("rollback reason is required")
        if not idempotency_key:
            raise ValueError("rollback idempotency_key is required")
        with self._lock():
            events = self._load_events()
            if not events:
                raise NarrativeStateConflict(
                    "narrative state must be bootstrapped first"
                )
            for event in events:
                if event.get("event_type") != "NARRATIVE_STATE_ROLLED_BACK":
                    continue
                payload = event.get("payload") or {}
                if payload.get("idempotency_key") != idempotency_key:
                    continue
                if (
                    payload.get("target_chapter") != chapter
                    or payload.get("reason") != reason
                ):
                    raise NarrativeStateConflict(
                        "rollback idempotency key was reused"
                    )
                self._persist_snapshot(events)
                return self._receipt(events, event)
            current = self._project(events)
            committed_chapters = [
                int(value)
                for value in current.get("chapters", {})
                if str(value).isdigit()
            ]
            if not committed_chapters or chapter >= max(committed_chapters):
                raise NarrativeStateConflict(
                    "rollback target must precede the active committed chapter"
                )
            historical_events = [
                event
                for event in self._active_authority_events(events)
                if (
                    event.get("event_type")
                    != "VERIFIED_CHAPTER_COMMITTED"
                    or int((event.get("payload") or {}).get("chapter") or 0)
                    <= chapter
                )
            ]
            restored_state = self._project(historical_events)
            event = self._new_event(
                events,
                event_type="NARRATIVE_STATE_ROLLED_BACK",
                payload={
                    "target_chapter": chapter,
                    "reason": reason,
                    "idempotency_key": idempotency_key,
                    "previous_state_sha256": current["state_sha256"],
                    "restored_state_sha256": restored_state["state_sha256"],
                    "restored_state": restored_state,
                },
            )
            events.append(event)
            self._append_event_to_ledger(event)
            self._persist_snapshot(events)
            return self._receipt(events, event)

    def commit(self, verified_commit: Mapping[str, Any]) -> dict[str, Any]:
        """Commit one accepted, verified chapter delta to narrative authority."""

        if not isinstance(verified_commit, Mapping):
            raise ValueError("verified commit must be a mapping")
        if verified_commit.get("schema_version") != "verified-chapter-commit/v1":
            raise ValueError("verified commit schema mismatch")
        if verified_commit.get("project") != self.project:
            raise ValueError("verified commit project mismatch")
        chapter = verified_commit.get("chapter")
        if isinstance(chapter, bool) or not isinstance(chapter, int) or chapter < 1:
            raise ValueError("verified commit chapter must be positive")
        seal = verified_commit.get("seal")
        if not isinstance(seal, Mapping) or seal.get("status") != "accepted":
            raise NarrativeStateConflict("verified commit requires an accepted seal")
        delta_verification = verified_commit.get("delta_verification")
        if (
            not isinstance(delta_verification, Mapping)
            or delta_verification.get("status") != "pass"
        ):
            raise NarrativeStateConflict("verified commit requires a passing delta verification")
        state_delta = verified_commit.get("state_delta")
        if not isinstance(state_delta, Mapping):
            raise ValueError("state_delta must be a mapping")
        for value in (
            verified_commit.get("artifact_sha256"),
            verified_commit.get("brief_sha256"),
            verified_commit.get("source_projection_sha256"),
            verified_commit.get("state_delta_sha256"),
            seal.get("receipt_sha256"),
            seal.get("artifact_sha256"),
            seal.get("brief_sha256"),
            seal.get("source_projection_sha256"),
            seal.get("verification_result_sha256"),
            seal.get("state_delta_sha256"),
            delta_verification.get("receipt_sha256"),
            delta_verification.get("source_projection_sha256"),
            delta_verification.get("verification_result_sha256"),
            verified_commit.get("previous_state_sha256"),
        ):
            if not _SHA256.fullmatch(str(value or "")):
                raise ValueError("verified commit hashes must be lowercase 64-hex")
        if verified_commit.get("state_delta_sha256") != _sha256_json(state_delta):
            raise NarrativeStateConflict("verified commit state delta hash mismatch")
        binding = {
            "artifact_sha256": verified_commit.get("artifact_sha256"),
            "brief_sha256": verified_commit.get("brief_sha256"),
            "source_projection_sha256": verified_commit.get(
                "source_projection_sha256"
            ),
            "verification_result_sha256": delta_verification.get(
                "verification_result_sha256"
            ),
            "state_delta_sha256": verified_commit.get("state_delta_sha256"),
        }
        if delta_verification.get("source_projection_sha256") != binding[
            "source_projection_sha256"
        ]:
            raise NarrativeStateConflict("delta verification projection binding mismatch")
        if any(seal.get(field) != value for field, value in binding.items()):
            raise NarrativeStateConflict("accepted seal narrative binding mismatch")
        detached_seal = seal.get("mode") == "detached"
        seal_receipt = self._verified_receipt(
            seal,
            label="accepted seal",
            expected_schema=(
                "narrative-detached-auto-seal-receipt/v1"
                if detached_seal
                else "narrative-seal-receipt/v1"
            ),
            expected_issuer=(
                "AgentLab.DetachedAcceptance"
                if detached_seal
                else "AgentLab.Supervisor"
            ),
            identity_field=("decision_id" if detached_seal else "attempt_id"),
        )
        verification_receipt = self._verified_receipt(
            delta_verification,
            label="delta verification",
            expected_schema="delta-verification-receipt/v1",
            expected_issuer="AgentLab.DeltaVerifier",
        )
        if (
            seal_receipt["evidence_binding_id"]
            != verification_receipt["evidence_binding_id"]
        ):
            raise NarrativeStateConflict("receipt evidence binding mismatch")
        if detached_seal and (
            not str(seal.get("decision_id") or "").strip()
            or seal_receipt.get("decision_id") != seal.get("decision_id")
        ):
            raise NarrativeStateConflict("detached acceptance decision binding mismatch")
        if detached_seal:
            task_id = str(seal_receipt.get("task_id") or "")
            work_item_id = str(seal_receipt.get("work_item_id") or "")
            decision_id = str(seal_receipt.get("decision_id") or "")
            acceptance_sha256 = str(
                seal_receipt.get("acceptance_record_sha256") or ""
            )
            if (
                not task_id
                or not work_item_id
                or not decision_id
                or not _SHA256.fullmatch(acceptance_sha256)
                or seal.get("task_id") != task_id
                or seal.get("work_item_id") != work_item_id
                or seal.get("acceptance_record_sha256") != acceptance_sha256
            ):
                raise NarrativeStateConflict(
                    "detached seal lacks immutable acceptance provenance"
                )
            project_root = self.project_brain_dir.parent
            agentlab_root = project_root.parent.parent
            from agent_runtime.narrative.auto_acceptance import (
                validate_detached_candidate_acceptance,
            )
            from agent_runtime.task_runtime_v2 import TaskRuntime

            runtime = TaskRuntime(agentlab_root, project=self.project)
            task_projection = runtime.load_task(task_id)
            record = (task_projection.get("trace_records") or {}).get(decision_id)
            if (
                not isinstance(record, Mapping)
                or record.get("record_type") != "narrative_auto_acceptance"
                or record.get("sha256") != acceptance_sha256
                or (record.get("record_data") or {}).get("work_item_id")
                != work_item_id
            ):
                raise NarrativeStateConflict(
                    "detached seal does not resolve to immutable acceptance evidence"
                )
            try:
                acceptance = validate_detached_candidate_acceptance(
                    agentlab_root,
                    project=self.project,
                    task_id=task_id,
                    work_item_id=work_item_id,
                    data=record.get("record_data") or {},
                    task_projection=task_projection,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                raise NarrativeStateConflict(
                    "detached acceptance evidence is invalid"
                ) from exc
            if acceptance.get("candidate_sha256") != binding["artifact_sha256"]:
                raise NarrativeStateConflict(
                    "detached acceptance candidate binding mismatch"
                )
            attempt_id = str(delta_verification.get("attempt_id") or "")
            attempt = (task_projection.get("attempts") or {}).get(attempt_id)
            execution_contract = (
                attempt.get("execution_contract")
                if isinstance(attempt, Mapping)
                else {}
            )
            outcome = attempt.get("outcome") if isinstance(attempt, Mapping) else {}
            if (
                not isinstance(attempt, Mapping)
                or attempt.get("status") != "succeeded"
                or attempt.get("work_item_id") != work_item_id
                or execution_contract.get("role") != "Scribe"
                or execution_contract.get("executor_type") != "deterministic_tool"
                or (execution_contract.get("deterministic_tool") or {}).get(
                    "acceptance_record_id"
                )
                != decision_id
                or outcome.get("execution_origin")
                != "deterministic_tool_executor"
            ):
                raise NarrativeStateConflict(
                    "delta verification is not bound to a succeeded Scribe Attempt"
                )
            try:
                runtime.verify_attempt_execution_receipt(task_id, attempt_id)
                task_root = project_root / "runtime" / "tasks" / task_id
                attempt_receipt_path = task_root / str(outcome.get("receipt_path") or "")
                attempt_receipt = yaml.safe_load(
                    attempt_receipt_path.read_text(encoding="utf-8")
                )
                attempt_output_path = task_root / str(
                    (attempt_receipt or {}).get("output_path") or ""
                )
                attempt_output = yaml.safe_load(
                    attempt_output_path.read_text(encoding="utf-8")
                )
            except (OSError, RuntimeError, ValueError, yaml.YAMLError) as exc:
                raise NarrativeStateConflict(
                    "Scribe Attempt output evidence is invalid"
                ) from exc
            if (
                not isinstance(attempt_receipt, Mapping)
                or not attempt_output_path.resolve().is_relative_to(task_root.resolve())
                or _sha256_file(attempt_output_path)
                != attempt_receipt.get("output_sha256")
                or outcome.get("output_sha256")
                != attempt_receipt.get("output_sha256")
                or attempt_output != state_delta
            ):
                raise NarrativeStateConflict(
                    "Scribe Attempt output does not match the committed state delta"
                )
        if seal_receipt.get("status") != "accepted" or any(
            seal_receipt.get(field) != value for field, value in binding.items()
        ):
            raise NarrativeStateConflict("accepted seal receipt binding mismatch")
        if (
            verification_receipt.get("status") != "pass"
            or verification_receipt.get("source_projection_sha256")
            != binding["source_projection_sha256"]
            or verification_receipt.get("verification_result_sha256")
            != binding["verification_result_sha256"]
        ):
            raise NarrativeStateConflict("delta verification receipt binding mismatch")

        commit_sha256 = _sha256_json(verified_commit)
        with self._lock():
            events = self._load_events()
            if not events:
                raise NarrativeStateConflict("narrative state must be bootstrapped first")
            for event in self._active_authority_events(events):
                if event.get("event_type") != "VERIFIED_CHAPTER_COMMITTED":
                    continue
                payload = event.get("payload") or {}
                if payload.get("commit_sha256") == commit_sha256:
                    self._persist_snapshot(events)
                    return self._receipt(events, event)
                if int(payload.get("chapter") or 0) == chapter:
                    raise NarrativeStateConflict(
                        f"chapter {chapter} already has a different verified commit"
                    )
            current = self._project(events)
            if verified_commit.get("previous_state_sha256") != current["state_sha256"]:
                raise NarrativeStateConflict("previous narrative state hash is stale")
            long_term_issues = validate_long_term_delta(
                state_delta,
                current_state=current,
            )
            if long_term_issues:
                raise NarrativeStateConflict(
                    "long-term narrative delta is invalid: "
                    + ",".join(long_term_issues)
                )
            payload = deepcopy(dict(verified_commit))
            payload["commit_sha256"] = commit_sha256
            event = self._new_event(
                events,
                event_type="VERIFIED_CHAPTER_COMMITTED",
                payload=payload,
            )
            events.append(event)
            self._append_event_to_ledger(event)
            self._persist_snapshot(events)
            return self._receipt(events, event)


__all__ = [
    "EVENTS_FILE",
    "SNAPSHOT_FILE",
    "NarrativeStateConflict",
    "NarrativeStateError",
    "NarrativeStateIntegrityError",
    "NarrativeStateStore",
    "narrative_payload_sha256",
]
