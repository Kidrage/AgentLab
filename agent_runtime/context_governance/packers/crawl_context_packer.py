from __future__ import annotations
from pathlib import Path
from ..schemas import ContextBudget, ContextProfile
from .base import evidence, external, make_pack, omitted, section, source_ref


class CrawlContextPacker:
    def pack(self, profile: ContextProfile, budget: ContextBudget, request_text: str = "", run_dir: Path | None = None):
        raw = source_ref(run_dir, "crawler_many_pages.jsonl")
        sections = [section("schema", "Schema placeholder", "Inferred crawl record schema placeholder.", [raw]), section("batch_summary", "Batch summary", f"Summarize initial batch up to {budget.max_sources} pages deterministically.", [raw]), section("sample_pages", "Sample pages", "Representative sample page refs only."), section("anomaly_refs", "Anomaly refs", "Outliers, duplicates, and parse failures as refs.")]
        return make_pack(profile, budget, sections, omitted_sections=[omitted("Full crawl body externalized.", raw)], externalized=[external(raw, "crawl_output", "Full crawl output must stay outside context pack.")], evidence_refs=[evidence(raw, "crawl_jsonl")], warnings=["No real crawler is invoked in P2-G."])