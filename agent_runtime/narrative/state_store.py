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
from pathlib import Path
import re
from typing import Any, Iterator, Mapping

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml


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
        "chapters": {},
        "style_memory": [],
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

    def _persist_events(self, events: list[dict[str, Any]]) -> None:
        content = "".join(_canonical_json(event) + "\n" for event in events)
        atomic_write_text(self.events_path, content)

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
                "chapters",
                "style_memory",
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

    def _persist_snapshot(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        snapshot = self._project(events)
        atomic_write_yaml(self.snapshot_path, snapshot)
        return snapshot

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
                else "committed"
            ),
            "project": self.project,
            "event_id": event["event_id"],
            "event_sequence": sequence,
            "state_sha256": snapshot["state_sha256"],
            "manifest_sha256": payload.get("manifest_sha256"),
            "commit_sha256": payload.get("commit_sha256"),
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
        for source in sources:
            if not isinstance(source, Mapping):
                raise ValueError("bootstrap source must be a mapping")
            path = Path(str(source.get("path") or "")).resolve(strict=True)
            expected = str(source.get("sha256") or "")
            if not _SHA256.fullmatch(expected):
                raise ValueError("bootstrap source sha256 must be lowercase 64-hex")
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise NarrativeStateIntegrityError(
                    f"bootstrap source hash mismatch: {path}"
                )
        base_state = manifest.get("base_state")
        if not isinstance(base_state, Mapping):
            raise ValueError("bootstrap base_state must be a mapping")
        manifest_sha256 = _sha256_json(manifest)
        with self._lock():
            events = self._load_events()
            if events:
                first = events[0]
                if (
                    first.get("event_type") == "NARRATIVE_BOOTSTRAPPED"
                    and (first.get("payload") or {}).get("manifest_sha256")
                    == manifest_sha256
                ):
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
                    "sources": deepcopy(list(sources)),
                    "base_state": deepcopy(dict(base_state)),
                },
            )
            events.append(event)
            self._persist_events(events)
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
        if any(key in record for key in ("prose", "excerpt", "text")):
            raise ValueError("editorial anti-pattern memory must not embed prose")
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
            self._persist_events(events)
            self._persist_snapshot(events)
            return self._receipt(events, event)

    def read(
        self, *, at_version: int | None = None, chapter: int | None = None
    ) -> dict[str, Any]:
        """Read a deterministic snapshot at an event version or chapter boundary."""

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
                if event.get("event_type") != "VERIFIED_CHAPTER_COMMITTED"
                or int((event.get("payload") or {}).get("chapter") or 0) <= chapter
            ]
        return self._project(events)

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
        for value in (
            verified_commit.get("artifact_sha256"),
            verified_commit.get("brief_sha256"),
            seal.get("receipt_sha256"),
            delta_verification.get("receipt_sha256"),
            verified_commit.get("previous_state_sha256"),
        ):
            if not _SHA256.fullmatch(str(value or "")):
                raise ValueError("verified commit hashes must be lowercase 64-hex")
        if not isinstance(verified_commit.get("state_delta"), Mapping):
            raise ValueError("state_delta must be a mapping")

        commit_sha256 = _sha256_json(verified_commit)
        with self._lock():
            events = self._load_events()
            if not events:
                raise NarrativeStateConflict("narrative state must be bootstrapped first")
            for event in events:
                if event.get("event_type") != "VERIFIED_CHAPTER_COMMITTED":
                    continue
                payload = event.get("payload") or {}
                if payload.get("commit_sha256") == commit_sha256:
                    return self._receipt(events, event)
                if int(payload.get("chapter") or 0) == chapter:
                    raise NarrativeStateConflict(
                        f"chapter {chapter} already has a different verified commit"
                    )
            current = self._project(events)
            if verified_commit.get("previous_state_sha256") != current["state_sha256"]:
                raise NarrativeStateConflict("previous narrative state hash is stale")
            payload = deepcopy(dict(verified_commit))
            payload["commit_sha256"] = commit_sha256
            event = self._new_event(
                events,
                event_type="VERIFIED_CHAPTER_COMMITTED",
                payload=payload,
            )
            events.append(event)
            self._persist_events(events)
            self._persist_snapshot(events)
            return self._receipt(events, event)


__all__ = [
    "EVENTS_FILE",
    "SNAPSHOT_FILE",
    "NarrativeStateConflict",
    "NarrativeStateError",
    "NarrativeStateIntegrityError",
    "NarrativeStateStore",
]
