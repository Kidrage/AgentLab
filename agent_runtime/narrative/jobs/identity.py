"""Immutable semantic identity for narrative jobs.

Natural language is compiled once at intake.  Background scheduling validates
and copies this contract; it never reclassifies prose or prior result text.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Mapping

from agent_runtime.narrative_intent import NarrativeIntent


JobKind = Literal[
    "narrative_audit",
    "narrative_generation",
    "narrative_revision",
]
RunMode = Literal[
    "audit_only",
    "generate_candidate",
    "targeted_rewrite",
    "independent_reaudit",
]

_ALLOWED_MODES: dict[str, set[str]] = {
    "narrative_audit": {"audit_only", "independent_reaudit"},
    "narrative_generation": {"generate_candidate"},
    "narrative_revision": {"targeted_rewrite"},
}


@dataclass(frozen=True)
class NarrativeJobIdentity:
    job_kind: JobKind
    run_mode: RunMode
    candidate_set_id: str | None = None
    source_job_id: str | None = None
    source_run_id: str | None = None
    triggered_by_audit_id: str | None = None
    attempt_id: str | None = None
    lease_token: str | None = None

    def __post_init__(self) -> None:
        if self.run_mode not in _ALLOWED_MODES.get(self.job_kind, set()):
            raise ValueError(
                f"run_mode {self.run_mode!r} is invalid for {self.job_kind!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def for_attempt(self, *, attempt_id: str, lease_token: str) -> "NarrativeJobIdentity":
        return replace(self, attempt_id=attempt_id, lease_token=lease_token)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "NarrativeJobIdentity":
        return cls(
            job_kind=str(value.get("job_kind") or ""),  # type: ignore[arg-type]
            run_mode=str(value.get("run_mode") or ""),  # type: ignore[arg-type]
            candidate_set_id=_optional_string(value.get("candidate_set_id")),
            source_job_id=_optional_string(value.get("source_job_id")),
            source_run_id=_optional_string(value.get("source_run_id")),
            triggered_by_audit_id=_optional_string(value.get("triggered_by_audit_id")),
            attempt_id=_optional_string(value.get("attempt_id")),
            lease_token=_optional_string(value.get("lease_token")),
        )


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None


def compile_narrative_job_identity(intent: NarrativeIntent) -> NarrativeJobIdentity | None:
    """Translate the intake classifier result into one durable job contract."""
    if intent.kind == "audit":
        return NarrativeJobIdentity("narrative_audit", "audit_only")
    if intent.kind == "rewrite":
        return NarrativeJobIdentity("narrative_revision", "targeted_rewrite")
    if intent.kind in {"chapter", "chapter_batch"}:
        return NarrativeJobIdentity("narrative_generation", "generate_candidate")
    return None


def _parse_legacy_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def lease_expiry(now: str, seconds: int) -> str:
    """Return the durable deadline for one attempt lease."""
    return (_parse_legacy_time(now) + timedelta(seconds=max(1, seconds))).isoformat()
