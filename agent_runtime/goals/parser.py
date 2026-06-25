"""Goal command parser — deterministic, no subprocess, no network.

Parses `/goal <action>` and `/目标 <action>` commands into a shared
GoalActionSchema for downstream compilation and validation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GoalActionSchema:
    """Shared goal action schema — deterministic, serializable."""
    action: str  # "set", "plan", "progress", "validate", "report"
    project: str = ""
    text: str = ""  # raw user goal text
    domain: str = ""  # inferred domain for template matching
    template_id: str = ""  # resolved template ID
    aliases: list[str] = field(default_factory=list)
    raw_parts: list[str] = field(default_factory=list)


# ── Command aliases ──────────────────────────────────────────────────

_CHINESE_ACTION_ALIASES: dict[str, str] = {
    "目标": "set",
    "设定": "set",
    "计划": "plan",
    "规划": "plan",
    "进展": "progress",
    "进度": "progress",
    "验证": "validate",
    "校验": "validate",
    "报告": "report",
    "报表": "report",
}

_ENGLISH_ACTION_ALIASES: dict[str, str] = {
    "goal": "set",
    "set": "set",
    "plan": "plan",
    "progress": "progress",
    "validate": "validate",
    "report": "report",
}

_SHORT_ALIASES: dict[str, str] = {
    "/目标": "set",
    "/goal": "set",
    "/mb": "set",  # 目标 (mù biāo) short
    "/jh": "plan",  # 计划 (jì huà) short
    "/jz": "progress",  # 进展 (jìn zhǎn) short
    "/yz": "validate",  # 验证 (yàn zhèng) short
    "/bg": "report",  # 报告 (bào gào) short
}

# ── Domain keywords for template classification ─────────────────────

_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "codebase_build": [
        "codebase", "build", "compile", "app", "cli", "api", "library",
        "package", "module", "python", "rust", "typescript", "javascript",
        "go", "java", "task runner", "server", "frontend", "backend",
    ],
    "longform_creation": [
        "novel", "story", "fiction", "book", "series", "chapter",
        "worldbuilding", "character", "plot", "narrative", "screenplay",
        "script", "creative writing", "longform",
    ],
    "research_archive": [
        "research", "literature review", "paper", "academic", "survey",
        "systematic review", "citation", "bibliography", "references",
        "knowledge base", "knowledge graph",
    ],
    "video_generation": [
        "video", "youtube", "episode", "storyboard", "animation",
        "recording", "screenplay", "visual", "filming", "timeline",
    ],
    "document_knowledgebase": [
        "document", "knowledge base", "wiki", "technical doc",
        "whitepaper", "ingest", "index", "searchable", "pdf",
    ],
    "local_automation": [
        "automate", "automation", "cron", "file organization",
        "downloads folder", "classify files", "rename", "backup",
        "script", "workflow", "batch",
    ],
    "operator_os_goal_management": [
        "operator", "goal management", "objective", "OKR",
        "task management", "project governance", "milestone",
        "roadmap", "strategy",
    ],
}


def _infer_domain(text: str) -> str:
    """Infer domain from goal text using keyword matching."""
    lowered = text.lower()
    best_domain = "unknown_large_project"
    best_score = 0
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in lowered)
        if score > best_score:
            best_score = score
            best_domain = domain
    return best_domain


def _resolve_action(raw: str) -> str:
    """Resolve action from raw command text."""
    stripped = raw.strip()
    if not stripped:
        return "set"

    # Check full Chinese command: /目标 plan ...
    m = re.match(r"^/目标\s*(\S*)", stripped)
    if m:
        alias = m.group(1).strip()
        if alias and alias in _CHINESE_ACTION_ALIASES:
            return _CHINESE_ACTION_ALIASES[alias]
        if alias and alias in _ENGLISH_ACTION_ALIASES:
            return _ENGLISH_ACTION_ALIASES[alias]
        if alias in _SHORT_ALIASES:
            return _SHORT_ALIASES[alias]
        return "set"

    # Check English command: /goal plan ...
    m = re.match(r"^/goal\s*(\S*)", stripped)
    if m:
        alias = m.group(1).strip()
        if alias and alias in _ENGLISH_ACTION_ALIASES:
            return _ENGLISH_ACTION_ALIASES[alias]
        if alias and alias in _CHINESE_ACTION_ALIASES:
            return _CHINESE_ACTION_ALIASES[alias]
        return "set"

    # Check short aliases
    for alias, action in _SHORT_ALIASES.items():
        if stripped.startswith(alias):
            return action

    # Check bare action word (first word of raw text)
    first_word = stripped.split()[0] if stripped.split() else ""
    if first_word in _ENGLISH_ACTION_ALIASES:
        return _ENGLISH_ACTION_ALIASES[first_word]
    if first_word in _CHINESE_ACTION_ALIASES:
        return _CHINESE_ACTION_ALIASES[first_word]
    if stripped in _ENGLISH_ACTION_ALIASES:
        return _ENGLISH_ACTION_ALIASES[stripped]
    if stripped in _CHINESE_ACTION_ALIASES:
        return _CHINESE_ACTION_ALIASES[stripped]

    return "set"


def _extract_text(raw: str) -> str:
    """Extract goal text from command, stripping the prefix."""
    stripped = raw.strip()

    # Remove short aliases
    for alias in sorted(_SHORT_ALIASES, key=len, reverse=True):
        if stripped.startswith(alias):
            stripped = stripped[len(alias):].strip()

    # Remove /goal or /目标 prefix plus optional action word
    m = re.match(r"^/(?:goal|目标)\s*\S*\s*", stripped)
    if m:
        stripped = stripped[m.end():].strip()
        return stripped

    # For bare action words at the start, remove the action word
    first_word = stripped.split()[0] if stripped.split() else ""
    if first_word in _ENGLISH_ACTION_ALIASES or first_word in _CHINESE_ACTION_ALIASES:
        # Remove the action word from the text
        rest = stripped[len(first_word):].strip()
        return rest if rest else stripped  # If text is only the action word, return as-is

    return stripped


def _extract_project(text: str) -> str:
    """Extract --project flag from text if present."""
    m = re.search(r"--project\s+(\S+)", text)
    if m:
        return m.group(1)
    m = re.search(r"-p\s+(\S+)", text)
    if m:
        return m.group(1)
    return ""


def parse_goal_command(raw_text: str) -> GoalActionSchema:
    """Parse a /goal or /目标 command into a deterministic GoalActionSchema.

    This function is pure — no subprocess, no network, no file I/O.
    """
    action = _resolve_action(raw_text)
    text = _extract_text(raw_text)
    project = _extract_project(raw_text)
    domain = _infer_domain(text) if text else "unknown_large_project"

    return GoalActionSchema(
        action=action,
        project=project,
        text=text,
        domain=domain,
        template_id=domain,
        aliases=sorted(_SHORT_ALIASES),
        raw_parts=raw_text.strip().split(),
    )
