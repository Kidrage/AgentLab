"""Deterministic prose-length contracts for narrative candidates."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any


HAN_CHARACTER_UNIT = "han_characters_excluding_markdown_headings"
_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def build_han_character_contract(
    target: tuple[int, int] | list[int] | None,
) -> dict[str, Any] | None:
    """Normalize a validated CreativeBrief target into a hard contract."""
    if target is None or len(target) != 2:
        return None
    minimum, maximum = int(target[0]), int(target[1])
    if minimum <= 0 or maximum < minimum:
        return None
    return {
        "unit": HAN_CHARACTER_UNIT,
        "minimum": minimum,
        "maximum": maximum,
    }


def normalize_han_character_contract(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or value.get("unit") != HAN_CHARACTER_UNIT:
        return None
    try:
        minimum = int(value.get("minimum"))
        maximum = int(value.get("maximum"))
    except (TypeError, ValueError):
        return None
    return build_han_character_contract((minimum, maximum))


def count_han_characters(prose: str) -> int:
    """Count Han characters in prose body, excluding Markdown headings."""
    body = "\n".join(
        line for line in prose.splitlines() if not line.lstrip().startswith("#")
    )
    return len(_HAN.findall(body))


def evaluate_han_character_contract(
    prose: str,
    contract: object,
) -> dict[str, Any]:
    normalized = normalize_han_character_contract(contract)
    if normalized is None:
        return {
            "status": "blocked",
            "issue": "fiction_draft_han_character_contract_invalid",
            "han_character_count": count_han_characters(prose),
            "contract": None,
        }
    observed = count_han_characters(prose)
    minimum = int(normalized["minimum"])
    maximum = int(normalized["maximum"])
    issue = ""
    if observed < minimum:
        issue = f"fiction_draft_han_characters_below_minimum:{observed}<{minimum}"
    elif observed > maximum:
        issue = f"fiction_draft_han_characters_above_maximum:{observed}>{maximum}"
    return {
        "status": "blocked" if issue else "pass",
        "issue": issue,
        "han_character_count": observed,
        "contract": normalized,
    }
