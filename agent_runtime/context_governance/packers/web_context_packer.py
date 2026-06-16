from __future__ import annotations
from pathlib import Path
from ..schemas import ContextBudget, ContextProfile
from .base import evidence, make_pack, omitted, section, source_ref


class WebContextPacker:
    def pack(self, profile: ContextProfile, budget: ContextBudget, request_text: str = "", run_dir: Path | None = None):
        src = source_ref(run_dir, "webpage_clean_markdown.md")
        sections = [section("query_plan", "Query plan", "Deterministic query/source plan only; no live web search.", [src]), section("source_scoring", "Source scoring placeholder", f"Plan up to {budget.max_sources} sources with citation/evidence requirements.", [src]), section("clean_markdown_refs", "Clean markdown refs", "Clean markdown source refs with citation placeholders.", [src])]
        return make_pack(profile, budget, sections, omitted_sections=[omitted("Full webpages not embedded; cite refs and drill down.", src)], evidence_refs=[evidence(src, "web_markdown")], warnings=["No real networking is performed in P2-G."])