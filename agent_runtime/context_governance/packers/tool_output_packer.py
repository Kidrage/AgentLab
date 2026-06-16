from __future__ import annotations
from pathlib import Path
from ..schemas import ContextBudget, ContextProfile
from .base import evidence, external, make_pack, omitted, section, source_ref


class ToolOutputPacker:
    def pack(self, profile: ContextProfile, budget: ContextBudget, request_text: str = "", run_dir: Path | None = None):
        raw = source_ref(run_dir, "huge_tool_output.log")
        sections = [section("summary", "Summary", "Filtered deterministic summary of tool output."), section("exit_code", "Exit code if known", "Exit code placeholder from execution record."), section("stderr_tail", "stderr tail", f"Bounded stderr tail up to {budget.max_tool_output_tokens} tokens."), section("stack_trace", "Stack trace", "Extractive stack trace if present."), section("changed_files", "Changed files", "Changed file refs if tool produced edits.")]
        return make_pack(profile, budget, sections, omitted_sections=[omitted("Full noisy stdout omitted.", raw)], externalized=[external(raw, "full_log", "Full tool output externalized by default.")], evidence_refs=[evidence(raw, "tool_output")])