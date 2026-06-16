from __future__ import annotations
from pathlib import Path
from ..schemas import ContextBudget, ContextProfile
from .base import evidence, external, make_pack, omitted, section, source_ref


class NarrativePacker:
    def pack(self, profile: ContextProfile, budget: ContextBudget, request_text: str = "", run_dir: Path | None = None):
        raw = source_ref(run_dir, "user_request.md")
        sections = [
            section("global_summary", "Global narrative summary placeholder", "High-level story/world summary placeholder."),
            section("chapter_summaries", "Chapter summaries placeholder", "Chapter-level summaries are fixture-driven and deterministic."),
            section("entity_timeline_graph", "Entity/timeline/relationship graph placeholder", "Character, timeline, and relationship graph skeleton."),
            section("unresolved_threads", "Unresolved threads placeholder", "Open plot threads and continuity risks."),
        ]
        return make_pack(profile, budget, sections, omitted_sections=[omitted("Full prose omitted; drill down by chapter/source offset.", raw)], externalized=[external(raw, "raw_input", "Full narrative remains externalized.")], evidence_refs=[evidence(raw, "narrative_source")])