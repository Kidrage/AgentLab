
"""Lightweight task routing for AgentLab Phase 2A.

This module only recommends which agent roles should participate. It does not
execute agents or modify source files.
"""

from __future__ import annotations

from typing import Any

from schemas import AgentRoute

try:
    from protocols.artifact_task import ARTIFACT_PRODUCER_ROLE, infer_artifact_type
except ImportError:  # pragma: no cover - package import path
    from agent_runtime.protocols.artifact_task import ARTIFACT_PRODUCER_ROLE, infer_artifact_type


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
    if not routing_config:
        return fallback
    routes = routing_config.get("routes", {})
    route_entry = routes.get(key)
    if isinstance(route_entry, dict):
        configured_agents = route_entry.get("agents")
    else:
        configured_agents = route_entry
    agents = list(configured_agents or fallback)
    if "Coder" in agents and "TesterAuditor" not in agents:
        insert_at = agents.index("Coder") + 1
        agents.insert(insert_at, "TesterAuditor")
    return agents


def _configured_route_size(routing_config: dict | None, key: str, fallback: str) -> str:
    if not routing_config:
        return fallback
    route_entry = routing_config.get("routes", {}).get(key)
    configured_size = route_entry.get("size") if isinstance(route_entry, dict) else None
    size_map = {
        "L1": "small",
        "L2": "medium",
        "L3": "large",
        "S0": "small",
        "S1": "small",
        "S2": "medium",
        "S3": "large",
        "S4": "large",
    }
    return size_map.get(str(configured_size), fallback)


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

    wants_evaluation = any(hint in text for hint in evaluation_hints)
    wants_research = any(hint in text for hint in research_hints)
    touches_interfaces = any(hint in text for hint in interface_hints)
    looks_large = any(hint in text for hint in large_hints) or len(text) > large_chars
    looks_medium = len(text) > medium_chars

    fallback_small = ["Supervisor", "Coder", "TesterAuditor", "Verifier"]
    fallback_medium = ["Supervisor", "RepoScout", "Coder", "TesterAuditor", "Verifier", "Archivist"]
    fallback_interface = ["Supervisor", "RepoScout", "InterfaceMapper", "Coder", "TesterAuditor", "Verifier", "Archivist"]
    fallback_research = ["Supervisor", "Researcher", "Coder", "TesterAuditor", "Verifier"]
    fallback_artifact = ["Supervisor", ARTIFACT_PRODUCER_ROLE, "TesterAuditor", "Verifier", "Archivist"]
    fallback_evaluation = [
        "Supervisor",
        "RepoScout",
        "Researcher",
        "InterfaceMapper",
        "TesterAuditor",
        "Verifier",
        "Archivist",
    ]
    fallback_large = [
        "Supervisor",
        "RepoScout",
        "Researcher",
        "InterfaceMapper",
        "Coder",
        "TesterAuditor",
        "Verifier",
        "Archivist",
    ]

    # ── Route selection ───────────────────────────────────────────────────
    # Implementation intent overrides evaluation route — if the user asks to
    # implement code AND evaluate it, implementation wins.
    if wants_implementation:
        # Implementation-required: pick the right-sized route that includes
        # an implementation executor (Coder).
        if looks_large:
            route_key = "large_or_risky_task"
            task_size = _configured_route_size(routing_config, route_key, "large")
            agents = _configured_route(routing_config, route_key, fallback_large)
        elif touches_interfaces:
            route_key = "interface_sensitive_task"
            task_size = _configured_route_size(routing_config, route_key, "medium")
            agents = _configured_route(routing_config, route_key, fallback_interface)
        elif wants_research:
            route_key = "research_sensitive_task"
            task_size = _configured_route_size(routing_config, route_key, "medium")
            agents = _configured_route(routing_config, route_key, fallback_research)
        elif looks_medium:
            route_key = "medium_task"
            task_size = _configured_route_size(routing_config, route_key, "medium")
            agents = _configured_route(routing_config, route_key, fallback_medium)
        else:
            route_key = "small_task"
            task_size = _configured_route_size(routing_config, route_key, "small")
            agents = _configured_route(routing_config, route_key, fallback_small)

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

    elif wants_artifact:
        route_key = "artifact_production_task"
        task_size = "medium" if artifact_type == "mixed" or looks_medium else "small"
        agents = _configured_route(routing_config, route_key, fallback_artifact)
    elif wants_evaluation:
        route_key = "evaluation_task"
        task_size = _configured_route_size(routing_config, route_key, "large")
        agents = _configured_route(routing_config, route_key, fallback_evaluation)
    elif looks_large:
        route_key = "large_or_risky_task"
        task_size = _configured_route_size(routing_config, route_key, "large")
        agents = _configured_route(routing_config, route_key, fallback_large)
    elif touches_interfaces:
        route_key = "interface_sensitive_task"
        task_size = _configured_route_size(routing_config, route_key, "medium")
        agents = _configured_route(routing_config, route_key, fallback_interface)
    elif wants_research:
        route_key = "research_sensitive_task"
        task_size = _configured_route_size(routing_config, route_key, "medium")
        agents = _configured_route(routing_config, route_key, fallback_research)
    elif looks_medium:
        route_key = "medium_task"
        task_size = _configured_route_size(routing_config, route_key, "medium")
        agents = _configured_route(routing_config, route_key, fallback_medium)
    else:
        route_key = "small_task"
        task_size = _configured_route_size(routing_config, route_key, "small")
        agents = _configured_route(routing_config, route_key, fallback_small)

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
    elif wants_artifact:
        rationale.append(
            f"Artifact production intent detected ({artifact_type}); route includes "
            f"{ARTIFACT_PRODUCER_ROLE} with an ArtifactTask contract."
        )
    if "Coder" in agents:
        rationale.append("Coder and Tester/Auditor are required for implementation and verification.")
    if ARTIFACT_PRODUCER_ROLE in agents:
        rationale.append("ArtifactProducer owns non-code and mixed deliverables; Coder remains scoped to code/automation work.")
    elif wants_implementation:
        rationale.append(
            "Implementation required but Coder not in route — "
            "check executor availability."
        )
    else:
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
