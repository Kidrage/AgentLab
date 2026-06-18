"""Assumption, unknown, and decision-card builder for AgentLab S1-C/D/E/F.

This module performs deterministic compile-time extraction only. It does not ask
users questions, read repositories, inspect files, execute shell commands, call
web search, or integrate with a runtime decision-card system. The returned cards
are plain dictionaries that the Task Compiler can carry forward as planning
metadata.
"""

from __future__ import annotations

import re
from typing import Any


SUPPORTED_CAPABILITIES = {
    "file_read",
    "file_write",
    "code_edit",
    "repo_inspection",
    "test_execution",
    "long_document_reading",
    "spreadsheet_processing",
    "data_analysis",
    "local_shell",
    "human_approval",
}

REPO_SCOPE_RE = re.compile(r"\b(repo|repository|github|path|folder|branch|file|checkout|worktree)\b", re.I)
RESEARCH_REGION_RE = re.compile(r"\b(region|country|market|global|us|usa|europe|china|asia|worldwide)\b", re.I)
RESEARCH_TIME_RE = re.compile(r"\b(latest|current|today|recent|202\d|timeframe|as of|this year)\b", re.I)
RESEARCH_SOURCE_RE = re.compile(r"\b(source|citation|cite|sources|evidence|official|primary)\b", re.I)
CREATIVE_GENRE_RE = re.compile(r"\b(novel|story|script|chapter|fiction|genre|sci-fi|fantasy|thriller|romance)\b", re.I)
CREATIVE_TONE_RE = re.compile(r"\b(tone|voice|style|dark|funny|serious|lyrical|audience)\b", re.I)
CREATIVE_LENGTH_RE = re.compile(r"\b(length|words|pages|chapter|short|long|scene|outline)\b", re.I)
DOCUMENT_INPUT_RE = re.compile(r"\b(pdf|docx|document|file|path|table|image|scan)\b", re.I)
DOCUMENT_OUTPUT_RE = re.compile(r"\b(markdown|csv|json|yaml|table|summary|output|format|extract)\b", re.I)
DATA_SOURCE_RE = re.compile(r"\b(csv|xlsx|spreadsheet|dataset|database|data source|dataframe|file)\b", re.I)
DATA_SCHEMA_RE = re.compile(r"\b(schema|columns|fields|table|rows|dataframe|spreadsheet)\b", re.I)
DATA_GOAL_RE = re.compile(r"\b(analyze|chart|statistics|forecast|model|report|clean|benchmark|evaluate)\b", re.I)
AUDIO_INPUT_RE = re.compile(r"\b(audio|music|stem|mix|wav|mp3|asset|input|track|file)\b", re.I)
AUDIO_TARGET_RE = re.compile(r"\b(playback|speaker|headphone|binaural|hrtf|loudness|mix|master|spatial)\b", re.I)
AUDIO_METHOD_RE = re.compile(r"\b(measure|analysis|evaluate|listen|validation|method|meter|spectrogram)\b", re.I)
VISUAL_INPUT_RE = re.compile(r"\b(image|screenshot|video|photo|diagram|figure|frame|file|path)\b", re.I)
DESTRUCTIVE_RE = re.compile(r"\b(delete|remove|overwrite|move|cleanup|clean up|rm\s+-|deploy|format|filesystem)\b", re.I)
FRESHNESS_RE = re.compile(r"\b(latest|current|today|recent|now|this year)\b", re.I)


def _dedupe(items: list[str]) -> list[str]:
    """Deduplicate while preserving first-seen order."""

    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _normalize_task_type(task_type: str) -> str:
    """Normalize enum-like task types to plain lowercase strings."""

    value = getattr(task_type, "value", task_type)
    return str(value or "unknown").strip().lower() or "unknown"


def _decision_card(kind: str, title: str, reason: str, required: bool = True, **extra: Any) -> dict[str, Any]:
    """Create a simple deterministic decision-card dictionary."""

    card: dict[str, Any] = {
        "kind": kind,
        "title": title,
        "reason": reason,
        "required": required,
    }
    card.update(extra)
    return card


def _missing_context_card(title: str, unknown: str) -> dict[str, Any]:
    """Create a missing-context card with backward-compatible clarification text."""

    return _decision_card(
        "missing_context",
        title,
        f"Clarification needed before high-risk execution: {unknown}",
        True,
        unknown=unknown,
    )


def _capability_gap_cards(required_capabilities: list[str]) -> list[dict[str, Any]]:
    """Build capability-gap cards for unsupported capabilities."""

    cards: list[dict[str, Any]] = []
    gaps = [capability for capability in required_capabilities if capability not in SUPPORTED_CAPABILITIES]
    if gaps:
        cards.append(
            _decision_card(
                "capability_gap",
                "Required capability is not implemented locally",
                "Capability gap must be acknowledged before execution.",
                True,
                required_capabilities=_dedupe(gaps),
            )
        )
    return cards


def _coding_unknowns(prompt: str) -> list[str]:
    """Return coding/debugging unknowns for missing repo/path/branch context."""

    if REPO_SCOPE_RE.search(prompt):
        return []
    return ["Coding task lacks an explicit repository, path, or branch scope."]


def _research_unknowns(prompt: str) -> list[str]:
    """Return research/business unknowns for source scope and freshness."""

    unknowns: list[str] = []
    if not RESEARCH_REGION_RE.search(prompt):
        unknowns.append("Research task lacks target region or market scope.")
    if not RESEARCH_TIME_RE.search(prompt):
        unknowns.append("Research task lacks timeframe or freshness requirement.")
    if not RESEARCH_SOURCE_RE.search(prompt):
        unknowns.append("Research task lacks source policy or citation requirements.")
    return unknowns


def _creative_unknowns(prompt: str) -> list[str]:
    """Return creative-writing unknowns for brief completeness."""

    unknowns: list[str] = []
    if not CREATIVE_GENRE_RE.search(prompt):
        unknowns.append("Creative task lacks genre or form.")
    if not CREATIVE_TONE_RE.search(prompt):
        unknowns.append("Creative task lacks tone, voice, audience, or style guidance.")
    if not CREATIVE_LENGTH_RE.search(prompt):
        unknowns.append("Creative task lacks length, structure, or outline expectations.")
    return unknowns


def _document_unknowns(prompt: str) -> list[str]:
    """Return document-processing unknowns for input and output scope."""

    unknowns: list[str] = []
    if not DOCUMENT_INPUT_RE.search(prompt):
        unknowns.append("Document task lacks input file, path, or document scope.")
    if not DOCUMENT_OUTPUT_RE.search(prompt):
        unknowns.append("Document task lacks requested output format or extraction target.")
    return unknowns


def _data_unknowns(prompt: str) -> list[str]:
    """Return data-analysis unknowns for source, schema, and goal."""

    unknowns: list[str] = []
    if not DATA_SOURCE_RE.search(prompt):
        unknowns.append("Data task lacks data source or file reference.")
    if not DATA_SCHEMA_RE.search(prompt):
        unknowns.append("Data task lacks schema, columns, or field expectations.")
    if not DATA_GOAL_RE.search(prompt):
        unknowns.append("Data task lacks output goal or analysis objective.")
    return unknowns


def _audio_unknowns(prompt: str) -> list[str]:
    """Return audio/music unknowns for assets and evaluation method."""

    unknowns: list[str] = []
    if not AUDIO_INPUT_RE.search(prompt):
        unknowns.append("Audio task lacks input asset or file reference.")
    if not AUDIO_TARGET_RE.search(prompt):
        unknowns.append("Audio task lacks playback target or listening context.")
    if not AUDIO_METHOD_RE.search(prompt):
        unknowns.append("Audio task lacks evaluation method or validation approach.")
    return unknowns


def _visual_unknowns(prompt: str) -> list[str]:
    """Return multimodal unknowns for missing image/video references."""

    if VISUAL_INPUT_RE.search(prompt):
        return []
    return ["Multimodal task lacks image, video, screenshot, file, or path reference."]


def _unknowns_for_task(prompt: str, task_type: str) -> list[str]:
    """Dispatch deterministic unknown extraction by normalized task type."""

    normalized = _normalize_task_type(task_type)
    if normalized in {"coding", "debugging"}:
        return _coding_unknowns(prompt)
    if normalized in {"research", "business"}:
        return _research_unknowns(prompt)
    if normalized == "creative_longform":
        return _creative_unknowns(prompt)
    if normalized == "document_processing":
        return _document_unknowns(prompt)
    if normalized == "data_analysis":
        return _data_unknowns(prompt)
    if normalized == "audio_music":
        return _audio_unknowns(prompt)
    if normalized == "multimodal":
        return _visual_unknowns(prompt)
    if normalized == "local_ops":
        return ["Local ops task requires exact path scope, dry-run boundary, and approval policy."]
    if normalized == "unknown":
        return ["Primary task type could not be classified from deterministic keyword signals."]
    return []


def _base_assumptions(prompt: str, task_type: str, domain_signals: list[str]) -> list[str]:
    """Build deterministic assumptions shared by all domains."""

    normalized = _normalize_task_type(task_type)
    assumptions = [
        "The compiler only creates planning data and must not execute tools or mutate runtime state.",
        f"The selected task type is inferred deterministically as {normalized}.",
    ]
    if domain_signals:
        assumptions.append("Domain signals are heuristic planning evidence, not proof of runtime capability.")
    if FRESHNESS_RE.search(prompt):
        assumptions.append("Fresh sources are required before final factual claims are accepted.")
    return assumptions


def build_assumptions_and_unknowns(
    user_prompt: str,
    task_type: str,
    domain_signals: list[str],
    required_capabilities: list[str],
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """Build deterministic assumptions, unknowns, and decision cards.

    The tuple means ``assumptions``, ``unknowns``, and ``decision_cards``. Cards
    are simple dictionaries and are not wired into a runtime card system yet.
    """

    prompt = str(user_prompt or "")
    normalized = _normalize_task_type(task_type)
    assumptions = _base_assumptions(prompt, normalized, domain_signals)
    unknowns = _unknowns_for_task(prompt, normalized)
    cards: list[dict[str, Any]] = []

    for unknown in unknowns:
        cards.append(_missing_context_card("Missing context before execution", unknown))

    if normalized == "local_ops" or DESTRUCTIVE_RE.search(prompt):
        cards.append(
            _decision_card(
                "human_approval",
                "Human approval required for local or destructive operation",
                "Local filesystem, shell, cleanup, delete, move, or deploy work needs approval, dry-run, and rollback.",
                True,
            )
        )

    cards.extend(_capability_gap_cards(required_capabilities))

    if FRESHNESS_RE.search(prompt):
        cards.append(
            _decision_card(
                "risk_review",
                "Fresh source review required",
                "Prompt asks for latest/current/today facts, so source freshness must be checked before final answer.",
                True,
            )
        )

    if normalized == "unknown":
        cards.append(
            _decision_card(
                "human_approval",
                "Human approval required for unknown task type",
                "Ambiguous classification needs clarification before execution.",
                True,
            )
        )

    return _dedupe(assumptions), _dedupe(unknowns), cards
