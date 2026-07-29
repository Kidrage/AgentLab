"""Rights-bound narrative craft cards.

Craft cards retain a technique and its provenance, never source prose for
imitation.  They are advisory research artifacts and cannot become canon.
"""

from __future__ import annotations

from typing import Mapping

ALLOWED_SOURCE_RIGHTS = frozenset(
    {
        "public_domain",
        "licensed",
        "user_provided",
        "author_interview",
        "criticism_research",
        "accepted_project_prose",
    }
)

_REQUIRED_TEXT_FIELDS = (
    "device",
    "mechanism",
    "reader_effect",
    "source_rights",
    "source_locator",
)
_REQUIRED_LIST_FIELDS = (
    "preconditions",
    "failure_modes",
    "applicable_scenes",
    "originality_constraints",
)
_FORBIDDEN_SOURCE_TEXT_FIELDS = frozenset(
    {
        "content",
        "excerpt",
        "full_text",
        "manuscript",
        "source_text",
        "text",
    }
)


def validate_craft_card(card: Mapping[str, object]) -> list[str]:
    """Return stable validation issues for one ``narrative-craft-card/v1``."""

    issues: list[str] = []
    for field in _REQUIRED_TEXT_FIELDS:
        value = card.get(field)
        if not isinstance(value, str) or not value.strip():
            issues.append(f"{field}_required")
    for field in _REQUIRED_LIST_FIELDS:
        value = card.get(field)
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) and item.strip() for item in value)
        ):
            issues.append(f"{field}_required")

    source_rights = card.get("source_rights")
    if (
        isinstance(source_rights, str)
        and source_rights
        and source_rights not in ALLOWED_SOURCE_RIGHTS
    ):
        issues.append(f"source_rights_not_allowed:{source_rights}")

    for field in sorted(_FORBIDDEN_SOURCE_TEXT_FIELDS.intersection(card)):
        issues.append(f"source_text_storage_forbidden:{field}")

    if source_rights == "accepted_project_prose":
        source_sha256 = card.get("source_sha256")
        if (
            not isinstance(source_sha256, str)
            or len(source_sha256) != 64
            or any(char not in "0123456789abcdef" for char in source_sha256)
        ):
            issues.append("accepted_project_prose_source_sha256_required")
    return issues
