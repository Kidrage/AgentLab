
"""Lightweight task routing for AgentLab Phase 2A.

This module only recommends which agent roles should participate. It does not
execute agents or modify source files.
"""

from __future__ import annotations

import re
from typing import Any

try:
    from agent_runtime.schemas import AgentRoute
    from agent_runtime.protocols.artifact_task import (
        ARTIFACT_PRODUCER_ROLE,
        infer_artifact_components,
        infer_artifact_type,
    )
    from agent_runtime.routing.route_catalog import RouteCatalog
    from agent_runtime.narrative_intent import classify_narrative_intent
except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
    from schemas import AgentRoute
    from protocols.artifact_task import (
        ARTIFACT_PRODUCER_ROLE,
        infer_artifact_components,
        infer_artifact_type,
    )
    from routing.route_catalog import RouteCatalog
    from narrative_intent import classify_narrative_intent


# ── Implementation intent signals ─────────────────────────────────────────
# Strong keywords that indicate the user wants code changes, not just analysis.
IMPLEMENTATION_HINTS: tuple[str, ...] = (
    "implement",
    "patch",
    "modify",
    "edit",
    "create file",
    "add test",
    "add tests",
    "fix",
    "wire",
    "integrate",
    "generate code",
    "write module",
    "update config",
    "run pytest",
    "make ci pass",
    "produce implementation report",
    "implementation report",
    "change code",
    "write code",
    "code change",
    "apply patch",
    "make change",
    "commit",
    "push",
    "pull request",
    # Chinese equivalents / 中文等价信号
    "实现",
    "修复",
    "改代码",
    "写补丁",
    "创建文件",
    "加测试",
    "接入",
    "落地",
    "过ci",
    "过 ci",
    "生成实现报告",
    "修改代码",
    "写代码",
    "应用补丁",
    "提交",
    "合并请求",
    "实现补丁",
    "改仓库",
    "修改仓库",
    "增加测试",
    "生成实现",
)


# ── Explicit analysis-only override signals ──────────────────────────────
# When these appear, the user *explicitly* wants analysis without implementation,
# even if the prompt also contains implementation-sounding keywords.
EXPLICIT_ANALYSIS_ONLY_HINTS: tuple[str, ...] = (
    "analysis only",
    "planning only",
    "do not modify files",
    "no implementation",
    "只分析",
    "只规划",
    "不要改代码",
    "不要落地",
    "不实现",
    "仅分析",
    "仅评估",
    "仅规划",
    "analysis-only",
    "design only",
    "do not implement",
    "don't implement",
)


# ── Implementation executor agent names ──────────────────────────────────
IMPLEMENTATION_EXECUTORS: frozenset[str] = frozenset({
    "Coder",
    "external_ide_ai",
    "manual_patch_submitter",
    "claude_code",
})


ARTIFACT_PRODUCTION_ACTION_HINTS: tuple[str, ...] = (
    "generate",
    "create",
    "draft",
    "write",
    "make",
    "produce",
    "export",
    "render",
    "生成",
    "创建",
    "制作",
    "写",
    "输出",
    "导出",
    "渲染",
)


ARTICLE_LIGHT_HINTS: tuple[str, ...] = (
    "article",
    "essay",
    "short article",
    "product description",
    "explainer",
    "说明文章",
    "说明文",
    "产品说明",
    "写文章",
    "短文",
    "分析文章",
    "市场分析",
    "analysis article",
)


CODE_IMPLEMENTATION_CONTEXT_HINTS: tuple[str, ...] = (
    "code",
    "repo",
    "repository",
    "module",
    "function",
    "class",
    "test",
    "pytest",
    "ci",
    "代码",
    "仓库",
    "模块",
    "函数",
    "测试",
    "接口",
    "配置",
)


NON_CODE_PRODUCTION_SYSTEM_HINTS: tuple[str, ...] = (
    "immersive",
    "installation",
    "exhibition",
    "show control",
    "lighting cue",
    "sound cue",
    "asset pipeline",
    "scene state",
    "生成系统",
    "生产链路",
    "生产线",
    "沉浸式",
    "装置",
    "展览",
    "展演",
    "灯光cue",
    "声音cue",
    "声音角色",
    "空间装置",
    "场景状态",
    "多轮渲染",
    "长期维护",
)


OBSERVATION_ACTION_HINTS: tuple[str, ...] = (
    "summarize",
    "summary",
    "transcript",
    "transcription",
    "extract",
    "ocr",
    "read",
    "inspect",
    "observe",
    "analyze",
    "understand",
    "describe",
    "transcribe",
    "总结",
    "概括",
    "提取",
    "识别",
    "读取",
    "检查",
    "观察",
    "分析",
    "理解",
    "描述",
    "转录",
)


OBSERVATION_SOURCE_HINTS: tuple[str, ...] = (
    "long text",
    "this text",
    "the following text",
    "attached text",
    "provided text",
    "attached image",
    "this image",
    "image attachment",
    "attached picture",
    "this picture",
    "attached photo",
    "this photo",
    "attached screenshot",
    "this screenshot",
    "screenshot.",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    "attached video",
    "this video",
    "provided video",
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    "attached audio",
    "this audio",
    "provided audio",
    "audio recording",
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".flac",
    "attached pdf",
    "this pdf",
    ".pdf",
    "attached document",
    "this document",
    "provided document",
    ".docx",
    "这段长文本",
    "这篇长文",
    "以下长文",
    "以下文本",
    "附件文本",
    "这张图片",
    "这张图",
    "附件图片",
    "附件图像",
    "这张照片",
    "这张截图",
    "这段视频",
    "这个视频",
    "附件视频",
    "视频文件",
    "这段音频",
    "这个音频",
    "附件音频",
    "音频文件",
    "附件 pdf",
    "附件pdf",
    "这个 pdf",
    "这个pdf",
    "这份 pdf",
    "这份pdf",
    "这份文档",
    "这个文档",
    "附件文档",
)


MEDIA_PRODUCTION_ACTION_HINTS: tuple[str, ...] = (
    "generate",
    "create",
    "make",
    "produce",
    "render",
    "生成",
    "创建",
    "制作",
    "渲染",
)


MEDIA_TARGET_HINTS: tuple[str, ...] = (
    "image",
    "picture",
    "photo",
    "poster",
    "illustration",
    "video",
    "movie",
    "audio",
    "voiceover",
    "media",
    "图片",
    "图像",
    "海报",
    "插画",
    "视频",
    "影片",
    "音频",
    "配音",
    "媒体",
)


def _detect_implementation_intent(text: str) -> bool:
    """Return True if *text* contains strong implementation signals.

    Explicit analysis-only overrides take precedence — if the user says
    "analysis only" or "不要改代码", we return False even when implementation
    keywords are present.
    """
    lowered = text.lower()

    # Explicit override wins
    for hint in EXPLICIT_ANALYSIS_ONLY_HINTS:
        if hint.lower() in lowered:
            return False

    for hint in IMPLEMENTATION_HINTS:
        if hint.lower() in lowered:
            return True

    return False


def _has_implementation_executor(agents: list[str]) -> bool:
    """Return True if *agents* contains at least one implementation executor."""
    return bool(set(agents) & IMPLEMENTATION_EXECUTORS)


def _detect_artifact_production_intent(text: str) -> tuple[bool, str | None]:
    """Return whether text asks for a non-code deliverable to be produced."""
    lowered = text.lower()
    artifact_type = infer_artifact_type(text)
    if not artifact_type:
        return False, None
    if artifact_type == "text" and "implementation report" in lowered:
        return False, None
    has_action = any(hint.lower() in lowered for hint in ARTIFACT_PRODUCTION_ACTION_HINTS)
    return has_action, artifact_type if has_action else None


def _detect_article_light_intent(text: str, artifact_type: str | None) -> bool:
    if artifact_type != "text":
        return False
    lowered = text.lower()
    return any(hint.lower() in lowered for hint in ARTICLE_LIGHT_HINTS)


def _detect_code_implementation_context(text: str) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in CODE_IMPLEMENTATION_CONTEXT_HINTS)


def _detect_non_code_production_system_intent(text: str) -> bool:
    lowered = text.lower()
    return any(hint.lower() in lowered for hint in NON_CODE_PRODUCTION_SYSTEM_HINTS)


def _detect_observation_intent(text: str) -> bool:
    """Return whether text asks to inspect an explicit input artifact."""
    lowered = text.lower()
    has_action = any(hint.lower() in lowered for hint in OBSERVATION_ACTION_HINTS)
    has_source = any(hint.lower() in lowered for hint in OBSERVATION_SOURCE_HINTS)
    # Production verbs can describe a read-only derived report (for example,
    # "make a transcript of attached audio").  Treat a request as media
    # production only when the verb directly governs a media target.  This
    # preserves genuine generation requests such as "create a video" and
    # "render this image" without letting the source noun override an explicit
    # summary/OCR/transcription request.
    production_actions = "|".join(
        re.escape(hint)
        for hint in MEDIA_PRODUCTION_ACTION_HINTS
        if hint.isascii()
    )
    media_targets = "|".join(
        re.escape(hint)
        for hint in MEDIA_TARGET_HINTS
        if hint.isascii()
    )
    creates_media = bool(
        re.search(
            rf"\b(?:{production_actions})\b\s+(?:(?:an?|the|this|that|new)\s+)?(?:{media_targets})\b",
            lowered,
        )
    )
    if not creates_media:
        chinese_actions = tuple(
            hint for hint in MEDIA_PRODUCTION_ACTION_HINTS if not hint.isascii()
        )
        chinese_targets = tuple(
            hint for hint in MEDIA_TARGET_HINTS if not hint.isascii()
        )
        creates_media = any(action in lowered for action in chinese_actions) and any(
            target in lowered for target in chinese_targets
        )
    if creates_media:
        return False
    return has_action and has_source


RESEARCH_HINTS = (
    "latest",
    "current",
    "docs",
    "api",
    "pricing",
    "regulation",
    "standard",
    "external",
    "research",
    # competitive intelligence / 竞品研究
    "competitor",
    "competitor analysis",
    "competitive",
    "comparison",
    "survey",
    "benchmark",
    "竞品",
    "同类产品",
    "对比",
    "调研",
    "竞争对手",
    "行业分析",
    "替代品",
    "alternative",
)

EVALUATION_HINTS = (
    "evaluate",
    "evaluation",
    "assessment",
    "assess",
    "benchmark",
    "performance evaluation",
    "performance benchmark",
    "comprehensive evaluation",
    "architecture review",
    "system review",
    "audit report",
    "compare",
    "comparison",
    "评估",
    "全面评估",
    "性能评估",
    "基准测试",
    "架构评估",
    "系统评估",
    "审计报告",
    "对比分析",
)

INTERFACE_HINTS = (
    "api",
    "schema",
    "protocol",
    "contract",
    "integration",
    "io",
    "metadata",
    "database",
    "migration",
    "ui",
)

LARGE_HINTS = (
    "architecture",
    "refactor",
    "multi-module",
    "cross-module",
    "migration",
    "rewrite",
    "performance",
    "security",
    "release",
)


def _configured_hints(routing_config: dict | None, key: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if not routing_config:
        return fallback
    hints = routing_config.get("keyword_hints", {}).get(key)
    return tuple(hints) if hints else fallback


def _configured_route(routing_config: dict | None, key: str, fallback: list[str]) -> list[str]:
    agents = RouteCatalog.from_config(routing_config).agents_for(key)
    return agents or fallback


def _configured_route_size(routing_config: dict | None, key: str, fallback: str) -> str:
    catalog = RouteCatalog.from_config(routing_config)
    if not catalog.has_route(key):
        return fallback
    catalog_size = catalog.size_for(key)
    return catalog_size or fallback


def recommend_route(
    task_text: str,
    routing_config: dict | None = None,
    known_agents: list[str] | None = None,
) -> AgentRoute:
    """Return a conservative route based on task wording.

    Implementation intent (keywords like ``implement``, ``patch``, ``fix``)
    takes precedence over evaluation hints.  An explicit "analysis only"
    override suppresses implementation routing.
    """
    text = task_text.lower()
    thresholds = (routing_config or {}).get("task_size_thresholds", {})
    medium_chars = int(thresholds.get("medium_characters", 800))
    large_chars = int(thresholds.get("large_characters", 2500))

    research_hints = _configured_hints(routing_config, "research", RESEARCH_HINTS)
    evaluation_hints = _configured_hints(routing_config, "evaluation", EVALUATION_HINTS)
    interface_hints = _configured_hints(routing_config, "interface", INTERFACE_HINTS)
    large_hints = _configured_hints(routing_config, "large_or_risky", LARGE_HINTS)

    # ── Intent detection ──────────────────────────────────────────────────
    # Detect implementation intent from the ORIGINAL text (preserving case
    # so Chinese characters match correctly).
    wants_implementation = _detect_implementation_intent(task_text)
    wants_artifact, artifact_type = _detect_artifact_production_intent(task_text)
    artifact_components = infer_artifact_components(task_text) if wants_artifact else []
    media_only_artifact = bool(artifact_components) and set(
        artifact_components
    ).issubset({"image", "video"})
    wants_non_code_production_system = _detect_non_code_production_system_intent(task_text)
    wants_observation = _detect_observation_intent(task_text)
    narrative_intent = classify_narrative_intent(task_text)
    is_creative_writing = narrative_intent.is_narrative

    wants_evaluation = any(hint in text for hint in evaluation_hints)
    wants_research = any(hint in text for hint in research_hints)
    touches_interfaces = any(hint in text for hint in interface_hints)
    looks_large = any(hint in text for hint in large_hints) or len(text) > large_chars
    looks_medium = len(text) > medium_chars

    route_catalog = RouteCatalog.from_config(routing_config)

    # ── Route selection ───────────────────────────────────────────────────
    # Implementation intent overrides evaluation route — if the user asks to
    # implement code AND evaluate it, implementation wins.
    if is_creative_writing and not _detect_code_implementation_context(task_text):
        route_key = "narrative_heavy_audit" if narrative_intent.kind == "audit" else "narrative_light_chapter"
        task_size = route_catalog.size_for(route_key)
        agents = route_catalog.agents_for(route_key)
    elif wants_implementation:
        # Implementation-required: pick the right-sized route that includes
        # an implementation executor (Coder).
        if looks_large:
            route_key = "large_or_risky_task"
            task_size = route_catalog.size_for(route_key)
            agents = route_catalog.agents_for(route_key)
        elif touches_interfaces:
            route_key = "interface_sensitive_task"
            task_size = route_catalog.size_for(route_key)
            agents = route_catalog.agents_for(route_key)
        elif wants_research:
            route_key = "research_sensitive_task"
            task_size = route_catalog.size_for(route_key)
            agents = route_catalog.agents_for(route_key)
        elif looks_medium:
            route_key = "medium_task"
            task_size = route_catalog.size_for(route_key)
            agents = route_catalog.agents_for(route_key)
        else:
            route_key = "small_task"
            task_size = route_catalog.size_for(route_key)
            agents = route_catalog.agents_for(route_key)

        # Safety net: if the selected route still lacks an implementation
        # executor (e.g. config overrides removed Coder), inject Coder.
        if not _has_implementation_executor(agents):
            # Insert Coder after Supervisor (index 0)
            if "Coder" in set(known_agents or (routing_config or {}).get("agent_order", [])):
                agents.insert(1, "Coder")
                if "TesterAuditor" not in agents:
                    agents.insert(2, "TesterAuditor")
        if wants_artifact and ARTIFACT_PRODUCER_ROLE not in agents:
            insert_at = agents.index("Coder") + 1 if "Coder" in agents else len(agents)
            agents.insert(insert_at, ARTIFACT_PRODUCER_ROLE)

    elif wants_observation:
        route_key = "observation_task"
        task_size = route_catalog.size_for(route_key)
        agents = route_catalog.agents_for(route_key)
    elif wants_artifact and media_only_artifact:
        route_key = "media_generation_task"
        task_size = route_catalog.size_for(route_key)
        agents = route_catalog.agents_for(route_key)
    elif wants_artifact or wants_non_code_production_system:
        route_key = "article_light_draft" if _detect_article_light_intent(task_text, artifact_type) else "artifact_production_task"
        task_size = "medium" if artifact_type == "mixed" or looks_medium or wants_non_code_production_system else "small"
        if route_key == "article_light_draft":
            task_size = route_catalog.size_for(route_key)
        agents = route_catalog.agents_for(route_key)
    elif wants_evaluation:
        route_key = "evaluation_task"
        task_size = route_catalog.size_for(route_key)
        agents = route_catalog.agents_for(route_key)
    elif looks_large:
        route_key = "large_or_risky_task"
        task_size = route_catalog.size_for(route_key)
        agents = route_catalog.agents_for(route_key)
    elif touches_interfaces:
        route_key = "interface_sensitive_task"
        task_size = route_catalog.size_for(route_key)
        agents = route_catalog.agents_for(route_key)
    elif wants_research:
        route_key = "research_sensitive_task"
        task_size = route_catalog.size_for(route_key)
        agents = route_catalog.agents_for(route_key)
    elif looks_medium:
        route_key = "medium_task"
        task_size = route_catalog.size_for(route_key)
        agents = route_catalog.agents_for(route_key)
    else:
        route_key = "small_task"
        task_size = route_catalog.size_for(route_key)
        agents = route_catalog.agents_for(route_key)

    # ── Explicit analysis-only: strip implementation executors ────────────
    # If the user explicitly asked for analysis-only, remove Coder even when
    # the route template includes it (e.g. small_task defaults to Coder).
    _wants_explicit_analysis_only = any(
        hint.lower() in text for hint in EXPLICIT_ANALYSIS_ONLY_HINTS
    )
    if _wants_explicit_analysis_only and not wants_implementation:
        agents = [a for a in agents if a not in IMPLEMENTATION_EXECUTORS and a != ARTIFACT_PRODUCER_ROLE]
        # If Coder was removed, also remove TesterAuditor (analysis-only
        # doesn't need test execution)
        if "Coder" not in agents:
            agents = [a for a in agents if a != "TesterAuditor"]

    # ── Build rationale ───────────────────────────────────────────────────
    rationale: list[str] = [
        "Supervisor always defines scope, token budget, and stop rules.",
        f"Route selected by {route_key} using smallest_safe_route rules.",
    ]
    if is_creative_writing and route_key in {"narrative_light_chapter", "narrative_heavy_audit"}:
        rationale.append(
            f"Creative writing domain detected; use {route_key} instead of "
            "generic artifact, interface, or large-risk routes."
        )
        if route_key == "narrative_light_chapter":
            rationale.append("Light chapter path selected; Reviewer/Scribe/Verifier are reserved for staged audits or promotion.")
        else:
            rationale.append("Heavy audit path selected; audit existing narrative artifacts instead of defaulting to chapter generation.")
    if _wants_explicit_analysis_only:
        rationale.append(
            "Explicit analysis-only signal detected; "
            "implementation executors removed from route."
        )
    elif wants_implementation:
        rationale.append(
            "Implementation intent detected; route includes an implementation "
            "executor for code changes."
        )
    elif wants_observation:
        rationale.append(
            "Explicit source-observation intent detected; Observer inspects the "
            "assigned input without producing or modifying it."
        )
    elif wants_artifact or wants_non_code_production_system:
        artifact_label = artifact_type or "production_system"
        rationale.append(
            f"Artifact production intent detected ({artifact_label}); route includes "
            f"{ARTIFACT_PRODUCER_ROLE} with an ArtifactTask contract."
        )
    if "Coder" in agents:
        rationale.append("Coder and Tester/Auditor are required for implementation and verification.")
    if ARTIFACT_PRODUCER_ROLE in agents:
        rationale.append("ArtifactProducer owns non-code and mixed deliverables; Coder remains scoped to code/automation work.")
    elif wants_implementation and not _has_implementation_executor(agents):
        rationale.append(
            "Implementation required but Coder not in route — "
            "check executor availability."
        )
    elif not wants_implementation:
        rationale.append("Analysis-only route selected; Coder is skipped because no source implementation is requested.")
    if wants_research:
        rationale.append("Research hints detected; include Researcher when route requires current or external facts.")
    if wants_evaluation:
        if wants_implementation:
            rationale.append(
                "Evaluation hints detected but implementation intent overrides; "
                "Coder is included for code changes."
            )
        else:
            rationale.append("Evaluation hints detected; use analysis-only L3 route and skip Coder by default.")
    if touches_interfaces:
        rationale.append("Interface hints detected; include InterfaceMapper for boundaries and contracts.")
    if looks_large:
        rationale.append("Large or risky hints detected; include the full route.")

    all_agents = set(known_agents or (routing_config or {}).get("agent_order") or [
        "Supervisor",
        "RepoScout",
        "Researcher",
        "Observer",
        "InterfaceMapper",
        "Coder",
        ARTIFACT_PRODUCER_ROLE,
        "TesterAuditor",
        "Verifier",
        "Archivist",
    ])
    skipped = sorted(all_agents.difference(agents))

    return AgentRoute(
        task_size=task_size,
        agents=agents,
        rationale=rationale,
        skipped_agents=skipped,
        route_key=route_key,
    )
