from pathlib import Path

from agent_runtime.context_governance.information_profiler import build_context_profile

FIX = Path(__file__).parent / "fixtures" / "context_governance"


def text(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_short_prompt_direct():
    p = build_context_profile("task_x", text("short_prompt.txt"))
    assert p.information_type == "short_prompt"
    assert p.compression_level == "C0_direct"
    assert "direct" in p.recommended_strategy


def test_repo_manifest_github_task_repo_map():
    p = build_context_profile("task_x", "Fix bug in GitHub repository src/ tests/ CI")
    assert p.information_type in {"code_repo", "code_debug"}
    assert p.compression_safety in {"no_lossy_compression", "extractive_only"}


def test_required_scenarios_classify():
    cases = [
        ("pytest_failure_log.txt", "log_analysis", "C2_extractive"),
        ("long_novel_excerpt.txt", "narrative_or_novel", "C4_hierarchical_summary"),
        ("long_document_excerpt.txt", "long_text_report", "C4_hierarchical_summary"),
        ("image_ocr_mock.json", "image_or_screenshot", "C2_extractive"),
        ("webpage_clean_markdown.md", "web_research", "C3_query_focused_compression"),
        ("crawler_many_pages.jsonl", "crawler_batch", "C6_externalize_and_drilldown"),
        ("table_sample.csv", "data_table_or_stream", "C6_externalize_and_drilldown"),
        ("huge_tool_output.log", "tool_output", "C1_trim"),
        ("abstract_strategy_prompt.txt", "abstract_reasoning", "C5_graph_or_tree_index"),
        ("task_history_mock.yml", "task_history", "C3_query_focused_compression"),
    ]
    for filename, scenario, level in cases:
        p = build_context_profile("task_x", text(filename), file_hints=[filename])
        assert p.information_type == scenario
        assert p.compression_level == level
