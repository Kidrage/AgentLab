"""Validation helpers for S9 result contracts."""

from __future__ import annotations


def require_non_empty(value: object, field: str) -> None:
    if value is None or value == "" or value == []:
        raise ValueError(f"{field} is required")


def require_evidence(evidence_artifacts: list[str]) -> None:
    require_non_empty(evidence_artifacts, "evidence_artifacts")
