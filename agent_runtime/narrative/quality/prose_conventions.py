"""Deterministic Chinese prose conventions for the narrative production seam.

This module deliberately owns only rules that can be checked without literary
judgement.  Mechanical dialogue errors may block Writer materialization;
rhetorical repetition is reported as an editorial revision request instead.
"""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any


REPORT_SCHEMA = "prose-conventions-report/v1"

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


def _merged_policy(policy: Mapping[str, Any] | None) -> dict[str, Any]:
    merged = {
        "schema_version": DEFAULT_POLICY["schema_version"],
        "dialogue": dict(DEFAULT_POLICY["dialogue"]),
        "rhetoric": {
            key: dict(value) if isinstance(value, Mapping) else value
            for key, value in DEFAULT_POLICY["rhetoric"].items()
        },
    }
    if not isinstance(policy, Mapping):
        return merged
    for section in ("dialogue", "rhetoric"):
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
    return merged


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
    issues = [*dialogue_issues, *rhetoric_issues]
    mechanical_status = "blocked" if dialogue_issues else "pass"
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
        "writer_rerun_needed": mechanical_status == "blocked",
        "chapter_context": dict(chapter_context or {}),
        "policy_schema_version": active_policy["schema_version"],
        "issues": issues,
        "metrics": {
            "han_character_count": len(_HAN.findall(prose_only)),
            "dialogue_quote_errors": len(dialogue_issues),
            "rhetorical_family_counts": family_counts,
        },
    }


__all__ = ["DEFAULT_POLICY", "REPORT_SCHEMA", "evaluate_prose_conventions"]
