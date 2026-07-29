"""Append-only, bounded authorial preference learning without model training."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from atomic_io import atomic_write_yaml

CROWN_AUTHORIAL_PRIOR = {
    "causal_foreshadowing": 12,
    "character_arcs": 11,
    "continuity": 9,
    "world_semantics": 8,
    "prose": 8,
    "scene_progress": 7,
    "mystery": 7,
    "emotion": 7,
    "pacing": 6,
    "relationships": 6,
    "payoff": 5,
    "atmosphere": 4,
    "ensemble_romance": 4,
    "anti_cliche": 3,
    "adult_tension": 2,
    "voice_humor": 1,
}

LEARNING_RATES = {
    "chapter": 0.20,
    "window": 0.12,
    "arc": 0.08,
    "book": 0.04,
}

_CLASSIFIER_RULES = {
    "causal_foreshadowing": ("伏笔", "因果", "foreshadow"),
    "character_arcs": ("人物弧", "成长", "character arc"),
    "continuity": ("连续性", "穿帮", "continuity"),
    "world_semantics": ("世界观", "设定", "world"),
    "prose": ("文笔", "文字", "prose"),
    "scene_progress": ("场景推进", "不推进", "scene"),
    "mystery": ("谜团", "悬念", "mystery"),
    "emotion": ("情绪", "感动", "emotion"),
    "pacing": ("节奏", "太慢", "拖沓", "pacing"),
    "relationships": ("关系", "感情线", "relationship"),
    "payoff": ("爽感", "回报", "payoff"),
    "atmosphere": ("氛围", "atmosphere"),
    "ensemble_romance": ("后宫", "群像恋爱", "ensemble romance"),
    "anti_cliche": ("套路", "陈词滥调", "cliche"),
    "adult_tension": ("性张力", "adult tension"),
    "voice_humor": ("幽默", "声音", "humor"),
}

_NEGATIVE_MARKERS = ("太慢", "拖沓", "不好", "不喜欢", "退步", "糟", "差")
_POSITIVE_MARKERS = ("很好", "喜欢", "更好", "有效", "精彩", "满意")

EVENTS_FILE = "authorial_preference_events.jsonl"
SNAPSHOT_FILE = "authorial_preference_profile.yml"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalize_weights(weights: Mapping[str, float | int]) -> dict[str, float]:
    if set(weights) != set(CROWN_AUTHORIAL_PRIOR):
        raise ValueError("preference dimensions must match the authorial prior")
    normalized = {key: float(value) for key, value in weights.items()}
    if any(
        isinstance(value, bool) or not math.isfinite(value) or value <= 0
        for value in normalized.values()
    ):
        raise ValueError("preference weights must be positive finite numbers")
    total = sum(normalized.values())
    if total <= 0:
        raise ValueError("preference weight total must be positive")
    return {key: value * 100.0 / total for key, value in normalized.items()}


def _validate_classifications(
    classifications: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not classifications:
        raise ValueError("at least one preference classification is required")
    validated: list[dict[str, Any]] = []
    for item in classifications:
        if not isinstance(item, Mapping):
            raise ValueError("preference classification must be a mapping")
        dimension = str(item.get("dimension") or "")
        if dimension not in CROWN_AUTHORIAL_PRIOR:
            raise ValueError(f"unknown soft preference dimension: {dimension}")
        polarity = item.get("polarity")
        if polarity not in {-1, 1}:
            raise ValueError("preference polarity must be -1 or 1")
        confidence = item.get("confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0.0 < float(confidence) <= 1.0
        ):
            raise ValueError("preference confidence must be in (0, 1]")
        recurrence = item.get("recurrence")
        if (
            isinstance(recurrence, bool)
            or not isinstance(recurrence, int)
            or not 1 <= recurrence <= 10
        ):
            raise ValueError("preference recurrence must be an integer in [1, 10]")
        validated.append(
            {
                "dimension": dimension,
                "polarity": int(polarity),
                "confidence": float(confidence),
                "recurrence": recurrence,
            }
        )
    return validated


def update_preference_weights(
    weights: Mapping[str, float | int],
    *,
    classifications: Sequence[Mapping[str, Any]],
    scope_level: str,
) -> dict[str, float]:
    """Apply the specified logit rule and a per-event 10% relative cap."""

    if scope_level not in LEARNING_RATES:
        raise ValueError("preference scope must be chapter, window, arc, or book")
    before = _normalize_weights(weights)
    validated = _validate_classifications(classifications)
    logits = {
        dimension: math.log(weight / 100.0)
        for dimension, weight in before.items()
    }
    rate = LEARNING_RATES[scope_level]
    for item in validated:
        logits[item["dimension"]] += (
            rate
            * item["polarity"]
            * item["confidence"]
            * item["recurrence"]
        )
    maximum = max(logits.values())
    exponentials = {
        dimension: math.exp(value - maximum)
        for dimension, value in logits.items()
    }
    denominator = sum(exponentials.values())
    raw = {
        dimension: value * 100.0 / denominator
        for dimension, value in exponentials.items()
    }
    maximum_relative = max(
        abs(raw[dimension] - before[dimension]) / before[dimension]
        for dimension in before
    )
    alpha = min(1.0, 0.1 / maximum_relative) if maximum_relative else 1.0
    return {
        dimension: before[dimension]
        + alpha * (raw[dimension] - before[dimension])
        for dimension in before
    }


def classify_feedback(
    text: str,
    *,
    polarity: int | None,
) -> dict[str, Any]:
    """Return deterministic rule matches; ambiguity remains for Supervisor."""

    body = str(text or "").strip()
    if not body:
        raise ValueError("feedback text is required")
    if polarity is not None and polarity not in {-1, 1}:
        raise ValueError("polarity must be -1 or 1")
    lowered = body.casefold()
    inferred = polarity
    if inferred is None:
        negative = any(marker in lowered for marker in _NEGATIVE_MARKERS)
        positive = any(marker in lowered for marker in _POSITIVE_MARKERS)
        inferred = -1 if negative and not positive else 1
    classifications: list[dict[str, Any]] = []
    for dimension, aliases in _CLASSIFIER_RULES.items():
        if any(alias.casefold() in lowered for alias in aliases):
            classifications.append(
                {
                    "dimension": dimension,
                    "polarity": inferred,
                    "confidence": 0.75,
                    "recurrence": 1,
                    "classifier": "exact_alias_rule",
                }
            )
    return {
        "schema_version": "narrative-feedback-classification/v1",
        "classifications": classifications,
        "supervisor_review_required": not classifications,
        "training_performed": False,
    }


class PreferenceStore:
    """Append-only preference events with deterministic overlay projection."""

    def __init__(self, project_brain_dir: Path, *, project: str) -> None:
        self.root = Path(project_brain_dir).resolve()
        self.project = str(project or "").strip()
        if not self.project:
            raise ValueError("project is required")

    @property
    def events_path(self) -> Path:
        return self.root / EVENTS_FILE

    @property
    def snapshot_path(self) -> Path:
        return self.root / SNAPSHOT_FILE

    @property
    def lock_path(self) -> Path:
        return self.root / ".authorial_preferences.lock"

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _events(self) -> list[dict[str, Any]]:
        if not self.events_path.is_file():
            return []
        events: list[dict[str, Any]] = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("preference event must be a mapping")
                events.append(value)
        return events

    def _append(self, event: Mapping[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical_json(event) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _project(self, events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        scopes: dict[str, dict[str, Any]] = {}
        prior: dict[str, float] | None = None
        for event in events:
            event_type = event.get("event_type")
            if event_type == "PREFERENCE_PRIOR_REGISTERED":
                prior = _normalize_weights(event["weights"])
                scopes["book:book"] = {
                    "weights": deepcopy(prior),
                    "expires_after_chapter": None,
                    "last_event_id": event["event_id"],
                }
            elif event_type in {
                "PREFERENCE_FEEDBACK_APPLIED",
                "PREFERENCE_ROLLED_BACK",
            }:
                scope_key = str(event["scope_key"])
                scopes[scope_key] = {
                    "weights": deepcopy(event["after_weights"]),
                    "expires_after_chapter": event.get(
                        "expires_after_chapter"
                    ),
                    "last_event_id": event["event_id"],
                }
        if prior is None:
            raise ValueError("authorial preference prior is not initialized")
        return {
            "schema_version": "narrative-preference-profile/v1",
            "project": self.project,
            "prior": prior,
            "scopes": scopes,
            "event_count": len(events),
            "last_event_id": events[-1]["event_id"] if events else None,
        }

    def _persist(self, events: Sequence[Mapping[str, Any]]) -> None:
        atomic_write_yaml(self.snapshot_path, self._project(events))

    def initialize(
        self,
        weights: Mapping[str, float | int],
    ) -> dict[str, Any]:
        normalized = _normalize_weights(weights)
        with self._lock():
            events = self._events()
            if events:
                projected = self._project(events)
                if projected["prior"] != normalized:
                    raise ValueError("authorial preference prior already differs")
                return dict(events[0])
            event = {
                "schema_version": "narrative-preference-event/v1",
                "event_type": "PREFERENCE_PRIOR_REGISTERED",
                "event_id": "preference-event-000001",
                "sequence": 1,
                "project": self.project,
                "scope_key": "book:book",
                "weights": normalized,
                "prior_id": "crown-authorial-prior/v1",
                "recorded_at": _utc_now(),
            }
            event["event_sha256"] = _sha256(event)
            self._append(event)
            self._persist([event])
            return event

    def _idempotent(
        self,
        events: Sequence[Mapping[str, Any]],
        *,
        idempotency_key: str,
        request_sha256: str,
    ) -> dict[str, Any] | None:
        for event in events:
            if event.get("idempotency_key") != idempotency_key:
                continue
            if event.get("request_sha256") != request_sha256:
                raise ValueError("preference idempotency key was reused")
            return dict(event)
        return None

    def intake(
        self,
        *,
        source: str,
        scope_level: str,
        scope_id: str,
        classifications: Sequence[Mapping[str, Any]],
        idempotency_key: str,
        expires_after_chapter: int | None = None,
    ) -> dict[str, Any]:
        if source not in {"user", "reviewer"}:
            raise ValueError("feedback source must be user or reviewer")
        if scope_level not in LEARNING_RATES:
            raise ValueError("invalid feedback scope")
        if source == "reviewer" and scope_level not in {"chapter", "window"}:
            raise ValueError("reviewer feedback may only create local candidates")
        if not str(scope_id or "").strip():
            raise ValueError("feedback scope_id is required")
        if not str(idempotency_key or "").strip():
            raise ValueError("feedback idempotency_key is required")
        if scope_level == "book":
            if expires_after_chapter is not None:
                raise ValueError("book preference must not expire")
        elif (
            isinstance(expires_after_chapter, bool)
            or not isinstance(expires_after_chapter, int)
            or expires_after_chapter < 1
        ):
            raise ValueError("local preference expiry chapter is required")
        validated = _validate_classifications(classifications)
        scope_key = f"{scope_level}:{scope_id}"
        request = {
            "source": source,
            "scope_key": scope_key,
            "classifications": validated,
            "expires_after_chapter": expires_after_chapter,
        }
        request_sha256 = _sha256(request)
        with self._lock():
            events = self._events()
            repeated = self._idempotent(
                events,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
            )
            if repeated is not None:
                return repeated
            profile = self._project(events)
            scope = profile["scopes"].get(scope_key)
            before = (
                deepcopy(scope["weights"])
                if isinstance(scope, Mapping)
                else deepcopy(profile["scopes"]["book:book"]["weights"])
            )
            after = update_preference_weights(
                before,
                classifications=validated,
                scope_level=scope_level,
            )
            sequence = len(events) + 1
            event = {
                "schema_version": "narrative-preference-event/v1",
                "event_type": "PREFERENCE_FEEDBACK_APPLIED",
                "event_id": f"preference-event-{sequence:06d}",
                "sequence": sequence,
                "project": self.project,
                "source": source,
                "scope_key": scope_key,
                "scope_level": scope_level,
                "scope_id": scope_id,
                "classifications": validated,
                "before_weights": before,
                "after_weights": after,
                "expires_after_chapter": expires_after_chapter,
                "idempotency_key": idempotency_key,
                "request_sha256": request_sha256,
                "recorded_at": _utc_now(),
            }
            event["event_sha256"] = _sha256(event)
            self._append(event)
            self._persist([*events, event])
            return event

    def rollback(
        self,
        *,
        event_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request = {"event_id": event_id, "operation": "rollback"}
        request_sha256 = _sha256(request)
        with self._lock():
            events = self._events()
            repeated = self._idempotent(
                events,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
            )
            if repeated is not None:
                return repeated
            target = next(
                (
                    event
                    for event in events
                    if event.get("event_id") == event_id
                    and event.get("event_type")
                    == "PREFERENCE_FEEDBACK_APPLIED"
                ),
                None,
            )
            if target is None:
                raise ValueError("feedback event is not rollback eligible")
            profile = self._project(events)
            scope_key = str(target["scope_key"])
            current = profile["scopes"].get(scope_key)
            if (
                not isinstance(current, Mapping)
                or current.get("last_event_id") != event_id
            ):
                raise ValueError("only the latest event for a scope can rollback")
            sequence = len(events) + 1
            event = {
                "schema_version": "narrative-preference-event/v1",
                "event_type": "PREFERENCE_ROLLED_BACK",
                "event_id": f"preference-event-{sequence:06d}",
                "sequence": sequence,
                "project": self.project,
                "scope_key": scope_key,
                "scope_level": target["scope_level"],
                "scope_id": target["scope_id"],
                "before_weights": deepcopy(target["after_weights"]),
                "after_weights": deepcopy(target["before_weights"]),
                "expires_after_chapter": target.get(
                    "expires_after_chapter"
                ),
                "rolled_back_event_id": event_id,
                "idempotency_key": idempotency_key,
                "request_sha256": request_sha256,
                "recorded_at": _utc_now(),
            }
            event["event_sha256"] = _sha256(event)
            self._append(event)
            self._persist([*events, event])
            return event

    def profile(
        self,
        *,
        chapter: int | None = None,
        arc: str | None = None,
        window: str | None = None,
        chapter_scope: str | None = None,
    ) -> dict[str, Any]:
        with self._lock():
            projected = self._project(self._events())
        effective = deepcopy(projected["scopes"]["book:book"]["weights"])
        retired: list[str] = []
        selected = (
            ("arc", arc),
            ("window", window),
            ("chapter", chapter_scope),
        )
        applied: list[str] = ["book:book"]
        for level, scope_id in selected:
            if not scope_id:
                continue
            key = f"{level}:{scope_id}"
            overlay = projected["scopes"].get(key)
            if not isinstance(overlay, Mapping):
                continue
            expires = overlay.get("expires_after_chapter")
            if chapter is not None and isinstance(expires, int) and chapter > expires:
                retired.append(key)
                continue
            effective = deepcopy(overlay["weights"])
            applied.append(key)
        return {
            **projected,
            "effective_weights": effective,
            "effective_profile_sha256": _sha256(effective),
            "applied_scopes": applied,
            "retired_overlays": retired,
        }
