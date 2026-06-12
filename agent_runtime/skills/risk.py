"""Risk helpers for external skill registry and incubation."""

from __future__ import annotations

from typing import Any


KNOWN_SOURCES = {"ecc", "anysearch", "codegraph", "agentlab_internal", "custom_local"}


def normalize_source(source: str) -> str:
    value = (source or "custom_local").strip().lower()
    return value if value in KNOWN_SOURCES else "custom_local"


def license_requires_review(license_info: dict[str, Any] | None) -> bool:
    info = license_info or {}
    name = str(info.get("name") or "unknown").strip().lower()
    compatibility = str(info.get("compatible_for_internal_distillation") or "").strip().lower()
    return name in {"", "unknown", "proprietary"} or compatibility in {
        "",
        "unknown",
        "review_required",
        "not_allowed",
    }


def risk_requires_approval(risk: dict[str, Any] | None) -> bool:
    info = risk or {}
    level = str(info.get("level") or "medium").lower()
    return bool(info.get("requires_approval", level in {"medium", "high", "critical"}))


def default_risk(level: str = "medium", *, reasons: list[str] | None = None) -> dict[str, Any]:
    return {
        "level": level,
        "reasons": reasons or ["external_prompt_dependency", "unknown_runtime_behavior"],
        "requires_approval": level in {"medium", "high", "critical"},
    }
