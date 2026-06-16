"""Build ContextProfile from request text and local hints."""

from __future__ import annotations

from pathlib import Path
import yaml

from .schemas import ContextProfile
from .task_context_classifier import classify_actions, classify_task_context


SCENARIO_MAP = {
    "short_prompt": ("text", "user_prompt", "unstructured", "direct", "C0_direct", "small_task", "safe_lossy"),
    "code_repo": ("code", "repo", "graph_like", "repo_map", "C5_graph_or_tree_index", "coding_task", "no_lossy_compression"),
    "repo_audit": ("code", "repo", "graph_like", "repo_map", "C5_graph_or_tree_index", "repo_audit_task", "no_lossy_compression"),
    "code_debug": ("log", "local_file", "semi_structured", "extractive_compress", "C2_extractive", "log_analysis_task", "extractive_only"),
    "long_text_report": ("text", "local_file", "unstructured", "hierarchical_summary", "C4_hierarchical_summary", "long_text_task", "safe_lossy"),
    "narrative_or_novel": ("text", "local_file", "graph_like", "graph_index", "C4_hierarchical_summary", "narrative_task", "safe_lossy"),
    "image_or_screenshot": ("image", "local_file", "semi_structured", "visual_crop", "C2_extractive", "visual_task", "extractive_only"),
    "web_research": ("webpage", "web", "semi_structured", "retrieve", "C3_query_focused_compression", "web_research_task", "safe_lossy"),
    "crawler_batch": ("webpage", "crawler", "structured", "externalize_and_drilldown", "C6_externalize_and_drilldown", "crawl_task", "safe_lossy"),
    "data_table_or_stream": ("table", "local_file", "structured", "code_execution", "C6_externalize_and_drilldown", "data_analysis_task", "no_lossy_compression"),
    "log_analysis": ("log", "local_file", "semi_structured", "extractive_compress", "C2_extractive", "log_analysis_task", "extractive_only"),
    "abstract_reasoning": ("text", "user_prompt", "unstructured", "graph_index", "C5_graph_or_tree_index", "abstract_reasoning_task", "safe_lossy"),
    "tool_output": ("tool_output", "tool_output", "semi_structured", "tool_filter", "C1_trim", "tool_output_task", "safe_lossy"),
    "task_history": ("text", "memory", "semi_structured", "hierarchical_summary", "C3_query_focused_compression", "long_text_task", "safe_lossy"),
}


def estimate_tokens(text: str) -> int:
    return max(1, (len(text or "") + 3) // 4)


def length_tier(char_count: int, governance_config: dict | None = None) -> str:
    tiers = (governance_config or {}).get("length_tiers") or {}
    for name in ["S", "M", "L", "XL"]:
        max_chars = (tiers.get(name) or {}).get("max_chars")
        if max_chars is not None and char_count <= int(max_chars):
            return name
    if tiers:
        return "XXL"
    if char_count <= 2000:
        return "S"
    if char_count <= 12000:
        return "M"
    if char_count <= 80000:
        return "L"
    if char_count <= 500000:
        return "XL"
    return "XXL"


def load_context_config(agentlab_root: Path, filename: str) -> dict:
    path = agentlab_root / "config" / filename
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def build_context_profile(task_id: str, request_text: str = "", file_hints: list[str] | None = None, source_hints: list[str] | None = None, governance_config: dict | None = None) -> ContextProfile:
    scenario = classify_task_context(request_text, file_hints, source_hints)
    modality, source, structure, strategy, level, budget_policy, safety = SCENARIO_MAP[scenario]
    strategies = [strategy]
    if scenario == "narrative_or_novel":
        strategies.append("hierarchical_summary")
    if scenario in {"code_repo", "repo_audit"}:
        strategies = ["repo_map"]
    if scenario == "web_research":
        strategies = ["retrieve", "extractive_compress", "externalize_and_drilldown"]
    if scenario in {"crawler_batch", "data_table_or_stream", "tool_output"}:
        strategies.append("externalize_and_drilldown")
    precision = "exact_required" if safety == "no_lossy_compression" else ("high" if safety == "extractive_only" else "medium")
    return ContextProfile(
        task_id=task_id,
        modality=[modality],
        source_type=[source],
        length_tier=length_tier(len(request_text or ""), governance_config),
        precision_risk=precision,
        freshness_required=scenario == "web_research",
        structure_level=structure,
        action_type=classify_actions(request_text),
        compression_safety=safety,
        recommended_strategy=strategies,
        information_type=scenario,
        compression_level=level,
        budget_policy=budget_policy,
        reasons=[f"classified_as:{scenario}", f"strategy:{strategy}", f"compression:{level}"],
        warnings=[] if scenario != "image_or_screenshot" else ["P2-G does not perform real OCR or image-model analysis."],
    )