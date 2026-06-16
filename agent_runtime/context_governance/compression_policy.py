"""Deterministic compression safety policy."""

from __future__ import annotations

from pathlib import Path

from .information_profiler import load_context_config


NO_LOSSY_TYPES = {"code", "config", "tests", "legal", "data"}


def compression_decision(information_kind: str, *, exact_required: bool = False, agentlab_root: Path | None = None) -> dict:
    config = load_context_config(agentlab_root, "compression_policy.yml") if agentlab_root else {}
    rules = (config.get("safety_rules") or {}).get(information_kind, {})
    if exact_required or information_kind in NO_LOSSY_TYPES:
        allowed = rules.get("allowed_levels") or ["C2_extractive", "C6_externalize_and_drilldown"]
        if information_kind in {"code", "config"}:
            allowed = rules.get("allowed_levels") or ["C0_direct", "C2_extractive"]
        return {
            "lossy_allowed": False,
            "compression_safety": "no_lossy_compression" if information_kind != "legal" else "extractive_only",
            "allowed_levels": allowed,
            "reason": f"{information_kind} requires exact evidence; lossy compression disabled.",
        }
    if rules:
        return {
            "lossy_allowed": rules.get("lossy_allowed", True),
            "compression_safety": "safe_lossy" if rules.get("lossy_allowed", True) is True else "extractive_only",
            "allowed_levels": rules.get("allowed_levels") or ["C3_query_focused_compression"],
            "reason": "configured compression policy",
        }
    return {
        "lossy_allowed": True,
        "compression_safety": "safe_lossy",
        "allowed_levels": ["C3_query_focused_compression", "C6_externalize_and_drilldown"],
        "reason": "default safe lossy policy for non-exact information",
    }


def build_compression_trace(profile: dict, pack: dict) -> dict:
    return {
        "version": 1,
        "task_id": profile.get("task_id"),
        "information_type": profile.get("information_type"),
        "compression_level": profile.get("compression_level"),
        "compression_safety": profile.get("compression_safety"),
        "recommended_strategy": profile.get("recommended_strategy", []),
        "lossy_allowed": profile.get("compression_safety") == "safe_lossy",
        "externalized_artifacts": pack.get("externalized_artifacts", []),
        "warnings": profile.get("warnings", []) + pack.get("warnings", []),
    }