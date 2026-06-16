from __future__ import annotations
from pathlib import Path
from ..schemas import ContextBudget, ContextProfile
from .base import evidence, external, make_pack, omitted, section, source_ref


class LogContextPacker:
    def pack(self, profile: ContextProfile, budget: ContextBudget, request_text: str = "", run_dir: Path | None = None):
        raw = source_ref(run_dir, "pytest_failure_log.txt")
        sections = [section("error_clusters", "Error clusters", "Cluster repeated errors and failure signatures deterministically.", [raw]), section("stack_trace_extract", "Stack trace extract", "Extractive stack trace refs only; no rewritten code evidence.", [raw]), section("representative_lines", "Representative lines", "Representative stderr/stdout lines with progress noise omitted.", [raw])]
        return make_pack(profile, budget, sections, omitted_sections=[omitted("Repeated progress lines omitted.", raw)], externalized=[external(raw, "full_log", "Full log externalized for exact drilldown.")], evidence_refs=[evidence(raw, "log")])