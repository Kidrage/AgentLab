from __future__ import annotations
from pathlib import Path
from ..schemas import ContextBudget, ContextProfile
from .base import evidence, external, make_pack, omitted, section, source_ref


class DataContextPacker:
    def pack(self, profile: ContextProfile, budget: ContextBudget, request_text: str = "", run_dir: Path | None = None):
        raw = source_ref(run_dir, "table_sample.csv")
        sections = [section("schema_profile", "Schema/profile placeholder", "Columns, types, null counts, and basic profile placeholder.", [raw]), section("sample_rows", "Sample rows limit", "Only bounded sample rows are allowed; full table is never embedded.", [raw]), section("local_execution", "Local execution recommended", "Data tasks should use local execution/profile refs instead of sending full tables to LLM.")]
        return make_pack(profile, budget, sections, omitted_sections=[omitted("All rows beyond bounded sample omitted.", raw)], externalized=[external(raw, "data_table", "Full data table externalized by default.")], evidence_refs=[evidence(raw, "data_table")])