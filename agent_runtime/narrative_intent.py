"""Shared narrative/article intent classification.

This module is intentionally small and deterministic.  It is the single place
for distinguishing longform chapter work, narrative audits, and plain article
drafting so mission compilation and task routing do not drift.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class NarrativeIntent:
    kind: str
    reason: str

    @property
    def is_narrative(self) -> bool:
        return self.kind in {"chapter", "chapter_batch", "audit"}


CHAPTER_RE = re.compile(
    r"(第\s*[\d一二三四五六七八九十百千]+\s*章|chapter\s*\d+|ch(?:apter)?[_\s-]*\d+)",
    re.I,
)

CHAPTER_WORD_RE = re.compile(r"(chapter|章节|正文)", re.I)

CHAPTER_RANGE_RE = re.compile(
    r"(前\s*[\d一二三四五六七八九十百千]+\s*章|"
    r"第\s*[\d一二三四五六七八九十百千]+\s*章\s*(?:到|至|-|~)\s*第?\s*[\d一二三四五六七八九十百千]+\s*章|"
    r"chapters?\s*\d+\s*(?:to|-|through)\s*\d+|"
    r"first\s+\d+\s+chapters)",
    re.I,
)

AUDIT_RE = re.compile(
    r"(audit|review|check|acceptance|promotion|narrative-eval|审计|验收|检查|连续性|晋升前)",
    re.I,
)

ARTICLE_RE = re.compile(
    r"(article|essay|report|product description|explainer|文章|报告|说明文|产品说明|分析文章|市场分析)",
    re.I,
)

ARTICLE_ACTION_RE = re.compile(r"(write|draft|create|generate|撰写|写|生成|创建)", re.I)

STORY_MARKER_RE = re.compile(
    r"(crown\s+of\s+ash|crown_of_ash|灰烬王冠|小说章节|长篇小说|角色圣经|重构蓝图|卷纲|世界观|人物弧线)",
    re.I,
)

GENERIC_STORY_RE = re.compile(r"(novel|fiction|manuscript|小说|故事|章节|正文)", re.I)

CONTINUATION_RE = re.compile(r"(续写|日更|继续写|下一章|continue writing|daily chapter)", re.I)


def classify_narrative_intent(text: str, *, active_longform_project: bool = False) -> NarrativeIntent:
    """Classify text as chapter, audit, article, or none.

    Plain articles about fiction markets, TV titles, or other non-story
    subjects must not route to longform chapter generation merely because they
    contain words like "小说" or "Crown".
    """
    raw = text or ""
    lowered = raw.lower()
    has_article = bool(ARTICLE_RE.search(raw))
    has_article_action = bool(ARTICLE_ACTION_RE.search(raw))
    has_chapter = bool(CHAPTER_RE.search(raw))
    has_chapter_word = bool(CHAPTER_WORD_RE.search(raw))
    has_chapter_range = bool(CHAPTER_RANGE_RE.search(raw))
    has_audit = bool(AUDIT_RE.search(raw))
    has_story_marker = bool(STORY_MARKER_RE.search(raw))
    has_generic_story = bool(GENERIC_STORY_RE.search(raw))
    has_continuation = bool(CONTINUATION_RE.search(raw))

    if has_audit and (has_chapter or has_chapter_range or has_story_marker or active_longform_project):
        return NarrativeIntent("audit", "audit_signal_with_narrative_scope")

    if has_article and has_article_action and not has_chapter and not has_continuation:
        return NarrativeIntent("article", "article_signal_without_chapter_scope")

    if has_chapter_range and (has_story_marker or has_generic_story or active_longform_project):
        return NarrativeIntent("chapter_batch", "chapter_range_with_story_scope")

    if "crown" in lowered and has_chapter:
        return NarrativeIntent("chapter", "crown_chapter_shorthand")

    if has_story_marker and (has_chapter or has_chapter_word or has_continuation or not has_article):
        return NarrativeIntent("chapter", "story_marker")

    if (has_chapter or has_chapter_word) and (has_generic_story or has_story_marker or active_longform_project):
        return NarrativeIntent("chapter", "chapter_marker_with_story_scope")

    if active_longform_project and (has_chapter or has_chapter_word or has_continuation):
        return NarrativeIntent("chapter", "active_project_continuation")

    return NarrativeIntent("none", "no_narrative_intent")
