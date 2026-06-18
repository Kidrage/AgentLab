"""Deterministic domain signal extraction for the S1-B Task Compiler.

This module is intentionally local-only and rule-based.  It does not import
provider SDKs, browse the web, execute shell commands, or inspect repositories.
The output is a transparent classification record that later compiler layers can
turn into capabilities, artifacts, acceptance gates, and approval policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from .mission_contract import MissionTaskType


@dataclass(frozen=True)
class DomainRule:
    """Keyword rule for one supported MissionTaskType."""

    task_type: MissionTaskType
    keywords: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class DomainClassification:
    """Transparent classification result for a raw user prompt."""

    task_type: MissionTaskType
    domain_signals: list[str] = field(default_factory=list)
    scores: dict[str, int] = field(default_factory=dict)
    matched_keywords: dict[str, list[str]] = field(default_factory=dict)


DOMAIN_RULES: tuple[DomainRule, ...] = (
    DomainRule(
        task_type=MissionTaskType.DEBUGGING,
        keywords=(
            "bug",
            "debug",
            "failure",
            "failing",
            "pytest",
            "traceback",
            "stack trace",
            "ci",
            "regression",
            "fix test",
        ),
        description="debugging or repair work",
    ),
    DomainRule(
        task_type=MissionTaskType.CODING,
        keywords=(
            "repo",
            "repository",
            "github",
            "test",
            "patch",
            "commit",
            "branch",
            "refactor",
            "cli",
            "api",
            "function",
            "class",
            "code",
            "implement",
        ),
        description="software engineering implementation work",
    ),
    DomainRule(
        task_type=MissionTaskType.RESEARCH,
        keywords=(
            "research",
            "investigate",
            "compare",
            "source",
            "citation",
            "latest",
            "report",
            "evidence",
            "sources",
        ),
        description="research requiring evidence and citations",
    ),
    DomainRule(
        task_type=MissionTaskType.BUSINESS,
        keywords=(
            "market",
            "company",
            "competitor",
            "industry",
            "business",
            "customer",
            "pricing",
            "go-to-market",
            "gtm",
        ),
        description="business analysis or market work",
    ),
    DomainRule(
        task_type=MissionTaskType.CREATIVE_LONGFORM,
        keywords=(
            "novel",
            "story",
            "script",
            "chapter",
            "character",
            "worldbuilding",
            "outline",
            "rewrite",
            "scene",
            "fiction",
        ),
        description="creative longform writing",
    ),
    DomainRule(
        task_type=MissionTaskType.DOCUMENT_PROCESSING,
        keywords=(
            "pdf",
            "docx",
            "document",
            "summarize",
            "extract",
            "table",
            "ocr",
            "parse",
            "format",
        ),
        description="document parsing, extraction, or summarization",
    ),
    DomainRule(
        task_type=MissionTaskType.DATA_ANALYSIS,
        keywords=(
            "csv",
            "xlsx",
            "spreadsheet",
            "dataframe",
            "chart",
            "statistics",
            "analyze data",
            "clean data",
            "dataset",
        ),
        description="structured data analysis",
    ),
    DomainRule(
        task_type=MissionTaskType.AUDIO_MUSIC,
        keywords=(
            "audio",
            "music",
            "mix",
            "master",
            "spatial audio",
            "hrtf",
            "mir",
            "stem",
            "stems",
            "loudness",
            "spectrogram",
            "speaker",
            "binaural",
        ),
        description="audio, music, or sound analysis work",
    ),
    DomainRule(
        task_type=MissionTaskType.MULTIMODAL,
        keywords=(
            "image",
            "screenshot",
            "video",
            "figure",
            "diagram",
            "photo",
            "ui screenshot",
            "visual",
        ),
        description="visual or multimodal input work",
    ),
    DomainRule(
        task_type=MissionTaskType.LOCAL_OPS,
        keywords=(
            "local file",
            "folder",
            "backup",
            "organize",
            "shell",
            "filesystem",
            "nas",
            "server",
            "deploy",
            "delete",
            "remove files",
        ),
        description="local operations on files, systems, or deployment targets",
    ),
    DomainRule(
        task_type=MissionTaskType.EDUCATION,
        keywords=(
            "teach",
            "explain",
            "lesson",
            "homework",
            "quiz",
            "study",
            "tutor",
        ),
        description="teaching, tutoring, or learning support",
    ),
)


TASK_TYPE_PRIORITY: tuple[MissionTaskType, ...] = (
    MissionTaskType.DEBUGGING,
    MissionTaskType.CODING,
    MissionTaskType.RESEARCH,
    MissionTaskType.BUSINESS,
    MissionTaskType.CREATIVE_LONGFORM,
    MissionTaskType.DOCUMENT_PROCESSING,
    MissionTaskType.DATA_ANALYSIS,
    MissionTaskType.AUDIO_MUSIC,
    MissionTaskType.MULTIMODAL,
    MissionTaskType.LOCAL_OPS,
    MissionTaskType.EDUCATION,
)


def normalize_prompt(prompt: str) -> str:
    """Normalize a prompt for deterministic keyword scoring."""

    return re.sub(r"\s+", " ", prompt.strip().lower())


def keyword_matches(normalized_prompt: str, keyword: str) -> bool:
    """Return True when a keyword or phrase is present as a signal."""

    normalized_keyword = keyword.lower().strip()
    if " " in normalized_keyword or "-" in normalized_keyword:
        return normalized_keyword in normalized_prompt
    return bool(re.search(rf"(?<![a-z0-9_]){re.escape(normalized_keyword)}(?![a-z0-9_])", normalized_prompt))


def score_domain_rule(prompt: str, rule: DomainRule) -> tuple[int, list[str]]:
    """Score a single rule and return matched keywords in declaration order."""

    normalized = normalize_prompt(prompt)
    matches = [keyword for keyword in rule.keywords if keyword_matches(normalized, keyword)]
    phrase_bonus = sum(1 for keyword in matches if " " in keyword or "-" in keyword)
    return len(matches) + phrase_bonus, matches


def classify_task_type(prompt: str) -> DomainClassification:
    """Classify a prompt into the strongest supported MissionTaskType.

    The classifier is deterministic: identical input always produces identical
    scores, tie-breaking follows TASK_TYPE_PRIORITY, and all secondary matches
    are preserved as domain_signals for auditability.
    """

    scores: dict[str, int] = {}
    matched_keywords: dict[str, list[str]] = {}
    for rule in DOMAIN_RULES:
        score, matches = score_domain_rule(prompt, rule)
        scores[rule.task_type.value] = score
        if matches:
            matched_keywords[rule.task_type.value] = matches

    best_type = MissionTaskType.UNKNOWN
    best_score = 0
    for task_type in TASK_TYPE_PRIORITY:
        score = scores.get(task_type.value, 0)
        if score > best_score:
            best_score = score
            best_type = task_type

    signals = build_domain_signal_notes(best_type, scores, matched_keywords)
    return DomainClassification(
        task_type=best_type,
        domain_signals=signals,
        scores=scores,
        matched_keywords=matched_keywords,
    )


def build_domain_signal_notes(
    primary: MissionTaskType,
    scores: dict[str, int],
    matched_keywords: dict[str, list[str]],
) -> list[str]:
    """Build stable human-readable signal notes for a compilation result."""

    notes: list[str] = []
    if primary == MissionTaskType.UNKNOWN:
        notes.append("no supported task type reached a positive keyword score")
        return notes
    notes.append(f"primary={primary.value} score={scores.get(primary.value, 0)}")
    for task_type in TASK_TYPE_PRIORITY:
        value = task_type.value
        matches = matched_keywords.get(value, [])
        if not matches:
            continue
        prefix = "primary" if task_type == primary else "secondary"
        notes.append(f"{prefix}:{value}:" + ",".join(matches))
    return notes
