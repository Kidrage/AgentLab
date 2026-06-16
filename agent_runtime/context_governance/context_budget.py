"""Context budget selection and savings estimates."""

from __future__ import annotations

from .information_profiler import estimate_tokens
from .schemas import ContextBudget, ContextProfile


DEFAULT_BUDGETS = {
    "small_task": {"max_input_tokens": 6000, "max_output_tokens": 2000},
    "coding_task": {"max_input_tokens": 16000, "max_output_tokens": 4000, "max_files": 12},
    "repo_audit_task": {"max_input_tokens": 22000, "max_output_tokens": 6000, "max_files": 20},
    "long_text_task": {"max_input_tokens": 18000, "max_output_tokens": 5000},
    "narrative_task": {"max_input_tokens": 18000, "max_output_tokens": 5000},
    "visual_task": {"max_input_tokens": 12000, "max_output_tokens": 3000, "max_crops": 4},
    "web_research_task": {"max_input_tokens": 9600, "max_output_tokens": 4000, "max_sources": 8},
    "crawl_task": {"max_input_tokens": 18000, "max_output_tokens": 5000, "max_sources": 20},
    "data_analysis_task": {"max_input_tokens": 14000, "max_output_tokens": 4000},
    "log_analysis_task": {"max_input_tokens": 16000, "max_output_tokens": 4000},
    "abstract_reasoning_task": {"max_input_tokens": 10000, "max_output_tokens": 4000},
    "tool_output_task": {"max_input_tokens": 8000, "max_output_tokens": 3000, "max_tool_output_tokens": 1200},
}


def build_context_budget(profile: ContextProfile, request_text: str = "", policy_config: dict | None = None) -> ContextBudget:
    budgets = (policy_config or {}).get("budgets") or {}
    raw = dict(DEFAULT_BUDGETS.get(profile.budget_policy, DEFAULT_BUDGETS["small_task"]))
    raw.update(budgets.get(profile.budget_policy) or {})
    baseline = estimate_tokens(request_text)
    capped = min(baseline, int(raw.get("max_input_tokens", 12000)))
    if profile.compression_level in {"C0_direct"}:
        packed = capped
    elif profile.compression_level in {"C1_trim", "C2_extractive"}:
        packed = min(capped, max(200, int(baseline * 0.55)))
    elif profile.compression_level in {"C6_externalize_and_drilldown"}:
        packed = min(capped, max(300, int(baseline * 0.15)))
    else:
        packed = min(capped, max(400, int(baseline * 0.35)))
    savings = 0.0 if baseline <= 0 else 1.0 - (packed / max(1, baseline))
    return ContextBudget(
        task_id=profile.task_id,
        max_input_tokens=int(raw.get("max_input_tokens", 12000)),
        max_output_tokens=int(raw.get("max_output_tokens", 4000)),
        max_tool_output_tokens=int(raw.get("max_tool_output_tokens", 1200)),
        max_sources=int(raw.get("max_sources", raw.get("max_pages_initial", 8) or 8)),
        max_files=int(raw.get("max_files", raw.get("max_repo_files_initial", 12) or 12)),
        max_crops=int(raw.get("max_crops", 4)),
        estimated_baseline_tokens=baseline,
        estimated_packed_tokens=packed,
        estimated_savings_ratio=savings,
        budget_policy=profile.budget_policy,
        warnings=[] if packed <= int(raw.get("max_input_tokens", 12000)) else ["packed context exceeds input budget"],
    )