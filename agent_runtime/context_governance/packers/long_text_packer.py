from __future__ import annotations
from pathlib import Path
from ..schemas import ContextBudget, ContextProfile
from .base import evidence, external, make_pack, omitted, section, source_ref


class LongTextPacker:
    def pack(self, profile: ContextProfile, budget: ContextBudget, request_text: str = "", run_dir: Path | None = None):
        raw = source_ref(run_dir, "user_request.md")
        sections = [
            section("chunk_summary", "Chunk summary placeholder", "Document should be split into deterministic chunks; P2-G records a placeholder summary only.", [raw]),
            section("query_focused_sections", "Query-focused sections", "Sections most related to the request are selected by keyword/fixture hints, not by LLM compression.", [raw]),
        ]
        return make_pack(profile, budget, sections, omitted_sections=[omitted("Middle/low-signal chunks omitted with drilldown refs.", raw)], externalized=[external(raw, "raw_input", "Full long text remains externalized.")], evidence_refs=[evidence(raw, "source_text")])