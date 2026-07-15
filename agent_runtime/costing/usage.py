"""Usage normalization for CostLedger v2."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

USAGE_SOURCES = {
    "api_usage",
    "external_cli_reported",
    "external_cli_estimate",
    "external_cli_unavailable",
    "hermes_session_usage",
    "hermes_message_complete_usage",
    "local_estimate",
    "manual_entry",
    "no_llm_call",
    "unknown",
}


def _token_value(raw: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = raw.get(key)
        if value is None:
            continue
        try:
            return max(int(value), 0)
        except (TypeError, ValueError):
            return 0
    return 0


@dataclass
class UsageRecord:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    image_input_tokens: int = 0
    audio_input_tokens: int = 0
    usage_source: str = "unknown"

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
            + self.reasoning_tokens
            + self.image_input_tokens
            + self.audio_input_tokens
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_usage(raw_usage: dict[str, Any] | None, *, usage_source: str | None = None) -> UsageRecord:
    """Convert provider-specific usage dicts into CostLedger v2 fields.

    The mapper is intentionally permissive: incomplete usage is preserved with
    zero token counts and an ``unknown`` source instead of failing the run.
    """
    raw = raw_usage or {}
    source = usage_source or raw.get("usage_source")
    if not source:
        source = "api_usage" if raw_usage else "unknown"
    if source not in USAGE_SOURCES:
        source = "unknown"

    return UsageRecord(
        input_tokens=_token_value(raw, "input_tokens", "prompt_tokens", "prompt"),
        output_tokens=_token_value(raw, "output_tokens", "completion_tokens", "completion"),
        cache_read_tokens=_token_value(raw, "cache_read_tokens", "cached_tokens", "cached_input_tokens"),
        cache_write_tokens=_token_value(raw, "cache_write_tokens"),
        reasoning_tokens=_token_value(raw, "reasoning_tokens"),
        image_input_tokens=_token_value(raw, "image_input_tokens"),
        audio_input_tokens=_token_value(raw, "audio_input_tokens"),
        usage_source=source,
    )
