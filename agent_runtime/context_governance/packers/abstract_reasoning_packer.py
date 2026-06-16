from __future__ import annotations
from pathlib import Path
from ..schemas import ContextBudget, ContextProfile
from .base import evidence, make_pack, omitted, section, source_ref


class AbstractReasoningPacker:
    def pack(self, profile: ContextProfile, budget: ContextBudget, request_text: str = "", run_dir: Path | None = None):
        raw = source_ref(run_dir, "user_request.md")
        sections = [section("decision_matrix", "Decision matrix frame", "Options / criteria / tradeoffs frame."), section("options_pros_cons", "Options/pros/cons placeholder", "Limited deterministic branches with pros/cons placeholders."), section("assumptions", "Assumptions", "Explicit assumptions to validate."), section("risks", "Risks", "Risk and unknowns list with limited branch budget.")]
        return make_pack(profile, budget, sections, omitted_sections=[omitted("Branches beyond configured depth omitted.", raw)], evidence_refs=[evidence(raw, "prompt")])