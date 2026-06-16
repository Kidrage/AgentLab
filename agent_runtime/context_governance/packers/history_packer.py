from __future__ import annotations
from pathlib import Path
from ..schemas import ContextBudget, ContextProfile
from .base import evidence, external, make_pack, omitted, section, source_ref


class HistoryPacker:
    def pack(self, profile: ContextProfile, budget: ContextBudget, request_text: str = "", run_dir: Path | None = None):
        raw = source_ref(run_dir, "task_history_mock.yml")
        sections = [section("immutable_goal", "Immutable goal", "Original user goal and acceptance constraints."), section("constraints", "Constraints", "Non-negotiable constraints and safety boundaries."), section("decisions", "Decisions", "Accepted decisions and rationale."), section("failed_attempts", "Failed attempts", "Attempts, failures, and why they failed."), section("current_state", "Current state", "Latest known state and artifacts."), section("next_actions", "Next actions", "Concrete next actions for continuation.")]
        return make_pack(profile, budget, sections, omitted_sections=[omitted("Verbose chat turns condensed and externalized.", raw)], externalized=[external(raw, "raw_input", "Full task history externalized.")], evidence_refs=[evidence(raw, "task_history")])