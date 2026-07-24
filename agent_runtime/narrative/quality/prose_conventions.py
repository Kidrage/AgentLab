"""Deterministic Chinese prose conventions for the narrative production seam.

This module deliberately owns only rules that can be checked without literary
judgement.  Mechanical dialogue errors may block Writer materialization;
rhetorical repetition is reported as an editorial revision request instead.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import re
from typing import Any


REPORT_SCHEMA = "prose-conventions-report/v1"
LOCAL_REPAIR_RECEIPT_SCHEMA = "local-prose-repair-receipt/v1"

DEFAULT_POLICY: dict[str, Any] = {
    "schema_version": "prose-conventions-policy/v1",
    "dialogue": {
        "outer_quotes": ["“", "”"],
        "nested_quotes": ["‘", "’"],
        "block_ascii_quotes_around_han": True,
        "block_high_confidence_unquoted_direct_speech": True,
    },
    "rhetoric": {
        "warning_cluster": {"count": 2, "han_window": 400},
        "revision_cluster": {"count": 3, "han_window": 800},
        "warning_density_per_1000": 4.0,
        "revision_density_per_1000": 6.0,
    },
    "document": {
        "block_meta_sections": True,
        "long_chapter_han_threshold": 3000,
        "minimum_long_chapter_paragraphs": 12,
        "maximum_paragraph_han": 800,
    },
}

_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_CODE_FENCE = re.compile(r"```.*?```", re.DOTALL)
_MARKDOWN_HEADING = re.compile(r"(?m)^\s{0,3}#{1,6}\s+.*$")
_ASCII_HAN_QUOTE = re.compile(
    r"(?P<quote>[\"'])(?=[^\n]*[\u3400-\u4dbf\u4e00-\u9fff])[^\n]*?(?P=quote)"
)
_DIRECT_SPEECH = re.compile(
    r"(?m)(?:^|[。！？!?]\s*)"
    r"(?P<speaker>[A-Za-z\u3400-\u4dbf\u4e00-\u9fff·]{1,20})"
    r"(?P<verb>低声说|沉声说|轻声说|大声说|回答|答道|问道|喊道|说道|说|问|喊|道)"
    r"\s*[：:]\s*(?![“])"
    r"(?P<utterance>[\u3400-\u4dbf\u4e00-\u9fff][^\n]{1,120})"
)

_RHETORICAL_FAMILIES: dict[str, re.Pattern[str]] = {
    "not_but": re.compile(r"不是.{0,36}?(?:而是|，是|,是)"),
    "not_really_but": re.compile(r"并非.{0,36}?而是"),
    "none_only": re.compile(r"没有.{0,36}?只有"),
    "not_about_but_about": re.compile(r"不在于.{0,36}?而在于"),
    "rather_than": re.compile(r"与其.{0,36}?不如"),
}
_QUOTE_CHARACTERS = frozenset("\"'“”‘’")
_META_SECTION = re.compile(
    r"(?im)^\s*(?:#{1,6}\s*|\*\*)?"
    r"(?:读者疑问|作者注|作者说明|创作说明|写作说明|章节总结|审稿说明)"
    r"(?:\*\*)?\s*[：:]?"
)


def _merged_policy(policy: Mapping[str, Any] | None) -> dict[str, Any]:
    merged = {
        "schema_version": DEFAULT_POLICY["schema_version"],
        "dialogue": dict(DEFAULT_POLICY["dialogue"]),
        "rhetoric": {
            key: dict(value) if isinstance(value, Mapping) else value
            for key, value in DEFAULT_POLICY["rhetoric"].items()
        },
        "document": dict(DEFAULT_POLICY["document"]),
    }
    if not isinstance(policy, Mapping):
        return merged
    for section in ("dialogue", "rhetoric", "document"):
        incoming = policy.get(section)
        if not isinstance(incoming, Mapping):
            continue
        for key, value in incoming.items():
            if isinstance(value, Mapping) and isinstance(
                merged[section].get(key), Mapping
            ):
                merged[section][key] = {**merged[section][key], **dict(value)}
            else:
                merged[section][key] = value
    # Project overrides may tighten these gates, never disable or weaken the
    # global mechanical/editorial floor.
    merged["dialogue"]["block_ascii_quotes_around_han"] = True
    merged["dialogue"]["block_high_confidence_unquoted_direct_speech"] = True
    for key in ("warning_cluster", "revision_cluster"):
        configured = merged["rhetoric"].get(key) or {}
        floor = DEFAULT_POLICY["rhetoric"][key]
        try:
            configured_count = int(configured.get("count", floor["count"]))
            configured_window = int(
                configured.get("han_window", floor["han_window"])
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid prose rhetoric policy: {key}") from exc
        merged["rhetoric"][key] = {
            "count": max(1, min(configured_count, floor["count"])),
            "han_window": max(configured_window, floor["han_window"]),
        }
    for key in ("warning_density_per_1000", "revision_density_per_1000"):
        try:
            merged["rhetoric"][key] = min(
                float(merged["rhetoric"].get(key, DEFAULT_POLICY["rhetoric"][key])),
                float(DEFAULT_POLICY["rhetoric"][key]),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid prose rhetoric policy: {key}") from exc
    return merged


def _document_issues(
    text: str,
    policy: Mapping[str, Any],
    chapter_context: Mapping[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if policy.get("block_meta_sections", True):
        for match in _META_SECTION.finditer(text):
            issues.append(
                {
                    "id": "non_prose_meta_section",
                    "severity": "blocked",
                    "scope": "local",
                    "locator": _line_locator(text, match.start()),
                    "message": "fiction draft contains an editorial or reader-question section",
                }
            )

    body = _MARKDOWN_HEADING.sub("", _CODE_FENCE.sub("", text))
    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", body)
        if _HAN.search(paragraph)
    ]
    paragraph_han = [len(_HAN.findall(paragraph)) for paragraph in paragraphs]
    han_count = sum(paragraph_han)
    max_paragraph_han = max(paragraph_han, default=0)
    context = chapter_context if isinstance(chapter_context, Mapping) else {}
    if context.get("enforce_paragraph_structure") is True:
        maximum = int(policy.get("maximum_paragraph_han", 800))
        for index, count in enumerate(paragraph_han, start=1):
            if count > maximum:
                issues.append(
                    {
                        "id": "mega_paragraph",
                        "severity": "blocked",
                        "scope": "local",
                        "locator": f"paragraph:{index}",
                        "han_characters": count,
                        "message": "paragraph exceeds the deterministic readability ceiling",
                    }
                )
        long_threshold = int(policy.get("long_chapter_han_threshold", 3000))
        minimum_paragraphs = int(
            policy.get("minimum_long_chapter_paragraphs", 12)
        )
        if han_count >= long_threshold and len(paragraphs) < minimum_paragraphs:
            issues.append(
                {
                    "id": "insufficient_paragraph_breaks",
                    "severity": "blocked",
                    "scope": "chapter",
                    "paragraph_count": len(paragraphs),
                    "message": "long-form chapter has too few prose paragraphs",
                }
            )

    forbidden = context.get("forbidden_facts") or []
    if isinstance(forbidden, list):
        for marker in forbidden:
            marker = str(marker or "").strip()
            if marker and marker in text:
                issues.append(
                    {
                        "id": "forbidden_story_fact",
                        "severity": "blocked",
                        "scope": "chapter",
                        "marker": marker,
                        "locator": _line_locator(text, text.index(marker)),
                        "message": "candidate introduces a chapter-contract forbidden fact",
                    }
                )
    return issues, {
        "paragraph_count": len(paragraphs),
        "max_paragraph_han": max_paragraph_han,
        "average_paragraph_han": (
            round(han_count / len(paragraphs), 3) if paragraphs else 0.0
        ),
    }


def _excluded_mask(prose: str) -> str:
    """Replace non-prose regions with spaces while preserving offsets."""

    chars = list(prose)
    for pattern in (_CODE_FENCE, _MARKDOWN_HEADING):
        for match in pattern.finditer(prose):
            chars[match.start() : match.end()] = " " * (match.end() - match.start())
    return "".join(chars)


def _line_locator(text: str, offset: int) -> str:
    return f"L{text.count(chr(10), 0, offset) + 1}"


def _dialogue_issues(text: str, policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    stack: list[tuple[str, int]] = []
    pairs = {"“": "”", "‘": "’"}
    closing = {value: key for key, value in pairs.items()}
    for offset, char in enumerate(text):
        if char in pairs:
            if char == "‘" and not any(opening == "“" for opening, _ in stack):
                issues.append(
                    {
                        "id": "misnested_chinese_dialogue_quote",
                        "severity": "blocked",
                        "scope": "local",
                        "locator": _line_locator(text, offset),
                        "message": "nested Chinese quote appears outside an outer dialogue quote",
                    }
                )
            stack.append((char, offset))
        elif char in closing:
            expected_open = closing[char]
            if not stack or stack[-1][0] != expected_open:
                issues.append(
                    {
                        "id": "misnested_chinese_dialogue_quote",
                        "severity": "blocked",
                        "scope": "local",
                        "locator": _line_locator(text, offset),
                        "message": f"unexpected closing quote {char}",
                    }
                )
            else:
                stack.pop()
    for opening, offset in stack:
        issues.append(
            {
                "id": "unclosed_chinese_dialogue_quote",
                "severity": "blocked",
                "scope": "local",
                "locator": _line_locator(text, offset),
                "message": f"opening quote {opening} is not closed",
            }
        )

    if policy.get("block_ascii_quotes_around_han", True):
        for match in _ASCII_HAN_QUOTE.finditer(text):
            issues.append(
                {
                    "id": "ascii_quote_for_chinese_dialogue",
                    "severity": "blocked",
                    "scope": "local",
                    "locator": _line_locator(text, match.start()),
                    "message": "Chinese dialogue must use curly Chinese quotation marks",
                }
            )

    if policy.get("block_high_confidence_unquoted_direct_speech", True):
        for match in _DIRECT_SPEECH.finditer(text):
            issues.append(
                {
                    "id": "unquoted_direct_speech",
                    "severity": "blocked",
                    "scope": "local",
                    "locator": _line_locator(text, match.start("utterance")),
                    "message": "high-confidence direct speech is missing outer Chinese quotes",
                    "speaker": match.group("speaker"),
                }
            )
    return issues


def _without_dialogue(text: str) -> str:
    chars = list(text)
    stack: list[tuple[str, int]] = []
    pairs = {"“": "”", "‘": "’"}
    for offset, char in enumerate(text):
        if char in pairs:
            stack.append((char, offset))
            continue
        if char not in {"”", "’"} or not stack:
            continue
        opening, start = stack[-1]
        if (opening, char) not in {("“", "”"), ("‘", "’")}:
            continue
        stack.pop()
        if opening == "“" and not stack:
            chars[start : offset + 1] = " " * (offset + 1 - start)
    return "".join(chars)


def _han_position(text: str, offset: int) -> int:
    return len(_HAN.findall(text[:offset]))


def _rhetorical_issues(
    narrative: str, policy: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    issues: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    all_occurrences: list[tuple[int, str]] = []
    for family, pattern in _RHETORICAL_FAMILIES.items():
        matches = list(pattern.finditer(narrative))
        counts[family] = len(matches)
        all_occurrences.extend(
            (_han_position(narrative, match.start()), family) for match in matches
        )
    all_occurrences.sort()

    revision = policy.get("revision_cluster") or {}
    warning = policy.get("warning_cluster") or {}
    revision_count = int(revision.get("count", 3))
    revision_window = int(revision.get("han_window", 800))
    warning_count = int(warning.get("count", 2))
    warning_window = int(warning.get("han_window", 400))

    for family in _RHETORICAL_FAMILIES:
        positions = [pos for pos, item_family in all_occurrences if item_family == family]
        severity = ""
        if any(
            positions[index + revision_count - 1] - positions[index]
            <= revision_window
            for index in range(max(0, len(positions) - revision_count + 1))
        ):
            severity = "revision_required"
        elif any(
            positions[index + warning_count - 1] - positions[index] <= warning_window
            for index in range(max(0, len(positions) - warning_count + 1))
        ):
            severity = "warning"
        if severity:
            issues.append(
                {
                    "id": "rhetorical_family_cluster",
                    "severity": severity,
                    "scope": "local",
                    "family": family,
                    "count": len(positions),
                    "message": "contrast-template family repeats inside the configured Han-character window",
                }
            )

    han_count = max(1, len(_HAN.findall(narrative)))
    density = len(all_occurrences) * 1000 / han_count
    density_severity = ""
    if density > float(policy.get("revision_density_per_1000", 6.0)):
        density_severity = "revision_required"
    elif density > float(policy.get("warning_density_per_1000", 4.0)):
        density_severity = "warning"
    if density_severity:
        issues.append(
            {
                "id": "rhetorical_template_density",
                "severity": density_severity,
                "scope": "chapter",
                "density_per_1000_han": round(density, 3),
                "message": "contrast-template density exceeds the project prose policy",
            }
        )
    return issues, counts


def evaluate_prose_conventions(
    prose: str,
    *,
    chapter_context: Mapping[str, Any] | None = None,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate deterministic dialogue mechanics and rhetorical fatigue.

    ``chapter_context`` is recorded for traceability but is never inferred from
    prose.  Hook and character semantics belong to the chapter-contract gate.
    """

    text = str(prose or "")
    active_policy = _merged_policy(policy)
    prose_only = _excluded_mask(text)
    dialogue_issues = _dialogue_issues(prose_only, active_policy["dialogue"])
    rhetoric_issues, family_counts = _rhetorical_issues(
        _without_dialogue(prose_only), active_policy["rhetoric"]
    )
    document_issues, document_metrics = _document_issues(
        text,
        active_policy["document"],
        chapter_context,
    )
    issues = [*dialogue_issues, *document_issues, *rhetoric_issues]
    mechanical_issues = [*dialogue_issues, *document_issues]
    mechanical_status = "blocked" if mechanical_issues else "pass"
    if mechanical_status == "blocked":
        status = "blocked"
    elif any(item["severity"] == "revision_required" for item in rhetoric_issues):
        status = "revision_required"
    else:
        status = "pass"
    return {
        "schema_version": REPORT_SCHEMA,
        "status": status,
        "mechanical_status": mechanical_status,
        "style_status": (
            "revision_required"
            if any(item["severity"] == "revision_required" for item in rhetoric_issues)
            else "warning"
            if rhetoric_issues
            else "pass"
        ),
        # Quote repair is a bounded edit against the returned candidate.  It
        # must not spend another full Writer generation or alter story beats.
        "writer_rerun_needed": False,
        "local_repair_needed": mechanical_status == "blocked",
        "chapter_context": dict(chapter_context or {}),
        "policy_schema_version": active_policy["schema_version"],
        "prose_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "issues": issues,
        "metrics": {
            "han_character_count": len(_HAN.findall(prose_only)),
            "dialogue_quote_errors": len(dialogue_issues),
            "rhetorical_family_counts": family_counts,
            **document_metrics,
        },
    }


def validate_local_dialogue_repair(
    original_prose: str,
    repaired_prose: str,
    *,
    source_report: Mapping[str, Any],
    chapter_context: Mapping[str, Any] | None = None,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a quote-only repair without spending another Writer run.

    Both inputs are canonicalised to the Writer contract's one-trailing-newline
    form.  Removing all recognised quote characters must leave byte-identical
    text, so this lane cannot silently revise words, punctuation, or story
    facts.  The source report and both prose versions are hash-bound.
    """

    original = (str(original_prose or "").rstrip() + "\n") if original_prose else ""
    repaired = (str(repaired_prose or "").rstrip() + "\n") if repaired_prose else ""
    original_sha256 = hashlib.sha256(original.encode("utf-8")).hexdigest()
    repaired_sha256 = hashlib.sha256(repaired.encode("utf-8")).hexdigest()
    issues: list[str] = []
    original_report = evaluate_prose_conventions(
        original,
        chapter_context=chapter_context,
        policy=policy,
    )
    if source_report.get("schema_version") != REPORT_SCHEMA:
        issues.append("source_report_schema_mismatch")
    if dict(source_report) != original_report:
        issues.append("source_report_evidence_mismatch")
    if original_report.get("mechanical_status") != "blocked" or not original_report.get(
        "local_repair_needed"
    ):
        issues.append("source_report_does_not_authorize_local_repair")
    if source_report.get("prose_sha256") != original_sha256:
        issues.append("source_report_prose_hash_mismatch")
    strip_quotes = lambda value: "".join(  # noqa: E731 - local transformation
        char for char in value if char not in _QUOTE_CHARACTERS
    )
    if strip_quotes(original) != strip_quotes(repaired):
        issues.append("repair_changed_non_quote_content")
    if original == repaired:
        issues.append("repair_made_no_change")

    repaired_report = evaluate_prose_conventions(
        repaired,
        chapter_context=chapter_context,
        policy=policy,
    )
    if repaired_report["mechanical_status"] != "pass":
        issues.append("repair_did_not_resolve_dialogue_mechanics")
    return {
        "schema_version": LOCAL_REPAIR_RECEIPT_SCHEMA,
        "issuer": "AgentLab.LocalProseRepair",
        "status": "pass" if not issues else "blocked",
        "repair_scope": "quote_characters_only",
        "writer_rerun_triggered": False,
        "source_prose_sha256": original_sha256,
        "repaired_prose_sha256": repaired_sha256,
        "source_report_sha256": hashlib.sha256(
            json.dumps(
                dict(source_report),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "repaired_report": repaired_report,
        "issues": issues,
    }


__all__ = [
    "DEFAULT_POLICY",
    "LOCAL_REPAIR_RECEIPT_SCHEMA",
    "REPORT_SCHEMA",
    "evaluate_prose_conventions",
    "validate_local_dialogue_repair",
]
