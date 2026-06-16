"""Deterministic task/source classification for P2-G."""

from __future__ import annotations

from pathlib import Path
import re


KEYWORDS: dict[str, list[str]] = {
    "code_debug": ["pytest", "traceback", "stack trace", "bug", "fix", "ci log", "stderr", "报错"],
    "repo_audit": ["repo audit", "repository review", "audit repo", "验收", "审计", "review repository"],
    "code_repo": ["repo", "repository", "github", "refactor", "ci", "src/", "tests/", "代码仓库"],
    "narrative_or_novel": ["novel", "小说", "剧本", "chapter", "character", "plot", "timeline", "worldbuilding"],
    "image_or_screenshot": ["image", "screenshot", "图片", "截图", "ocr", "chart", "table image", "image_ocr"],
    "web_research": ["search", "web", "latest", "docs", "pricing", "regulation", "搜索", "网页", "官网"],
    "crawler_batch": ["crawl", "spider", "scraper", "scrape", "爬虫", "批量网页", "many pages"],
    "data_table_or_stream": ["csv", "excel", "dataframe", "table", "telemetry", "stream", "数据流", "表格"],
    "log_analysis": ["log", "stack trace", "traceback", "error log", "ci log", "stderr"],
    "abstract_reasoning": ["architecture", "strategy", "roadmap", "design", "compare", "tradeoff", "抽象", "架构", "路线"],
    "tool_output": ["tool output", "command output", "stdout", "stderr", "exit code", "huge output"],
    "task_history": ["task history", "conversation history", "handoff", "failed attempts", "任务历史"],
}


EXTENSION_HINTS = {
    ".py": "code_repo", ".js": "code_repo", ".ts": "code_repo", ".go": "code_repo",
    ".md": "long_text_report", ".txt": "long_text_report",
    ".log": "log_analysis", ".jsonl": "crawler_batch", ".csv": "data_table_or_stream",
    ".xls": "data_table_or_stream", ".xlsx": "data_table_or_stream",
    ".png": "image_or_screenshot", ".jpg": "image_or_screenshot", ".jpeg": "image_or_screenshot",
    ".yml": "task_history", ".yaml": "task_history",
}


def _contains_any(text: str, words: list[str]) -> bool:
    lowered = text.lower()
    for word in words:
        w = word.lower()
        if re.fullmatch(r"[a-z0-9_]+", w):
            if re.search(rf"(?<![a-z0-9_]){re.escape(w)}(?![a-z0-9_])", lowered):
                return True
        elif w in lowered:
            return True
    return False


def classify_task_context(request_text: str = "", file_hints: list[str] | None = None, source_hints: list[str] | None = None) -> str:
    """Return one of the P2-G scenario labels using stable priority rules."""
    text = "\n".join([request_text or "", " ".join(file_hints or []), " ".join(source_hints or [])])
    hint_names = " ".join(file_hints or []).lower()
    if "tool_output" in hint_names or "huge_tool_output" in hint_names:
        return "tool_output"
    priority = [
        "crawler_batch", "narrative_or_novel", "image_or_screenshot", "data_table_or_stream", "task_history",
        "log_analysis", "tool_output", "repo_audit", "code_debug", "code_repo",
        "web_research", "abstract_reasoning",
    ]
    for label in priority:
        if _contains_any(text, KEYWORDS.get(label, [])):
            return label
    hints = [Path(h).suffix.lower() for h in (file_hints or [])]
    for suffix in hints:
        if suffix in EXTENSION_HINTS:
            return EXTENSION_HINTS[suffix]
    if len(request_text or "") > 12000:
        return "long_text_report"
    return "short_prompt"


def classify_actions(text: str) -> list[str]:
    lowered = (text or "").lower()
    mapping = {
        "summarize": ["summarize", "摘要", "总结"],
        "modify": ["modify", "edit", "fix", "refactor", "修改", "修复"],
        "debug": ["debug", "traceback", "error", "pytest", "调试", "报错"],
        "extract": ["extract", "抽取", "提取"],
        "compare": ["compare", "对比", "比较", "tradeoff"],
        "decide": ["decide", "decision", "选择", "决策"],
        "reason": ["reason", "architecture", "strategy", "推理", "架构"],
    }
    actions = [name for name, keys in mapping.items() if _contains_any(lowered, keys)]
    return actions or ["answer"]