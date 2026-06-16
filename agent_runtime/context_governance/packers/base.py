"""Shared helpers for deterministic packers."""

from __future__ import annotations

from pathlib import Path

from ..information_profiler import estimate_tokens
from ..schemas import ContextBudget, ContextPack, ContextProfile, EvidenceRef, ExternalizedArtifact, OmittedSection, PackedSection


def section(section_id: str, title: str, content: str, refs: list[str] | None = None) -> dict:
    return PackedSection(section_id, title, content, estimate_tokens(content), refs or []).as_dict()


def omitted(reason: str, ref: str, can_drill_down: bool = True) -> dict:
    return OmittedSection(reason, ref, can_drill_down).as_dict()


def external(path: str, kind: str, reason: str) -> dict:
    return ExternalizedArtifact(path, kind, reason).as_dict()


def evidence(path: str, kind: str) -> dict:
    return EvidenceRef(path, kind).as_dict()


def make_pack(profile: ContextProfile, budget: ContextBudget, sections: list[dict], *, omitted_sections: list[dict] | None = None, externalized: list[dict] | None = None, evidence_refs: list[dict] | None = None, warnings: list[str] | None = None) -> ContextPack:
    return ContextPack(
        task_id=profile.task_id,
        profile=profile.as_dict(),
        budget=budget.as_dict(),
        strategy=profile.recommended_strategy,
        packed_sections=sections,
        omitted_sections=omitted_sections or [],
        externalized_artifacts=externalized or [],
        evidence_refs=evidence_refs or [],
        warnings=(profile.warnings or []) + (warnings or []),
    )


def source_ref(run_dir: Path | None, name: str) -> str:
    return str((run_dir / name) if run_dir else name)