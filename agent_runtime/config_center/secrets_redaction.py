"""Secret redaction for M2-5 Config Center.

Detects and masks secret values before they reach output/display.
"""

from __future__ import annotations

import re
from typing import Any

# Patterns that indicate a value might be a secret
_SECRET_KEY_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r".*api[_-]?key.*",
        r".*secret.*",
        r".*token.*",
        r".*password.*",
        r".*passwd.*",
        r".*credential.*",
        r".*auth[_-]?token.*",
        r".*private[_-]?key.*",
        r".*access[_-]?key.*",
    ]
]

REDACTED_PLACEHOLDER = "***REDACTED***"


def is_secret_key(key: str) -> bool:
    """Check if a key name indicates it holds a secret value."""
    return any(p.match(key) for p in _SECRET_KEY_PATTERNS)


def redact_value(value: Any) -> Any:
    """Return a redacted placeholder if value is non-empty, else the value itself."""
    if value is None:
        return None
    if isinstance(value, str) and value:
        return REDACTED_PLACEHOLDER
    if isinstance(value, (int, float)):
        return REDACTED_PLACEHOLDER
    return REDACTED_PLACEHOLDER


def redact_config(config: dict[str, Any]) -> dict[str, Any]:
    """Recursively redact secret values from a config dict.

    Keys matching secret patterns have their values replaced with a placeholder.
    """
    result: dict[str, Any] = {}
    for key, value in config.items():
        last_segment = key.rsplit(".", 1)[-1]
        if isinstance(value, dict):
            result[key] = redact_config(value)
        elif is_secret_key(last_segment):
            result[key] = redact_value(value)
        else:
            result[key] = value
    return result


def redact_config_value(cv: Any, key: str) -> Any:
    """Redact a single ConfigValue's value if its key is secret."""
    last_segment = key.rsplit(".", 1)[-1]
    if is_secret_key(last_segment):
        return redact_value(cv.value if hasattr(cv, "value") else cv)
    return cv.value if hasattr(cv, "value") else cv
